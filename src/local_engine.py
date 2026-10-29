"""
local_engine.py
-----------------
A pandas implementation of the exact same clean/derive/aggregate logic in
snowpark_transform.py. Two reasons this exists:

  1. Demo/dev without a Snowflake account: `pipeline.py --engine local` runs
     the whole analysis on a laptop with just pandas installed.
  2. Testability: metric-calculation logic can be unit-tested quickly in
     pandas rather than requiring a live warehouse connection for every
     test run. The Snowpark version should be validated to produce the
     same aggregate numbers before being trusted in production.

Every function here mirrors a function in snowpark_transform.py by name and
purpose, and raises the local equivalent of TransformError so pipeline.py
can handle both engines with one except block.
"""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("local_engine")

REQUIRED_COLUMNS = {"date", "product", "region", "units_sold", "unit_price"}


class TransformError(Exception):
    """Raised when a local transformation step fails."""


def load_raw(csv_path: str) -> pd.DataFrame:
    """Load and lightly validate the raw sales CSV."""
    path = Path(csv_path)
    if not path.exists():
        raise TransformError(f"Source file not found: {csv_path}")
    try:
        df = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        raise TransformError(f"Failed to read CSV: {exc}") from exc

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise TransformError(f"Missing required column(s): {sorted(missing)}")

    logger.info("Loaded %d raw rows from %s", len(df), csv_path)
    return df


def clean_and_derive(df: pd.DataFrame) -> pd.DataFrame:
    """
    Type-cast, drop invalid rows, and add derived columns:
    total_sales, month, year, month_year.
    """
    try:
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out["units_sold"] = pd.to_numeric(out["units_sold"], errors="coerce")
        out["unit_price"] = pd.to_numeric(out["unit_price"], errors="coerce")

        before = len(out)
        out = out.dropna(subset=["date", "product", "region", "units_sold", "unit_price"])
        dropped = before - len(out)
        if dropped:
            logger.warning("Dropped %d row(s) with nulls/invalid types.", dropped)

        # total_sales: use the provided 'sales' column if present & consistent,
        # otherwise compute it (matches Step 5.1: "units sold x unit price").
        computed = (out["units_sold"] * out["unit_price"]).round(2)
        if "sales" in out.columns:
            out["total_sales"] = pd.to_numeric(out["sales"], errors="coerce").fillna(computed)
        else:
            out["total_sales"] = computed

        out["month"] = out["date"].dt.month
        out["year"] = out["date"].dt.year
        out["month_year"] = out["date"].dt.to_period("M").astype(str)

        logger.info("Clean/derive complete: %d rows retained.", len(out))
        return out
    except TransformError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TransformError(f"Failed during clean/derive step: {exc}") from exc


# ---------------------------------------------------------------------------
# Step 5: Metrics
# ---------------------------------------------------------------------------

def product_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    """5.1 Product Sales Leaderboard: total revenue per product, descending."""
    result = (
        df.groupby("product", as_index=False)["total_sales"]
        .sum()
        .rename(columns={"total_sales": "total_revenue"})
        .sort_values("total_revenue", ascending=False)
        .reset_index(drop=True)
    )
    return result


def regional_sales(df: pd.DataFrame) -> pd.DataFrame:
    """5.2 Regional Sales Comparison: total revenue per region, descending."""
    result = (
        df.groupby("region", as_index=False)["total_sales"]
        .sum()
        .rename(columns={"total_sales": "total_revenue"})
        .sort_values("total_revenue", ascending=False)
        .reset_index(drop=True)
    )
    return result


def monthly_trend(df: pd.DataFrame) -> pd.DataFrame:
    """5.3 Monthly Trend Analysis: total revenue per calendar month."""
    result = (
        df.groupby(["year", "month", "month_year"], as_index=False)["total_sales"]
        .sum()
        .rename(columns={"total_sales": "total_revenue"})
        .sort_values(["year", "month"])
        .reset_index(drop=True)
    )
    return result


def units_vs_revenue(df: pd.DataFrame) -> pd.DataFrame:
    """5.4 Units Sold vs Revenue: side-by-side comparison per product."""
    result = (
        df.groupby("product", as_index=False)
        .agg(total_units=("units_sold", "sum"), total_revenue=("total_sales", "sum"))
        .sort_values("total_revenue", ascending=False)
        .reset_index(drop=True)
    )
    result["revenue_per_unit"] = (result["total_revenue"] / result["total_units"]).round(2)
    return result


def average_order_value(df: pd.DataFrame) -> dict:
    """
    5.5 Average Order Value: total revenue / total units sold.
    Returns overall AOV plus breakdowns by region and product.
    """
    overall = round(df["total_sales"].sum() / df["units_sold"].sum(), 2)

    def _aov_by(group_col: str) -> pd.DataFrame:
        grouped = df.groupby(group_col).agg(
            total_revenue=("total_sales", "sum"), total_units=("units_sold", "sum")
        )
        grouped["aov"] = (grouped["total_revenue"] / grouped["total_units"]).round(2)
        return (
            grouped[["aov"]]
            .reset_index()
            .sort_values("aov", ascending=False)
            .reset_index(drop=True)
        )

    by_region = _aov_by("region")
    by_product = _aov_by("product")

    return {"overall": overall, "by_region": by_region, "by_product": by_product}


def compute_all_metrics(df: pd.DataFrame) -> dict:
    """Convenience wrapper: computes all 5 metrics at once."""
    return {
        "product_leaderboard": product_leaderboard(df),
        "regional_sales": regional_sales(df),
        "monthly_trend": monthly_trend(df),
        "units_vs_revenue": units_vs_revenue(df),
        "aov": average_order_value(df),
    }
