# Retail Sales Performance Analysis

Analyzes historical retail transaction data to surface product, regional, and
time-based sales insights, following a landing-zone → warehouse-transform →
dashboard data engineering architecture.

## 1. Data

`data/sales.csv` — 100 transactions, Jan 1 – Apr 10, 2023.

| Column | Type | Notes |
|---|---|---|
| date | Date (YYYY-MM-DD) | |
| product | String | Product A / B / C |
| region | String | North / South / East / West |
| units_sold | Integer | |
| unit_price | Float | |
| sales | Float | Pre-computed total; pipeline re-derives it as `units_sold × unit_price` and reconciles the two |

**Data quality check (Step 2):** no null values, no duplicate rows, no
negative or zero units/prices, and the `sales` column matches
`units_sold × unit_price` for all 100 rows. `transaction_id`, `category`,
and `sales_rep` were excluded per the requirements doc (marked "not
required as of now"). No cleanup was required beyond type-casting the date
column, which the pipeline still does defensively in case future data
drops don't come pre-cleaned.

## 2. Architecture

```
sales.csv --> [S3: raw landing zone] --> [Snowflake / Snowpark: transform + aggregate] --> [Streamlit: dashboard]
```

| Layer | Tech | Why |
|---|---|---|
| Storage | **Amazon S3** | Cheap, durable, versioned landing zone for raw files. Decouples the source system from the warehouse — if the schema or source changes, raw history is still safe in S3. Snowflake reads it directly through an external stage, so there's no separate ETL hop. |
| Transformation | **Snowflake + Snowpark (Python)** | The requirement was "transformations must be in Snowflake" and "entire logic in Python." Snowpark gives a pandas-like DataFrame API that compiles to SQL and executes inside the Snowflake warehouse (pushdown), so we get Python ergonomics without pulling data out of the warehouse or hand-writing SQL strings. It also scales past what a laptop/pandas job could handle. |
| Orchestration | **Python (`pipeline.py`)** | A single, testable entry point that sequences extract → load → transform → metrics, with structured logging and exceptions at every step instead of a notebook that fails silently. |
| Dashboard | **Streamlit (in Snowflake)** | Explicitly required instead of a BI tool. Streamlit-in-Snowflake queries curated tables in place (`get_active_session()`), so the dashboard has zero data egress and no separate hosting/auth to manage. |
| Local dev/demo engine | **pandas + matplotlib/Plotly** | Snowflake/AWS accounts aren't available in every environment (CI, a fresh laptop). `local_engine.py` mirrors the exact same clean/derive/aggregate logic in pandas so the pipeline and dashboard are fully runnable and demoable without cloud credentials, and so the transformation logic can be unit-tested quickly before trusting it in Snowpark. |

## 3. Project layout

```
retail_sales_analysis/
├── data/sales.csv                 # source data
├── src/
│   ├── config.py                  # env-var driven settings (AWS, Snowflake, pipeline)
│   ├── aws_s3_loader.py           # Step 3: lands sales.csv in S3
│   ├── snowpark_transform.py      # Step 3-4: Snowflake/Snowpark clean+derive+aggregate
│   ├── local_engine.py            # pandas mirror of the Snowpark logic (dev/demo/tests)
│   ├── visualize.py                # static chart generation (matplotlib)
│   └── pipeline.py                # orchestrator CLI, --engine local|snowflake
├── streamlit_app/
│   └── dashboard.py                # Step 6: Streamlit dashboard (dual-mode: SiS or local)
├── outputs/charts/                 # generated PNGs (product, region, monthly, units-vs-rev, AOV)
├── .env.example                    # copy to .env and fill in real AWS/Snowflake credentials
└── requirements.txt
```

## 4. Running it

**Local (no cloud account needed):**
```bash
pip install -r requirements.txt
python src/pipeline.py --engine local
streamlit run streamlit_app/dashboard.py
```

**Full architecture (requires AWS + Snowflake credentials):**
```bash
cp .env.example .env   # fill in AWS_* and SNOWFLAKE_* values
python src/pipeline.py --engine snowflake
# deploy streamlit_app/dashboard.py as a Streamlit-in-Snowflake app
```

Every script fails loudly with a specific exception (`S3UploadError`,
`TransformError`) rather than swallowing errors, so a missing credential or
a malformed row stops the run with a clear message instead of producing
silently wrong numbers.

## 5. Metrics & findings (Step 5, computed from the actual 100-row dataset)

**5.1 Product Sales Leaderboard**
| Product | Total Revenue |
|---|---|
| Product C | $23,367.04 |
| Product B | $17,388.79 |
| Product A | $11,969.24 |

Product C leads by a wide margin (~95% ahead of Product A) despite only
selling 425 vs. 252 units — see 5.4.

**5.2 Regional Sales Comparison**
| Region | Total Revenue |
|---|---|
| North | $15,441.13 |
| West | $13,799.41 |
| South | $13,725.89 |
| East | $9,758.64 |

North is the strongest market; East trails the other three regions by
~30-37%, making it a candidate for targeted promotion or investigation.

**5.3 Monthly Trend**
| Month | Total Revenue |
|---|---|
| 2023-01 | $19,700.01 |
| 2023-02 | $13,360.66 |
| 2023-03 | $13,594.36 |
| 2023-04 | $6,070.04 (partial — data ends Apr 10) |

January is the strongest month in the dataset; February/March are roughly
flat. April looks low only because the data cuts off 10 days in, not
because of an actual decline.

**5.4 Units Sold vs Revenue**
| Product | Total Units | Total Revenue | Revenue/Unit |
|---|---|---|---|
| Product C | 425 | $23,367.04 | $54.98 |
| Product B | 333 | $17,388.79 | $52.22 |
| Product A | 252 | $11,969.24 | $47.50 |

Volume and revenue rank in the same order here (Product C wins both), but
Product C's revenue-per-unit is also the highest — its lead isn't just
volume, it commands a better price too.

**5.5 Average Order Value**

Two distinct measures are reported. The requirements doc defines "AOV" as
total revenue ÷ total units sold, but that is average revenue *per unit*,
not per order, so it is labeled as such here and true AOV (revenue ÷
transactions) is reported alongside it.

- **AOV (revenue per transaction): $527.25** ($52,725 ÷ 100 transactions)
- **Average revenue per unit: $52.20** ($52,725 ÷ 1,010 units, the doc's formula)

| Region | AOV (per transaction) | Avg revenue per unit |
|---|---|---|
| North | $643.38 | $63.03 |
| South | $571.91 | $52.79 |
| West | $492.84 | $51.11 |
| East | $406.61 | $41.53 |

North leads on both measures: its orders are worth ~58% more than East's
($643 vs. $407) and each unit sells for ~52% more ($63 vs. $42), which is
worth digging into (pricing, product mix, or promotions may differ by
region). Regional rankings are the same under either measure.

## 6. Deliverables checklist (Step 7)

- [x] Code files (Python scripts) — `src/`, `streamlit_app/`
- [x] Setup configuration — `.env.example`, `requirements.txt`
- [x] Final dashboard — `streamlit_app/dashboard.py`
- [x] Presentation explaining the work and the "why" behind each tech
      choice — `presentation/Retail_Sales_Performance_Analysis.pptx`

## Project history

The commits are the project's six saved versions (July 15 to October 21, 2026), committed in order in October 2026. Versions 1–4 were reconstructed from the final files by reversing the recorded edits; their file sizes match the originals as delivered, but no original copy survived for a byte-for-byte check. Versions 5 and 6 are exact copies. The original July versions of the presentation deck and the pre-fix AOV chart were overwritten and are not included.
