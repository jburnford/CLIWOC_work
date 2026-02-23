"""
Phase 6: Validation & Output
CLIWOC Data Cleaning Pipeline for "Sailors and Circulation"

Tasks:
  1. Reproduce Dagomar's annual wind velocity trends (validation)
  2. Quality flag statistics
  3. Generate quality_report.md
  4. Export cliwoc_cleaned.parquet
  5. Generate cliwoc_wind_timeseries.parquet (aggregated)
  6. Store wind_translations audit table in DB

All SQL-based to avoid loading full 287K × 206 columns into memory.
Parquet export uses chunked reads.
"""

import csv
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

BASE_DIR = Path("/home/jic823/climate")
OUT_DIR = BASE_DIR / "cleaned"
DB_PATH = OUT_DIR / "cliwoc_cleaned.db"

DAGOMAR_CSV = BASE_DIR / "DagomarDatasets" / "Datasets" / "CLIWOC Average Annual Wind Velocity and Number of Observations.csv"
WIND_JSON = OUT_DIR / "wind_term_translations.json"

PARQUET_FULL = OUT_DIR / "cliwoc_cleaned.parquet"
PARQUET_TIMESERIES = OUT_DIR / "cliwoc_wind_timeseries.parquet"
QUALITY_REPORT = OUT_DIR / "quality_report.md"


def validate_against_dagomar(conn):
    """Compare our annual wind means to Dagomar's published values."""
    print("\n── 1. Validation: Reproduce Dagomar's trends ──")

    # Load Dagomar's data
    dagomar = pd.read_csv(DAGOMAR_CSV)
    dagomar.columns = ["year", "dagomar_w", "dagomar_n"]

    # Compute our annual means using original W column only (matching Dagomar's method)
    our_data = pd.read_sql("""
        SELECT CAST(Year AS INTEGER) as year,
               AVG(W) as our_w,
               COUNT(*) as our_n
        FROM observations
        WHERE W IS NOT NULL
          AND Year >= 1750 AND Year <= 1855
        GROUP BY CAST(Year AS INTEGER)
        ORDER BY year
    """, conn)

    # Also compute using W_corrected (our cleaned version)
    our_corrected = pd.read_sql("""
        SELECT CAST(Year AS INTEGER) as year,
               AVG(W_corrected) as our_w_corrected,
               COUNT(*) as our_n_corrected
        FROM observations
        WHERE W_corrected IS NOT NULL
          AND Year >= 1750 AND Year <= 1855
        GROUP BY CAST(Year AS INTEGER)
        ORDER BY year
    """, conn)

    # Merge
    merged = dagomar.merge(our_data, on="year", how="outer").merge(
        our_corrected, on="year", how="outer")

    # Compare
    common = merged.dropna(subset=["dagomar_w", "our_w"])
    diff = (common["our_w"] - common["dagomar_w"]).abs()
    pct_diff = diff / common["dagomar_w"] * 100

    print(f"  Years compared: {len(common)} (1750-1855)")
    print(f"  Mean absolute difference (W): {diff.mean():.4f} tenths m/s")
    print(f"  Max absolute difference: {diff.max():.4f} tenths m/s")
    print(f"  Mean % difference: {pct_diff.mean():.3f}%")
    print(f"  Max % difference: {pct_diff.max():.3f}%")

    # Check obs counts match
    n_diff = (common["our_n"] - common["dagomar_n"]).abs()
    print(f"  Obs count differences: mean={n_diff.mean():.1f}, max={n_diff.max()}")

    if pct_diff.mean() < 1.0:
        print("  PASS: Annual wind means match within 1%")
    elif pct_diff.mean() < 5.0:
        print("  MARGINAL: Differences between 1-5% — investigate")
    else:
        print("  FAIL: Differences >5% — significant discrepancy")

    # Show worst years
    worst = common.nlargest(5, "dagomar_w").copy()
    worst["diff"] = worst["our_w"] - worst["dagomar_w"]
    print("\n  Years with largest absolute values (Dagomar):")
    for _, row in worst.iterrows():
        print(f"    {int(row['year'])}: Dagomar={row['dagomar_w']:.2f}, Ours={row['our_w']:.2f}, "
              f"Diff={row['diff']:.2f}")

    # Also compare corrected vs original
    common2 = merged.dropna(subset=["our_w", "our_w_corrected"])
    if len(common2) > 0:
        corr_diff = (common2["our_w_corrected"] - common2["our_w"]).abs()
        print(f"\n  W vs W_corrected comparison ({len(common2)} years):")
        print(f"    Mean difference: {corr_diff.mean():.4f} tenths m/s")
        print(f"    Additional obs from LLM translation: "
              f"{(common2['our_n_corrected'] - common2['our_n']).mean():.0f}/year avg")

    return merged


def quality_flag_statistics(conn):
    """Summarize all QC flags."""
    print("\n── 2. Quality flag statistics ──")
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    flags = [
        ("qc_calendar_converted", "Julian→Gregorian calendar conversion"),
        ("qc_duplicate", "Potential duplicate records"),
        ("qc_temp_outlier", "Temperature outliers"),
        ("qc_pressure_outlier", "Pressure outliers"),
        ("qc_wind_calm", "Calm wind (no direction)"),
        ("qc_wind_variable", "Variable wind direction"),
        ("qc_direction_imputed", "Wind direction imputed from text"),
        ("qc_wind_llm_translated", "Wind force LLM-translated"),
    ]

    results = []
    for col, desc in flags:
        r = cur.execute(f"SELECT COUNT(*) FROM observations WHERE {col} = 1").fetchone()
        n = r[0]
        pct = n / total * 100
        print(f"  {col:30s}: {n:6,} ({pct:5.2f}%)  — {desc}")
        results.append((col, desc, n, pct))

    # Confidence distribution for LLM translations
    print("\n  LLM translation confidence:")
    rows = cur.execute("""
        SELECT qc_wind_confidence, COUNT(*) FROM observations
        WHERE qc_wind_llm_translated = 1
        GROUP BY qc_wind_confidence ORDER BY COUNT(*) DESC
    """).fetchall()
    for conf, cnt in rows:
        print(f"    {conf or 'NULL':10s}: {cnt:,}")

    return results


def data_coverage_summary(conn):
    """Summarize data availability by variable."""
    print("\n── 3. Data coverage summary ──")
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    variables = [
        ("W", "Wind speed (original)"),
        ("W_corrected", "Wind speed (with LLM fills)"),
        ("W_midpoint", "Wind speed (Beaufort midpoint)"),
        ("D", "Wind direction (original)"),
        ("D_cleaned", "Wind direction (cleaned)"),
        ("AT", "Air temperature"),
        ("SLP", "Sea level pressure"),
        ("weather_category", "Weather classification"),
        ("sea_state", "Sea state (Douglas)"),
        ("grid_5x5", "Spatial grid cell"),
        ("beaufort_corrected", "Beaufort (corrected)"),
    ]

    results = []
    for col, desc in variables:
        r = cur.execute(f"SELECT COUNT(*) FROM observations WHERE {col} IS NOT NULL").fetchone()
        n = r[0]
        pct = n / total * 100
        print(f"  {desc:35s}: {n:7,} / {total:,} ({pct:5.1f}%)")
        results.append((col, desc, n, pct))

    return results


def nationality_breakdown(conn):
    """Records by nationality."""
    print("\n── 4. Nationality breakdown ──")
    rows = pd.read_sql("""
        SELECT Nationality as nationality, COUNT(*) as n,
               SUM(CASE WHEN W IS NOT NULL THEN 1 ELSE 0 END) as has_W,
               SUM(CASE WHEN W_corrected IS NOT NULL THEN 1 ELSE 0 END) as has_W_corrected,
               AVG(CASE WHEN W IS NOT NULL THEN W END) as avg_W,
               MIN(Year) as min_year, MAX(Year) as max_year
        FROM observations
        GROUP BY Nationality
        ORDER BY n DESC
    """, conn)
    print(rows.to_string(index=False))
    return rows


def generate_wind_timeseries(conn):
    """Create aggregated wind timeseries parquet."""
    print("\n── 5. Generating wind timeseries parquet ──")

    # Monthly by grid cell
    ts = pd.read_sql("""
        SELECT
            CAST(Year AS INTEGER) as year,
            CAST(Month AS INTEGER) as month,
            grid_5x5,
            ocean_basin,
            hemisphere,
            season,
            COUNT(*) as n_obs,
            AVG(W_corrected / 10.0) as mean_wind_speed,
            AVG(W_midpoint) as mean_wind_midpoint,
            AVG(u_wind) as mean_u_wind,
            AVG(v_wind) as mean_v_wind,
            AVG(D_cleaned) as mean_direction,
            AVG(beaufort_corrected) as mean_beaufort,
            AVG(AT_celsius) as mean_temp,
            AVG(SLP_hPa) as mean_pressure,
            AVG(sea_state) as mean_sea_state
        FROM observations
        WHERE Year >= 1750 AND Year <= 1855
          AND W_corrected IS NOT NULL
          AND grid_5x5 IS NOT NULL
        GROUP BY CAST(Year AS INTEGER), CAST(Month AS INTEGER), grid_5x5,
                 ocean_basin, hemisphere, season
        ORDER BY year, month, grid_5x5
    """, conn)

    ts.to_parquet(PARQUET_TIMESERIES, index=False)
    print(f"  Written: {PARQUET_TIMESERIES}")
    print(f"  Rows: {len(ts):,} (monthly × grid cell aggregates)")
    print(f"  Years: {ts['year'].min()}-{ts['year'].max()}")
    print(f"  Grid cells: {ts['grid_5x5'].nunique()}")

    return ts


def export_full_parquet(conn):
    """Export full cleaned dataset as parquet, reading in chunks."""
    print("\n── 6. Exporting full parquet ──")

    # Get column names (only the ones we care about for analysis)
    # Skip the 100+ raw ICOADS/archival columns, keep the useful ones
    keep_cols = [
        # Identity
        "Year", "Month", "Day", "TimeOB", "ShipName", "Nationality",
        "ShipType", "VoyageFrom", "VoyageTo",
        # Position
        "latitude", "longitude",
        # Wind (original)
        "D", "W", "AllWindForces", "AllWindDirections", "WindScale",
        # Atmosphere (original)
        "AT", "SLP", "Weather", "StateSea",
        # Phase 1: Foundation
        "date_iso", "decimal_year", "AT_celsius", "SLP_hPa",
        "qc_calendar_converted", "qc_duplicate", "qc_temp_outlier", "qc_pressure_outlier",
        # Phase 2: Wind direction
        "D_cleaned", "beaufort", "u_wind", "v_wind",
        "qc_wind_calm", "qc_wind_variable", "qc_direction_imputed",
        # Phase 3: Wind force translation
        "W_corrected", "beaufort_corrected", "qc_wind_llm_translated", "qc_wind_confidence",
        # Phase 4: Weather & sea state
        "weather_category", "sea_state",
        # Phase 5: Derived
        "grid_5x5", "hemisphere", "ocean_basin", "season", "W_midpoint",
    ]

    # Check which columns actually exist
    cur = conn.cursor()
    all_cols = [r[1] for r in cur.execute("PRAGMA table_info(observations)").fetchall()]
    valid_cols = [c for c in keep_cols if c in all_cols]

    cols_str = ", ".join(f'"{c}"' for c in valid_cols)

    # Read in chunks to avoid memory issues
    chunk_size = 50000
    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    writer = None
    for offset in range(0, total, chunk_size):
        chunk = pd.read_sql(
            f"SELECT {cols_str} FROM observations LIMIT {chunk_size} OFFSET {offset}",
            conn
        )
        # Convert types
        for col in ["latitude", "longitude"]:
            if col in chunk.columns:
                chunk[col] = pd.to_numeric(chunk[col], errors="coerce")
        for col in ["Year", "Month", "Day"]:
            if col in chunk.columns:
                chunk[col] = pd.to_numeric(chunk[col], errors="coerce").astype("Int64")

        table = pa.Table.from_pandas(chunk)
        if writer is None:
            writer = pq.ParquetWriter(PARQUET_FULL, table.schema)
        writer.write_table(table)

    if writer:
        writer.close()

    print(f"  Written: {PARQUET_FULL}")
    print(f"  Columns: {len(valid_cols)}")
    print(f"  Rows: {total:,}")
    size_mb = PARQUET_FULL.stat().st_size / 1024 / 1024
    print(f"  File size: {size_mb:.1f} MB")


def store_wind_translations_table(conn):
    """Store wind term translations as a DB table for easy querying."""
    print("\n── 7. Storing wind_translations table ──")

    with open(WIND_JSON) as f:
        translations = json.load(f)

    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS wind_translations")
    cur.execute("""
        CREATE TABLE wind_translations (
            term TEXT PRIMARY KEY,
            beaufort REAL,
            confidence TEXT,
            method TEXT,
            reasoning TEXT
        )
    """)

    rows = []
    for term, info in translations.items():
        rows.append((
            term,
            info.get("beaufort"),
            info.get("confidence"),
            info.get("method"),
            info.get("reasoning", ""),
        ))

    cur.executemany("INSERT INTO wind_translations VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    print(f"  Stored {len(rows):,} wind term translations")


def generate_quality_report(conn, validation_df, flag_results, coverage_results):
    """Generate quality_report.md."""
    print("\n── 8. Generating quality report ──")
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    lines = []
    lines.append("# CLIWOC Data Quality Report")
    lines.append("")
    lines.append("## Dataset Overview")
    lines.append(f"- **Total records**: {total:,}")
    lines.append(f"- **Source**: CLIWOC 2.1 (Climatological Database for the World's Oceans)")
    lines.append(f"- **Time range**: 1662-1855 (primary focus: 1750-1855)")
    lines.append(f"- **Nationalities**: Dutch (44%), British (33%), Spanish (19%), French (4%)")
    lines.append("")

    lines.append("## Cleaning Pipeline")
    lines.append("| Phase | Description | Script |")
    lines.append("|-------|-------------|--------|")
    lines.append("| 1 | Foundation (load, calendar, outliers) | `01_foundation.py` |")
    lines.append("| 2 | Wind direction cleaning | `02_wind_direction.py` |")
    lines.append("| 3 | Wind force LLM translation | `03_wind_force_llm.py` |")
    lines.append("| 4 | Weather & sea state classification | `04_weather_seastate.py`, `04b`, `04c` |")
    lines.append("| 5 | Derived variables & spatial binning | `05_derived.py` |")
    lines.append("| 6 | Validation & output | `06_validate_export.py` |")
    lines.append("")

    lines.append("## Data Coverage")
    lines.append("| Variable | Non-null | % |")
    lines.append("|----------|---------|---|")
    for col, desc, n, pct in coverage_results:
        lines.append(f"| {desc} | {n:,} | {pct:.1f}% |")
    lines.append("")

    lines.append("## Quality Flags")
    lines.append("| Flag | Count | % | Description |")
    lines.append("|------|-------|---|-------------|")
    for col, desc, n, pct in flag_results:
        lines.append(f"| `{col}` | {n:,} | {pct:.2f}% | {desc} |")
    lines.append("")

    lines.append("## Validation Against Dagomar's Published Trends")
    lines.append("")
    if validation_df is not None:
        common = validation_df.dropna(subset=["dagomar_w", "our_w"])
        diff = (common["our_w"] - common["dagomar_w"]).abs()
        pct_diff = diff / common["dagomar_w"] * 100
        lines.append(f"- Compared annual mean wind velocity for {len(common)} years (1750-1855)")
        lines.append(f"- Mean absolute difference: {diff.mean():.4f} tenths m/s")
        lines.append(f"- Mean percentage difference: {pct_diff.mean():.3f}%")
        lines.append(f"- **Result**: {'PASS' if pct_diff.mean() < 1.0 else 'REVIEW'}")
    lines.append("")

    lines.append("## Spatial Coverage")
    rows = cur.execute("""
        SELECT ocean_basin, COUNT(*) as n FROM observations
        WHERE ocean_basin IS NOT NULL
        GROUP BY ocean_basin ORDER BY n DESC
    """).fetchall()
    lines.append("| Ocean Basin | Records | % |")
    lines.append("|-------------|---------|---|")
    for basin, n in rows:
        lines.append(f"| {basin} | {n:,} | {n/total*100:.1f}% |")
    lines.append("")

    lines.append("## Output Files")
    lines.append("| File | Description |")
    lines.append("|------|-------------|")
    lines.append("| `cliwoc_cleaned.db` | SQLite database (primary) |")
    lines.append("| `cliwoc_cleaned.parquet` | Full dataset export |")
    lines.append("| `cliwoc_wind_timeseries.parquet` | Monthly × grid cell wind aggregates |")
    lines.append("| `wind_term_translations.json` | Wind translation audit trail |")
    lines.append("| `weather_classifications.json` | Weather classification audit trail |")
    lines.append("| `sea_state_classifications.json` | Sea state classification audit trail |")
    lines.append("| `quality_report.md` | This file |")
    lines.append("")

    lines.append("---")
    lines.append("*Generated by CLIWOC Data Cleaning Pipeline, Phase 6*")

    report = "\n".join(lines)
    QUALITY_REPORT.write_text(report)
    print(f"  Written: {QUALITY_REPORT}")
    return report


def main():
    print("=" * 70)
    print("CLIWOC DATA CLEANING — PHASE 6: VALIDATION & OUTPUT")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)

    # 1. Validation
    validation_df = validate_against_dagomar(conn)

    # 2. Quality flags
    flag_results = quality_flag_statistics(conn)

    # 3. Coverage
    coverage_results = data_coverage_summary(conn)

    # 4. Nationality breakdown
    nationality_breakdown(conn)

    # 5. Wind timeseries parquet
    generate_wind_timeseries(conn)

    # 6. Full parquet export
    export_full_parquet(conn)

    # 7. Wind translations table
    store_wind_translations_table(conn)

    # 8. Quality report
    generate_quality_report(conn, validation_df, flag_results, coverage_results)

    # ── Final database stats ──
    print("\n" + "=" * 70)
    print("PHASE 6 SUMMARY")
    print("=" * 70)
    cur = conn.cursor()
    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    indexes = cur.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    print(f"  Database: {DB_PATH}")
    print(f"  Tables: {[t[0] for t in tables]}")
    print(f"  Indexes: {len(indexes)}")
    print(f"  Total records: {total:,}")

    # List output files with sizes
    print(f"\n  Output files:")
    for f in sorted(OUT_DIR.glob("*")):
        if f.is_file() and not f.name.endswith("-journal"):
            size = f.stat().st_size
            if size > 1024 * 1024:
                print(f"    {f.name:45s} {size/1024/1024:.1f} MB")
            else:
                print(f"    {f.name:45s} {size/1024:.1f} KB")

    conn.close()
    print(f"\nPhase 6 complete. All outputs in: {OUT_DIR}")


if __name__ == "__main__":
    main()
