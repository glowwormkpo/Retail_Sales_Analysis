"""
visualize.py
-------------
Static chart generation (matplotlib) for the pipeline's batch report output.
The Streamlit dashboard (streamlit_app/dashboard.py) uses Plotly for
interactivity; this module produces PNGs suitable for the README/report
and for environments without a browser.
"""

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logger = logging.getLogger("visualize")

PALETTE = ["#2E5EAA", "#5BA3D0", "#F2A541", "#57A773", "#C44536"]


def _save(fig, out_dir: str, filename: str) -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(out_dir) / filename
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved chart: %s", out_path)
    return str(out_path)


def plot_product_leaderboard(df, out_dir: str) -> str:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(df["product"], df["total_revenue"], color=PALETTE[0])
    ax.set_title("Product Sales Leaderboard — Total Revenue by Product")
    ax.set_xlabel("Product")
    ax.set_ylabel("Total Revenue ($)")
    for i, v in enumerate(df["total_revenue"]):
        ax.text(i, v, f"${v:,.0f}", ha="center", va="bottom", fontsize=9)
    return _save(fig, out_dir, "product_leaderboard.png")


def plot_regional_sales(df, out_dir: str) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].bar(df["region"], df["total_revenue"], color=PALETTE[1])
    axes[0].set_title("Regional Sales — Bar")
    axes[0].set_ylabel("Total Revenue ($)")
    axes[1].pie(df["total_revenue"], labels=df["region"], autopct="%1.1f%%",
                colors=PALETTE, startangle=90)
    axes[1].set_title("Regional Sales — Share of Revenue")
    fig.suptitle("Regional Sales Comparison")
    return _save(fig, out_dir, "regional_sales.png")


def plot_monthly_trend(df, out_dir: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(df["month_year"], df["total_revenue"], marker="o", color=PALETTE[2])
    ax.fill_between(range(len(df)), df["total_revenue"], alpha=0.15, color=PALETTE[2])
    ax.set_title("Monthly Trend — Total Revenue Over Time")
    ax.set_xlabel("Month")
    ax.set_ylabel("Total Revenue ($)")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    return _save(fig, out_dir, "monthly_trend.png")


def plot_units_vs_revenue(df, out_dir: str) -> str:
    fig, ax1 = plt.subplots(figsize=(8, 4.5))
    x = range(len(df))
    width = 0.35
    ax1.bar([i - width / 2 for i in x], df["total_units"], width, label="Total Units Sold", color=PALETTE[3])
    ax1.set_ylabel("Total Units Sold")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(df["product"])

    ax2 = ax1.twinx()
    ax2.bar([i + width / 2 for i in x], df["total_revenue"], width, label="Total Revenue", color=PALETTE[4])
    ax2.set_ylabel("Total Revenue ($)")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
    ax1.set_title("Units Sold vs Revenue by Product")
    return _save(fig, out_dir, "units_vs_revenue.png")


def plot_aov(aov_by_region_df, out_dir: str) -> str:
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(aov_by_region_df["region"], aov_by_region_df["aov"], color=PALETTE[0])
    ax.set_title("Average Order Value by Region")
    ax.set_xlabel("Region")
    ax.set_ylabel("AOV ($)")
    for i, v in enumerate(aov_by_region_df["aov"]):
        ax.text(i, v, f"${v:,.2f}", ha="center", va="bottom", fontsize=9)
    return _save(fig, out_dir, "aov_by_region.png")


def generate_all_charts(metrics: dict, out_dir: str) -> list:
    """Generate every chart required by Step 5/6 and return the list of file paths."""
    paths = [
        plot_product_leaderboard(metrics["product_leaderboard"], out_dir),
        plot_regional_sales(metrics["regional_sales"], out_dir),
        plot_monthly_trend(metrics["monthly_trend"], out_dir),
        plot_units_vs_revenue(metrics["units_vs_revenue"], out_dir),
        plot_aov(metrics["aov"]["by_region"], out_dir),
    ]
    return paths
