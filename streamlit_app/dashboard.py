"""
dashboard.py
-------------
Step 6: the Streamlit dashboard. Per the requirement ("No BI tools should
be used for visualization... use Streamlit in Snowflake"), this app is
written to run either:

  1. As a native "Streamlit in Snowflake" (SiS) app, reading curated tables
     directly via `get_active_session()` -- no data leaves Snowflake, no
     external BI tool involved.
  2. As a regular local `streamlit run dashboard.py`, reading the same
     curated logic via local_engine.py against data/sales.csv -- useful for
     development and for this session, since no Snowflake account is
     connected here.

The mode is auto-detected: if a Snowflake session is available (SiS
runtime), it's used; otherwise it falls back to the local pandas engine.

Run locally with:
    streamlit run streamlit_app/dashboard.py
"""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

st.set_page_config(page_title="Retail Sales Performance Analysis", layout="wide")


# ---------------------------------------------------------------------------
# Data access layer: Snowflake (SiS) if available, else local pandas fallback
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Loading sales data...")
def load_data() -> pd.DataFrame:
    try:
        # Only succeeds when actually running inside Streamlit in Snowflake.
        from snowflake.snowpark.context import get_active_session
        session = get_active_session()
        from config import snowflake_config
        sdf = session.table(snowflake_config.curated_table)
        df = sdf.to_pandas()
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"sale_date": "date", "total_sales": "total_sales"})
        st.session_state["_engine"] = "Snowflake (Streamlit in Snowflake)"
        return df
    except Exception:
        # Local fallback: pandas engine against data/sales.csv
        from local_engine import load_raw, clean_and_derive
        csv_path = Path(__file__).resolve().parent.parent / "data" / "sales.csv"
        df = clean_and_derive(load_raw(str(csv_path)))
        st.session_state["_engine"] = "Local (pandas fallback)"
        return df


df = load_data()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.title("Filters")
st.sidebar.caption(f"Engine: {st.session_state.get('_engine', 'unknown')}")

regions = sorted(df["region"].unique())
products = sorted(df["product"].unique())

selected_regions = st.sidebar.multiselect("Region", regions, default=regions)
selected_products = st.sidebar.multiselect("Product", products, default=products)

min_date, max_date = df["date"].min(), df["date"].max()
date_range = st.sidebar.date_input("Date range", value=(min_date, max_date),
                                    min_value=min_date, max_value=max_date)

filtered = df[df["region"].isin(selected_regions) & df["product"].isin(selected_products)]
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = pd.Timestamp(date_range[0]), pd.Timestamp(date_range[1])
    filtered = filtered[(filtered["date"] >= start) & (filtered["date"] <= end)]

if filtered.empty:
    st.warning("No data matches the selected filters.")
    st.stop()

# ---------------------------------------------------------------------------
# Header + KPIs
# ---------------------------------------------------------------------------

st.title("Retail Sales Performance Analysis")
st.caption("Product performance, regional trends, and buying patterns")

total_revenue = filtered["total_sales"].sum()
total_units = filtered["units_sold"].sum()
n_transactions = len(filtered)
aov = total_revenue / n_transactions if n_transactions else 0
rev_per_unit = total_revenue / total_units if total_units else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Revenue", f"${total_revenue:,.0f}")
k2.metric("Total Units Sold", f"{total_units:,}")
k3.metric("Average Order Value", f"${aov:,.2f}")
k4.metric("Avg Revenue per Unit", f"${rev_per_unit:,.2f}")
k5.metric("Transactions", f"{n_transactions:,}")

st.divider()

# ---------------------------------------------------------------------------
# 1. Product Sales Performance
# ---------------------------------------------------------------------------

st.header("1. Product Sales Performance")
st.caption("Question: Which products bring the most revenue?")

prod_agg = (
    filtered.groupby("product", as_index=False)["total_sales"].sum()
    .rename(columns={"total_sales": "total_revenue"})
    .sort_values("total_revenue", ascending=False)
)

c1, c2 = st.columns(2)
with c1:
    fig = px.bar(prod_agg, x="product", y="total_revenue", color="product",
                 title="Total Revenue by Product", text_auto=".2s")
    st.plotly_chart(fig, use_container_width=True)
with c2:
    fig = px.pie(prod_agg, names="product", values="total_revenue",
                 title="Revenue Share by Product", hole=0.35)
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# 2. Monthly Trends
# ---------------------------------------------------------------------------

st.header("2. Monthly Trends")
st.caption("Question: Are there seasonal sales patterns?")

monthly = filtered.copy()
monthly["month_year"] = monthly["date"].dt.to_period("M").astype(str)
monthly_agg = monthly.groupby("month_year", as_index=False)["total_sales"].sum() \
    .rename(columns={"total_sales": "total_revenue"}).sort_values("month_year")

c1, c2 = st.columns(2)
with c1:
    fig = px.line(monthly_agg, x="month_year", y="total_revenue", markers=True,
                   title="Month-over-Month Revenue")
    st.plotly_chart(fig, use_container_width=True)
with c2:
    fig = px.area(monthly_agg, x="month_year", y="total_revenue",
                   title="Revenue Growth Trend")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# 3. Regional Insights
# ---------------------------------------------------------------------------

st.header("3. Regional Insights")
st.caption("Question: Which regions perform the best?")

region_agg = filtered.groupby("region", as_index=False)["total_sales"].sum() \
    .rename(columns={"total_sales": "total_revenue"}).sort_values("total_revenue")

region_product = filtered.groupby(["region", "product"], as_index=False)["total_sales"].sum() \
    .rename(columns={"total_sales": "total_revenue"})

c1, c2 = st.columns(2)
with c1:
    fig = px.bar(region_agg, x="total_revenue", y="region", orientation="h",
                 title="Revenue by Region", text_auto=".2s")
    st.plotly_chart(fig, use_container_width=True)
with c2:
    fig = px.bar(region_product, x="region", y="total_revenue", color="product",
                 title="Product Mix within Each Region", barmode="stack")
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Extra: Units vs Revenue + AOV (Step 5.4 / 5.5)
# ---------------------------------------------------------------------------

st.header("4. Units Sold vs Revenue")
st.caption("Question: Does high volume always mean high revenue?")

uvr = filtered.groupby("product", as_index=False).agg(
    total_units=("units_sold", "sum"), total_revenue=("total_sales", "sum")
)
uvr["revenue_per_unit"] = (uvr["total_revenue"] / uvr["total_units"]).round(2)
st.dataframe(uvr, use_container_width=True, hide_index=True)

st.header("5. Average Order Value (AOV)")
aov_region = filtered.groupby("region", as_index=False).agg(
    total_revenue=("total_sales", "sum"), transactions=("total_sales", "size")
)
aov_region["aov"] = (aov_region["total_revenue"] / aov_region["transactions"]).round(2)
fig = px.bar(aov_region.sort_values("aov", ascending=False), x="region", y="aov",
             title="Average Order Value by Region (revenue per transaction)", text_auto=".2f")
st.plotly_chart(fig, use_container_width=True)

st.caption("Retail Sales Performance Analysis — built with Streamlit + Snowpark")
