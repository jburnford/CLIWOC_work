"""
Phase 1: Foundation — Load, Validate, Calendar Fix
CLIWOC Data Cleaning Pipeline for "Sailors and Circulation"

Loads CLIWOC21.tsv into SQLite, validates units, fixes Julian calendar dates,
creates convenience columns, and flags duplicates/outliers.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/jic823/climate")
RAW_TSV = BASE_DIR / "CLIWOC21.tsv"
OUT_DIR = BASE_DIR / "cleaned"
DB_PATH = OUT_DIR / "cliwoc_cleaned.db"

OUT_DIR.mkdir(parents=True, exist_ok=True)


def load_raw(path: Path) -> pd.DataFrame:
    """Load CLIWOC21.tsv and drop corrupt rows."""
    print(f"Loading {path} ...")
    df = pd.read_csv(path, sep="\t", low_memory=False)
    print(f"  Loaded {len(df):,} rows, {len(df.columns)} columns")

    # Drop corrupt rows: Year or Nationality is NaN (3 known corrupt rows)
    n_before = len(df)
    df = df.dropna(subset=["Year", "Nationality"]).copy()
    n_dropped = n_before - len(df)
    print(f"  Dropped {n_dropped} corrupt rows (missing Year or Nationality)")
    print(f"  Remaining: {len(df):,} rows")
    return df


def verify_units(df: pd.DataFrame):
    """Spot-check that AT is tenths °C and SLP is tenths hPa."""
    print("\n── Unit Verification ──")

    # AT: tenths of °C → divide by 10 should give reasonable temperatures
    at_valid = df["AT"].dropna()
    if len(at_valid) > 0:
        at_celsius = at_valid / 10.0
        print(f"  AT (n={len(at_valid):,}): "
              f"min={at_celsius.min():.1f}°C, "
              f"median={at_celsius.median():.1f}°C, "
              f"max={at_celsius.max():.1f}°C")
        # Check by provenance unit type
        for unit in df["AirThermReadingUnits"].dropna().unique():
            mask = (df["AirThermReadingUnits"] == unit) & df["AT"].notna()
            if mask.sum() > 0:
                vals = df.loc[mask, "AT"] / 10.0
                print(f"    {unit} (n={mask.sum():,}): "
                      f"median={vals.median():.1f}°C, "
                      f"range=[{vals.min():.1f}, {vals.max():.1f}]")

    # SLP: tenths of hPa → divide by 10 should give ~960-1050 hPa
    slp_valid = df["SLP"].dropna()
    if len(slp_valid) > 0:
        slp_hpa = slp_valid / 10.0
        print(f"  SLP (n={len(slp_valid):,}): "
              f"min={slp_hpa.min():.1f} hPa, "
              f"median={slp_hpa.median():.1f} hPa, "
              f"max={slp_hpa.max():.1f} hPa")


def _day_of_year(y, m, d):
    """Day-of-year for a given date (1-indexed)."""
    days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0):
        days_in_month[1] = 29
    return sum(days_in_month[:m - 1]) + d


def _days_in_year(y):
    if (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0):
        return 366
    return 365


def build_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create Gregorian date columns (date_iso, decimal_year).

    The CLIWOC team already converted Julian→Gregorian in the YR/MO/DY columns:
      - YR/MO/DY = Gregorian dates (corrected +11 days for Calendar=1 records)
      - Year/Month/Day = original logbook dates (Julian for Calendar=1)
    Verified: for all 4,663 Julian records, Year/Month/Day + 11 == YR/MO/DY.

    We use YR/MO/DY directly — no additional correction needed.

    NOTE: We avoid pandas datetime64[ns] because it can't represent dates
    before 1677, and CLIWOC data starts in 1662. Instead we build date_iso
    strings and decimal_year floats directly from integer components.
    """
    print("\n── Date Construction ──")

    # Coerce to numeric (corrupt non-numeric values already dropped)
    yr = pd.to_numeric(df["YR"], errors="coerce")
    mo = pd.to_numeric(df["MO"], errors="coerce")
    dy = pd.to_numeric(df["DY"], errors="coerce")

    date_iso = []
    decimal_year = []
    n_invalid = 0

    for y, m, d in zip(yr, mo, dy):
        if pd.isna(y) or pd.isna(m) or pd.isna(d):
            date_iso.append(None)
            decimal_year.append(np.nan)
            n_invalid += 1
            continue

        y, m, d = int(y), int(m), int(d)
        if y < 1 or y > 2100 or m < 1 or m > 12 or d < 1:
            date_iso.append(None)
            decimal_year.append(np.nan)
            n_invalid += 1
            continue

        # Clamp day to valid range for month
        max_days = [31, 29 if ((y % 4 == 0 and y % 100 != 0) or y % 400 == 0) else 28,
                    31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        d = min(d, max_days[m - 1])

        date_iso.append(f"{y:04d}-{m:02d}-{d:02d}")
        doy = _day_of_year(y, m, d)
        diy = _days_in_year(y)
        decimal_year.append(y + (doy - 1) / diy)

    df["date_iso"] = date_iso
    df["decimal_year"] = decimal_year
    valid = df["date_iso"].notna()
    print(f"  Valid dates: {valid.sum():,} / Invalid: {n_invalid}")

    # QC flag: mark records where CLIWOC applied Julian→Gregorian conversion
    julian_mask = df["Calendar"] == 1.0
    df["qc_calendar_converted"] = julian_mask & valid
    n_julian = df["qc_calendar_converted"].sum()
    print(f"  Julian→Gregorian (by CLIWOC team): {n_julian:,} records flagged")

    print(f"  date_iso sample: {df['date_iso'].dropna().iloc[:3].tolist()}")
    print(f"  decimal_year range: [{df['decimal_year'].min():.2f}, {df['decimal_year'].max():.2f}]")

    return df


def create_convenience_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Create AT_celsius and SLP_hPa from raw tenths columns."""
    print("\n── Convenience Columns ──")

    # AT is tenths of °C
    df["AT_celsius"] = pd.to_numeric(df["AT"], errors="coerce") / 10.0
    n_at = df["AT_celsius"].notna().sum()
    print(f"  AT_celsius: {n_at:,} valid values, "
          f"median={df['AT_celsius'].median():.1f}°C")

    # SLP is tenths of hPa
    df["SLP_hPa"] = pd.to_numeric(df["SLP"], errors="coerce") / 10.0
    n_slp = df["SLP_hPa"].notna().sum()
    print(f"  SLP_hPa: {n_slp:,} valid values, "
          f"median={df['SLP_hPa'].median():.1f} hPa")

    return df


def flag_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Flag potential duplicates: same date + lat + lon + ship."""
    print("\n── Duplicate Detection ──")

    # Use date_iso + latitude + longitude + ShipName
    dup_cols = ["date_iso", "latitude", "longitude", "ShipName"]
    # Only flag among records where all dup_cols are non-null
    has_all = df[dup_cols].notna().all(axis=1)
    df["qc_duplicate"] = False
    df.loc[has_all, "qc_duplicate"] = df.loc[has_all].duplicated(
        subset=dup_cols, keep=False
    )
    n_dups = df["qc_duplicate"].sum()
    print(f"  Potential duplicates: {n_dups:,} records ({n_dups/len(df)*100:.2f}%)")

    if n_dups > 0:
        # Show nationality breakdown
        dup_nat = df.loc[df["qc_duplicate"], "Nationality"].value_counts()
        for nat, count in dup_nat.items():
            print(f"    {nat}: {count:,}")

    return df


def flag_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """Flag physically implausible temperature and pressure values."""
    print("\n── Outlier Detection ──")

    # Temperature outliers: < -40°C or > 50°C
    df["qc_temp_outlier"] = False
    at_valid = df["AT_celsius"].notna()
    df.loc[at_valid, "qc_temp_outlier"] = (
        (df.loc[at_valid, "AT_celsius"] < -40) |
        (df.loc[at_valid, "AT_celsius"] > 50)
    )
    n_temp_out = df["qc_temp_outlier"].sum()
    print(f"  Temperature outliers (< -40°C or > 50°C): {n_temp_out}")
    if n_temp_out > 0:
        outliers = df.loc[df["qc_temp_outlier"], ["date_iso", "AT_celsius", "latitude",
                                                    "longitude", "Nationality"]]
        print(outliers.to_string())

    # Pressure outliers: < 870 hPa or > 1084 hPa
    df["qc_pressure_outlier"] = False
    slp_valid = df["SLP_hPa"].notna()
    df.loc[slp_valid, "qc_pressure_outlier"] = (
        (df.loc[slp_valid, "SLP_hPa"] < 870) |
        (df.loc[slp_valid, "SLP_hPa"] > 1084)
    )
    n_pres_out = df["qc_pressure_outlier"].sum()
    print(f"  Pressure outliers (< 870 hPa or > 1084 hPa): {n_pres_out}")
    if n_pres_out > 0:
        outliers = df.loc[df["qc_pressure_outlier"], ["date_iso", "SLP_hPa", "latitude",
                                                       "longitude", "Nationality"]]
        print(outliers.to_string())

    return df


def save_to_sqlite(df: pd.DataFrame, db_path: Path):
    """Save DataFrame to SQLite database."""
    print(f"\n── Saving to {db_path} ──")

    conn = sqlite3.connect(db_path)

    # Drop old table if exists
    conn.execute("DROP TABLE IF EXISTS observations")

    # Write DataFrame
    df.to_sql("observations", conn, index=False, if_exists="replace")
    n_rows = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    print(f"  Wrote {n_rows:,} rows to 'observations' table")

    # Create indexes for common queries
    indexes = [
        ("idx_obs_year", "Year"),
        ("idx_obs_nationality", "Nationality"),
        ("idx_obs_shipname", "ShipName"),
        ("idx_obs_date_iso", "date_iso"),
        ("idx_obs_decimal_year", "decimal_year"),
    ]
    for idx_name, col in indexes:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON observations ({col})")
        print(f"  Created index {idx_name} on {col}")

    conn.commit()

    # Report size
    db_size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"  Database size: {db_size_mb:.1f} MB")

    conn.close()


def print_summary(df: pd.DataFrame):
    """Print Phase 1 summary statistics."""
    print("\n" + "=" * 70)
    print("PHASE 1 SUMMARY")
    print("=" * 70)
    print(f"Total records: {len(df):,}")
    print(f"Date range: {df['date_iso'].min()} to {df['date_iso'].max()}")
    print(f"Decimal year range: {df['decimal_year'].min():.2f} to {df['decimal_year'].max():.2f}")
    print()

    print("Coverage:")
    print(f"  With position (lat+lon): {(df['latitude'].notna() & df['longitude'].notna()).sum():,}")
    print(f"  With temperature (AT):   {df['AT_celsius'].notna().sum():,}")
    print(f"  With pressure (SLP):     {df['SLP_hPa'].notna().sum():,}")
    print(f"  With wind speed (W):     {pd.to_numeric(df['W'], errors='coerce').notna().sum():,}")
    print(f"  With wind direction (D): {pd.to_numeric(df['D'], errors='coerce').notna().sum():,}")
    print()

    print("QC Flags:")
    print(f"  qc_calendar_converted:  {df['qc_calendar_converted'].sum():,}")
    print(f"  qc_duplicate:           {df['qc_duplicate'].sum():,}")
    print(f"  qc_temp_outlier:        {df['qc_temp_outlier'].sum():,}")
    print(f"  qc_pressure_outlier:    {df['qc_pressure_outlier'].sum():,}")
    print()

    print("Nationality breakdown:")
    for nat, count in df["Nationality"].value_counts().items():
        print(f"  {nat}: {count:,} ({count/len(df)*100:.1f}%)")

    print()
    print("New columns added:")
    new_cols = ["date_iso", "decimal_year", "AT_celsius", "SLP_hPa",
                "qc_calendar_converted", "qc_duplicate",
                "qc_temp_outlier", "qc_pressure_outlier"]
    for col in new_cols:
        dtype = df[col].dtype
        non_null = df[col].notna().sum()
        print(f"  {col:30s} {str(dtype):10s} ({non_null:,} non-null)")


def main():
    print("=" * 70)
    print("CLIWOC DATA CLEANING — PHASE 1: FOUNDATION")
    print("=" * 70)

    # 1. Load
    df = load_raw(RAW_TSV)

    # 2. Verify units (informational only)
    verify_units(df)

    # 3. Build Gregorian dates (YR/MO/DY already corrected by CLIWOC team)
    df = build_dates(df)

    # 4. Convenience columns
    df = create_convenience_columns(df)

    # 5. Duplicates
    df = flag_duplicates(df)

    # 6. Outliers
    df = flag_outliers(df)

    # 7. Save
    save_to_sqlite(df, DB_PATH)

    # 8. Summary
    print_summary(df)

    print(f"\nPhase 1 complete. Database: {DB_PATH}")
    return df


if __name__ == "__main__":
    df = main()
