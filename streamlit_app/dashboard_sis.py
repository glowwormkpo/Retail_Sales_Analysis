"""
dashboard_sis.py
------------------
Self-contained Streamlit-in-Snowflake version of the dashboard, using Altair
(bundled with Streamlit itself -- no extra packages, no PyPI/External
Access Integration required) instead of Plotly.

Paste this file's contents directly into the Snowsight Streamlit app editor
(streamlit_app.py). No changes to pyproject.toml are needed.
"""

import pandas as pd
import altair as alt
import streamlit as st
from snowflake.snowpark.context import get_active_session

st.set_page_config(page_title="Retail Sales Performance Analysis", layout="wide")

CURATED_TABLE = "RETAIL_SALES_DB.ANALYTICS.SALES_CURATED"


@st.cache_data(show_spinner="Loading sales data...")
def load_data() -> pd.DataFrame:
    session = get_active_session()
    df = session.table(CURATED_TABLE).to_pandas()
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"sale_date": "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df


df = load_data()

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.title("Filters")

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
    chart = alt.Chart(prod_agg).mark_bar().encode(
        x=alt.X("product:N", sort="-y", title="Product"),
        y=alt.Y("total_revenue:Q", title="Total Revenue ($)"),
        color=alt.Color("product:N", legend=None),
        tooltip=["product", "total_revenue"],
    ).properties(title="Total Revenue by Product")
    st.altair_chart(chart, use_container_width=True)
with c2:
    chart = alt.Chart(prod_agg).mark_arc(innerRadius=50).encode(
        theta="total_revenue:Q",
        color=alt.Color("product:N", title="Product"),
        tooltip=["product", "total_revenue"],
    ).properties(title="Revenue Share by Product")
    st.altair_chart(chart, use_container_width=True)

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
    chart = alt.Chart(monthly_agg).mark_line(point=True).encode(
        x=alt.X("month_year:N", title="Month"),
        y=alt.Y("total_revenue:Q", title="Total Revenue ($)"),
        tooltip=["month_year", "total_revenue"],
    ).properties(title="Month-over-Month Revenue")
    st.altair_chart(chart, use_container_width=True)
with c2:
    chart = alt.Chart(monthly_agg).mark_area(opacity=0.6).encode(
        x=alt.X("month_year:N", title="Month"),
        y=alt.Y("total_revenue:Q", title="Total Revenue ($)"),
        tooltip=["month_year", "total_revenue"],
    ).properties(title="Revenue Growth Trend")
    st.altair_chart(chart, use_container_width=True)

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
    chart = alt.Chart(region_agg).mark_bar().encode(
        x=alt.X("total_revenue:Q", title="Total Revenue ($)"),
        y=alt.Y("region:N", sort="-x", title="Region"),
        tooltip=["region", "total_revenue"],
    ).properties(title="Revenue by Region")
    st.altair_chart(chart, use_container_width=True)
with c2:
    chart = alt.Chart(region_product).mark_bar().encode(
        x=alt.X("region:N", title="Region"),
        y=alt.Y("total_revenue:Q", title="Total Revenue ($)"),
        color=alt.Color("product:N", title="Product"),
        tooltip=["region", "product", "total_revenue"],
    ).properties(title="Product Mix within Each Region")
    st.altair_chart(chart, use_container_width=True)

# ---------------------------------------------------------------------------
# 4. Units vs Revenue + 5. AOV
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
chart = alt.Chart(aov_region.sort_values("aov", ascending=False)).mark_bar().encode(
    x=alt.X("region:N", sort="-y", title="Region"),
    y=alt.Y("aov:Q", title="AOV ($)"),
    tooltip=["region", "aov"],
).properties(title="Average Order Value by Region (revenue per transaction)")
st.altair_chart(chart, use_container_width=True)

st.caption("Retail Sales Performance Analysis — built with Streamlit + Snowpark")
