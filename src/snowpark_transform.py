"""
snowpark_transform.py
----------------------
Transformation layer (Step 3-4): everything here runs INSIDE Snowflake via
Snowpark, per the requirement "transformations must be in Snowflake." No
data is pulled into local pandas -- Snowpark pushes down the compute
(pushdown SQL) so this scales to full production volumes.

Why Snowpark (not raw SQL): the requirement was "entire logic in Python."
Snowpark gives a DataFrame API that looks like pandas but compiles to SQL
executed by the Snowflake warehouse, so we get Python ergonomics with
warehouse-scale performance and no data egress.

Pipeline performed here:
  1. Create an external stage pointing at the S3 raw landing zone.
  2. COPY INTO a raw table (schema-on-read, VARCHAR-safe landing).
  3. Cast/clean into a typed staging DataFrame.
  4. Add derived columns: total_sales, month, year, month_year.
  5. Compute the 5 required metrics as curated tables:
       - product_leaderboard
       - regional_sales
       - monthly_trend
       - units_vs_revenue
       - aov_summary (overall + by region + by product)
  6. Write each curated result back to Snowflake tables for the dashboard
     to read.

This script requires a live Snowflake account (see .env.example /
SnowflakeConfig). It is not executed as part of this session since no
Snowflake credentials are connected here -- run it from an environment
where SNOWFLAKE_ACCOUNT/USER/PASSWORD are set.
"""

import logging
import sys
from contextlib import contextmanager

from config import aws_config, snowflake_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("snowpark_transform")

try:
    from snowflake.snowpark import Session
    from snowflake.snowpark.functions import col, month, year, round as sp_round, sum as sp_sum, concat_ws, lit
    from snowflake.snowpark.exceptions import SnowparkSQLException
except ImportError:  # pragma: no cover
    Session = None


class TransformError(Exception):
    """Raised when a Snowpark transformation step fails."""


@contextmanager
def snowpark_session():
    """Yields a Snowpark Session, guaranteeing it is closed even on failure."""
    if Session is None:
        raise TransformError(
            "snowflake-snowpark-python is not installed. "
            "Run `pip install snowflake-snowpark-python`."
        )
    if not snowflake_config.has_credentials:
        raise TransformError(
            "Snowflake credentials are not configured. Set SNOWFLAKE_ACCOUNT / "
            "SNOWFLAKE_USER / SNOWFLAKE_PASSWORD in your environment."
        )

    session = None
    try:
        session = Session.builder.configs(snowflake_config.connection_params()).create()
        logger.info("Snowpark session created (account=%s, warehouse=%s)",
                    snowflake_config.account, snowflake_config.warehouse)
        yield session
    except SnowparkSQLException as exc:
        raise TransformError(f"Snowflake SQL error: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - surface any connection failure clearly
        raise TransformError(f"Failed to create Snowpark session: {exc}") from exc
    finally:
        if session is not None:
            session.close()
            logger.info("Snowpark session closed.")


def setup_external_stage(session) -> None:
    """Create the DB/schema/external stage pointing at the S3 raw landing zone."""
    try:
        session.sql(f"CREATE DATABASE IF NOT EXISTS {snowflake_config.database}").collect()
        session.sql(
            f"CREATE SCHEMA IF NOT EXISTS {snowflake_config.database}.{snowflake_config.schema}"
        ).collect()
        session.sql(f"""
            CREATE STAGE IF NOT EXISTS {snowflake_config.stage_name}
            URL = 's3://{aws_config.bucket_name}/{aws_config.raw_prefix}'
            CREDENTIALS = (AWS_KEY_ID = '{aws_config.access_key_id}'
                            AWS_SECRET_KEY = '{aws_config.secret_access_key}')
            FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"')
        """).collect()
        logger.info("External stage %s ready.", snowflake_config.stage_name)
    except SnowparkSQLException as exc:
        raise TransformError(f"Failed to set up external stage: {exc}") from exc


def load_raw_table(session):
    """COPY INTO the raw table from the external S3 stage."""
    try:
        session.sql(f"""
            CREATE OR REPLACE TABLE {snowflake_config.raw_table} (
                DATE_RAW STRING, PRODUCT STRING, REGION STRING,
                UNITS_SOLD STRING, UNIT_PRICE STRING, SALES STRING
            )
        """).collect()
        session.sql(f"""
            COPY INTO {snowflake_config.raw_table}
            FROM @{snowflake_config.stage_name}
            ON_ERROR = 'ABORT_STATEMENT'
        """).collect()
        raw_df = session.table(snowflake_config.raw_table)
        logger.info("Loaded raw table %s (%d rows).", snowflake_config.raw_table, raw_df.count())
        return raw_df
    except SnowparkSQLException as exc:
        raise TransformError(f"Failed to load raw table: {exc}") from exc


def clean_and_derive(raw_df):
    """Cast raw VARCHAR columns to proper types and add derived columns."""
    try:
        typed = raw_df.select(
            col("DATE_RAW").cast("date").alias("SALE_DATE"),
            col("PRODUCT"),
            col("REGION"),
            col("UNITS_SOLD").cast("integer").alias("UNITS_SOLD"),
            col("UNIT_PRICE").cast("float").alias("UNIT_PRICE"),
            col("SALES").cast("float").alias("TOTAL_SALES"),
        )
        # Guard against nulls introduced by bad casts (Step 2 quality requirement)
        clean = typed.dropna(subset=["SALE_DATE", "PRODUCT", "REGION", "UNITS_SOLD", "UNIT_PRICE"])
        derived = clean.with_columns(
            ["MONTH", "YEAR", "MONTH_YEAR"],
            [
                month(col("SALE_DATE")),
                year(col("SALE_DATE")),
                concat_ws(lit("-"), year(col("SALE_DATE")), month(col("SALE_DATE"))),
            ],
        )
        derived.write.mode("overwrite").save_as_table(snowflake_config.curated_table)
        logger.info("Curated table %s written (%d rows).",
                    snowflake_config.curated_table, derived.count())
        return derived
    except SnowparkSQLException as exc:
        raise TransformError(f"Failed during clean/derive step: {exc}") from exc


def compute_metrics(session, curated_df) -> None:
    """Compute and persist the 5 required business metrics (Step 5)."""
    try:
        # 5.1 Product Sales Leaderboard
        product_leaderboard = (
            curated_df.group_by("PRODUCT")
            .agg(sp_sum("TOTAL_SALES").alias("TOTAL_REVENUE"))
            .sort(col("TOTAL_REVENUE").desc())
        )
        product_leaderboard.write.mode("overwrite").save_as_table("PRODUCT_LEADERBOARD")

        # 5.2 Regional Sales Comparison
        regional_sales = (
            curated_df.group_by("REGION")
            .agg(sp_sum("TOTAL_SALES").alias("TOTAL_REVENUE"))
            .sort(col("TOTAL_REVENUE").desc())
        )
        regional_sales.write.mode("overwrite").save_as_table("REGIONAL_SALES")

        # 5.3 Monthly Trend Analysis
        monthly_trend = (
            curated_df.group_by("YEAR", "MONTH", "MONTH_YEAR")
            .agg(sp_sum("TOTAL_SALES").alias("TOTAL_REVENUE"))
            .sort(col("YEAR"), col("MONTH"))
        )
        monthly_trend.write.mode("overwrite").save_as_table("MONTHLY_TREND")

        # 5.4 Units Sold vs Revenue
        units_vs_revenue = curated_df.group_by("PRODUCT").agg(
            sp_sum("UNITS_SOLD").alias("TOTAL_UNITS"),
            sp_sum("TOTAL_SALES").alias("TOTAL_REVENUE"),
        )
        units_vs_revenue.write.mode("overwrite").save_as_table("UNITS_VS_REVENUE")

        # 5.5 Average Order Value (overall + by region)
        overall_aov = curated_df.agg(
            sp_round(sp_sum("TOTAL_SALES") / sp_sum("UNITS_SOLD"), 2).alias("AOV")
        )
        overall_aov.write.mode("overwrite").save_as_table("AOV_OVERALL")

        aov_by_region = curated_df.group_by("REGION").agg(
            sp_round(sp_sum("TOTAL_SALES") / sp_sum("UNITS_SOLD"), 2).alias("AOV")
        )
        aov_by_region.write.mode("overwrite").save_as_table("AOV_BY_REGION")

        logger.info("All 5 curated metric tables written successfully.")
    except SnowparkSQLException as exc:
        raise TransformError(f"Failed computing metrics: {exc}") from exc


def run_full_transform() -> None:
    """Entry point: runs the entire extract-clean-derive-aggregate pipeline in Snowflake."""
    with snowpark_session() as session:
        setup_external_stage(session)
        raw_df = load_raw_table(session)
        curated_df = clean_and_derive(raw_df)
        compute_metrics(session, curated_df)


if __name__ == "__main__":
    try:
        run_full_transform()
        print("OK: Snowpark transformation pipeline completed.")
    except TransformError as exc:
        logger.error(str(exc))
        sys.exit(1)
