"""
pipeline.py
------------
Orchestrator (Step 4): runs the full extract -> load -> transform ->
metrics -> visualize flow described in the requirements doc.

Two engines share this one entry point:

  --engine local      Runs entirely on pandas against the local CSV.
                       No cloud accounts needed -- this is what actually
                       executes in this session and is meant for dev/demo.

  --engine snowflake   Runs the "real" architecture: uploads the raw file
                       to S3 (aws_s3_loader.py), then runs the Snowpark
                       transformation (snowpark_transform.py) inside
                       Snowflake. Requires AWS + Snowflake credentials to
                       be configured (see .env.example).

Any failure in any step is caught, logged, and turned into a non-zero exit
code -- nothing fails silently.
"""

import argparse
import logging
import sys

from config import pipeline_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pipeline")


def run_local(csv_path: str, charts_dir: str) -> dict:
    from local_engine import load_raw, clean_and_derive, compute_all_metrics, TransformError
    from visualize import generate_all_charts

    try:
        raw = load_raw(csv_path)
        clean = clean_and_derive(raw)
        metrics = compute_all_metrics(clean)
        chart_paths = generate_all_charts(metrics, charts_dir)
        logger.info("Local pipeline complete. %d charts written to %s.",
                    len(chart_paths), charts_dir)
        return {"metrics": metrics, "charts": chart_paths}
    except TransformError as exc:
        logger.error("Local pipeline failed: %s", exc)
        raise


def run_snowflake(csv_path: str) -> None:
    from aws_s3_loader import upload_sales_file, S3UploadError
    from snowpark_transform import run_full_transform, TransformError

    try:
        uri = upload_sales_file(csv_path)
        logger.info("Raw file landed at %s", uri)
    except S3UploadError as exc:
        logger.error("S3 upload step failed: %s", exc)
        raise

    try:
        run_full_transform()
        logger.info("Snowpark transformation completed.")
    except TransformError as exc:
        logger.error("Snowpark transformation failed: %s", exc)
        raise


def main():
    parser = argparse.ArgumentParser(description="Retail Sales Performance Analysis pipeline.")
    parser.add_argument("--engine", choices=["local", "snowflake"],
                         default=pipeline_config.engine,
                         help="Which execution engine to run (default from PIPELINE_ENGINE env var).")
    parser.add_argument("--file", default=pipeline_config.local_data_path,
                         help="Path to the local sales.csv file.")
    parser.add_argument("--charts-dir", default=pipeline_config.charts_output_dir,
                         help="Where to write generated chart PNGs (local engine only).")
    args = parser.parse_args()

    logger.info("Starting pipeline with engine=%s", args.engine)
    try:
        if args.engine == "local":
            result = run_local(args.file, args.charts_dir)
            print(f"OK: local pipeline finished. Charts: {result['charts']}")
        else:
            run_snowflake(args.file)
            print("OK: snowflake pipeline finished. Curated tables written in Snowflake.")
    except Exception as exc:  # noqa: BLE001 - top-level guard so nothing fails silently
        logger.error("Pipeline aborted: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
