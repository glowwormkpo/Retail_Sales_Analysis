"""
config.py
---------
Centralized configuration for the Retail Sales Performance Analysis pipeline.

All secrets/connection details are pulled from environment variables (never
hard-coded) so the same codebase can move from a laptop to CI/CD to
production without code changes. Copy `.env.example` to `.env` and fill in
real values, or export the variables in your shell / orchestrator.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv()

# Load variables from a .env file (in the current working directory, or any
# parent directory) into the process environment. Safe to call even if no
# .env file exists -- real environment variables (e.g. set by CI/CD) always
# take precedence and are never overwritten.
load_dotenv()


@dataclass(frozen=True)
class AWSConfig:
    """Connection settings for the S3 storage layer."""
    region_name: str = os.getenv("AWS_REGION", "us-east-1")
    bucket_name: str = os.getenv("AWS_S3_BUCKET", "retail-sales-raw-data")
    raw_prefix: str = os.getenv("AWS_S3_RAW_PREFIX", "raw/sales/")
    access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")

    @property
    def has_credentials(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key)


@dataclass(frozen=True)
class SnowflakeConfig:
    """Connection settings for the Snowpark / Snowflake transformation layer."""
    account: str = os.getenv("SNOWFLAKE_ACCOUNT", "")
    user: str = os.getenv("SNOWFLAKE_USER", "")
    password: str = os.getenv("SNOWFLAKE_PASSWORD", "")
    role: str = os.getenv("SNOWFLAKE_ROLE", "SYSADMIN")
    warehouse: str = os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH")
    database: str = os.getenv("SNOWFLAKE_DATABASE", "RETAIL_SALES_DB")
    schema: str = os.getenv("SNOWFLAKE_SCHEMA", "ANALYTICS")
    raw_table: str = os.getenv("SNOWFLAKE_RAW_TABLE", "SALES_RAW")
    curated_table: str = os.getenv("SNOWFLAKE_CURATED_TABLE", "SALES_CURATED")
    stage_name: str = os.getenv("SNOWFLAKE_STAGE", "SALES_S3_STAGE")

    @property
    def has_credentials(self) -> bool:
        return bool(self.account and self.user and self.password)

    def connection_params(self) -> dict:
        return {
            "account": self.account,
            "user": self.user,
            "password": self.password,
            "role": self.role,
            "warehouse": self.warehouse,
            "database": self.database,
            "schema": self.schema,
        }


@dataclass(frozen=True)
class PipelineConfig:
    """General pipeline settings."""
    local_data_path: str = os.getenv("LOCAL_SALES_CSV", "data/sales.csv")
    charts_output_dir: str = os.getenv("CHARTS_OUTPUT_DIR", "outputs/charts")
    engine: str = os.getenv("PIPELINE_ENGINE", "local")  # "local" or "snowflake"


aws_config = AWSConfig()
snowflake_config = SnowflakeConfig()
pipeline_config = PipelineConfig()
