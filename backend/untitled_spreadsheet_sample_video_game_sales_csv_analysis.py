#!/usr/bin/env python3
"""Auto-generated analysis for Untitled spreadsheet - sample_video_game_sales.csv.

Reproduces the KPIs and charts from the Analyze Data tool with pandas + matplotlib.
The numbers match the tool exactly because this applies the same aggregations.

Setup:
    pip install pandas matplotlib openpyxl
Run:
    python untitled_spreadsheet_sample_video_game_sales_csv_analysis.py [path-to-data-file]
"""
import sys

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # write PNGs without a display
import matplotlib.pyplot as plt

DATA_FILE = sys.argv[1] if len(sys.argv) > 1 else 'Untitled spreadsheet - sample_video_game_sales.csv'


def load_table(path):
    name = path.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(path)
    if name.endswith(".json"):
        return pd.read_json(path)
    sep = "\t" if name.endswith(".tsv") else ","
    return pd.read_csv(path, sep=sep)


def format_value(value, fmt):
    if value is None or (isinstance(value, float) and value != value):  # None / NaN
        return "—"
    if fmt == "currency":
        return f"${value:,.2f}"
    if fmt == "percent":
        return f"{value:,.1f}%"
    if float(value).is_integer() and abs(value) < 1e15:
        return f"{int(value):,}"
    return f"{value:,.2f}"


def main():
    df = load_table(DATA_FILE)
    df.columns = [str(c).strip() for c in df.columns]

    print("=== KPIs ===")
    print('Total Global Sales:', format_value(pd.to_numeric(df['Global_Sales'], errors='coerce').sum(), 'number'))
    print('Average Global Sales per Game:', format_value(pd.to_numeric(df['Global_Sales'], errors='coerce').mean(), 'number'))
    print('Total NA Sales:', format_value(pd.to_numeric(df['NA_Sales'], errors='coerce').sum(), 'number'))
    print('Total EU Sales:', format_value(pd.to_numeric(df['EU_Sales'], errors='coerce').sum(), 'number'))
    print('Total JP Sales:', format_value(pd.to_numeric(df['JP_Sales'], errors='coerce').sum(), 'number'))
    print('Number of Platforms Represented:', format_value(float(df['Platform'].nunique(dropna=True)), 'number'))

    print("\n=== Charts ===")
    # Chart 1: Global Sales by Platform (bar)
    work = df[['Platform', 'Global_Sales']].copy()
    work = work[work['Platform'].notna()]
    work['Global_Sales'] = pd.to_numeric(work['Global_Sales'], errors='coerce')
    series = work.dropna(subset=['Global_Sales']).groupby('Platform')['Global_Sales'].agg('sum')
    y_label = 'sum of Global_Sales'
    series = series.sort_values(ascending=False)
    series = series.head(10)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(series.index.astype(str), series.values)
    ax.set_xlabel('Platform'); ax.set_ylabel(y_label)
    plt.xticks(rotation=30, ha='right')
    ax.set_title('Global Sales by Platform')
    fig.tight_layout()
    fig.savefig('chart_1_global_sales_by_platform.png', dpi=150)
    plt.close(fig)
    print('Saved chart_1_global_sales_by_platform.png')

    # Chart 2: Global Sales by Genre (bar)
    work = df[['Genre', 'Global_Sales']].copy()
    work = work[work['Genre'].notna()]
    work['Global_Sales'] = pd.to_numeric(work['Global_Sales'], errors='coerce')
    series = work.dropna(subset=['Global_Sales']).groupby('Genre')['Global_Sales'].agg('sum')
    y_label = 'sum of Global_Sales'
    series = series.sort_values(ascending=False)
    series = series.head(10)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(series.index.astype(str), series.values)
    ax.set_xlabel('Genre'); ax.set_ylabel(y_label)
    plt.xticks(rotation=30, ha='right')
    ax.set_title('Global Sales by Genre')
    fig.tight_layout()
    fig.savefig('chart_2_global_sales_by_genre.png', dpi=150)
    plt.close(fig)
    print('Saved chart_2_global_sales_by_genre.png')

    # Chart 3: Global Sales by Publisher (pie)
    work = df[['Publisher', 'Global_Sales']].copy()
    work = work[work['Publisher'].notna()]
    work['Global_Sales'] = pd.to_numeric(work['Global_Sales'], errors='coerce')
    series = work.dropna(subset=['Global_Sales']).groupby('Publisher')['Global_Sales'].agg('sum')
    y_label = 'sum of Global_Sales'
    series = series.sort_values(ascending=False)
    series = series.head(10)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.pie(series.values, labels=series.index.astype(str), autopct='%1.1f%%')
    ax.set_title('Global Sales by Publisher')
    fig.tight_layout()
    fig.savefig('chart_3_global_sales_by_publisher.png', dpi=150)
    plt.close(fig)
    print('Saved chart_3_global_sales_by_publisher.png')

    # Chart 4: Total Global Sales Trend by Release Year (line)
    work = df[['Year', 'Global_Sales']].copy()
    work = work[work['Year'].notna()]
    work['Global_Sales'] = pd.to_numeric(work['Global_Sales'], errors='coerce')
    series = work.dropna(subset=['Global_Sales']).groupby('Year')['Global_Sales'].agg('sum')
    y_label = 'sum of Global_Sales'
    series = series.sort_index()
    series = series.head(10)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(series.index.astype(str), series.values, marker='o')
    ax.set_xlabel('Year'); ax.set_ylabel(y_label)
    plt.xticks(rotation=30, ha='right')
    ax.set_title('Total Global Sales Trend by Release Year')
    fig.tight_layout()
    fig.savefig('chart_4_total_global_sales_trend_by_release_year.png', dpi=150)
    plt.close(fig)
    print('Saved chart_4_total_global_sales_trend_by_release_year.png')


if __name__ == "__main__":
    main()
