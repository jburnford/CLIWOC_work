"""
Phase 5: Derived Variables & Spatial Binning
CLIWOC Data Cleaning Pipeline for "Sailors and Circulation"

Creates:
  - grid_5x5: 5° × 5° lat/lon cell identifier (e.g. "(-5.0, 30.0)")
  - hemisphere: N or S
  - ocean_basin: Atlantic, Indian, Pacific, Arctic, Southern, Mediterranean, etc.
  - season: DJF/MAM/JJA/SON (hemisphere-adjusted)
  - W_midpoint: Beaufort midpoint wind speed (m/s) for sensitivity analysis

All operations done via SQL to avoid loading 287K × 200 columns into memory.
"""

import sqlite3
import math
from pathlib import Path

BASE_DIR = Path("/home/jic823/climate")
DB_PATH = BASE_DIR / "cleaned" / "cliwoc_cleaned.db"

# Beaufort midpoint values (m/s) — midpoints of each Beaufort range
# These are alternative to CLIWOC's upper-range values for sensitivity analysis
BEAUFORT_MIDPOINTS = {
    0: 0.15,    # 0.0-0.3 → 0.15
    1: 1.15,    # 0.3-1.6 → 0.95 (geometric mid might be better, use arithmetic)
    2: 2.8,     # 1.6-3.4 → 2.5 ... actually let me use standard midpoints
    3: 4.35,    # 3.4-5.5
    4: 7.15,    # 5.5-8.0 → 6.75
    5: 9.65,    # 8.0-10.8 → 9.4  (actually 9.35 but round)
    6: 12.35,   # 10.8-13.9
    7: 15.65,   # 13.9-17.2 → 15.55
    8: 18.95,   # 17.2-20.8 → 19.0
    9: 22.6,    # 20.8-24.5
    10: 27.0,   # 24.5-28.5 → 26.5
    11: 30.55,  # 28.5-32.7 → 30.6
    12: 34.0,   # >32.7
}

# More precise Beaufort scale midpoints (WMO standard ranges, m/s)
BEAUFORT_MIDPOINTS = {
    0: 0.15,    # 0.0–0.3
    1: 0.95,    # 0.3–1.6
    2: 2.45,    # 1.6–3.3
    3: 4.4,     # 3.4–5.4
    4: 6.7,     # 5.5–7.9
    5: 9.35,    # 8.0–10.7
    6: 12.3,    # 10.8–13.8
    7: 15.5,    # 13.9–17.1
    8: 18.95,   # 17.2–20.7
    9: 22.6,    # 20.8–24.4
    10: 26.45,  # 24.5–28.4
    11: 30.55,  # 28.5–32.6
    12: 34.0,   # ≥32.7 (use 34 as representative)
}


def classify_ocean_basin(lat, lon):
    """
    Classify a lat/lon point into an ocean basin.
    Simplified classification suitable for ship logbook data (mainly open ocean).
    """
    if lat is None or lon is None:
        return None

    # Normalize longitude to -180..180
    if lon > 180:
        lon -= 360

    # Southern Ocean (south of 60°S)
    if lat < -60:
        return "Southern"

    # Arctic (north of 66.5°N)
    if lat > 66.5:
        return "Arctic"

    # Mediterranean (roughly)
    if 30 <= lat <= 46 and -6 <= lon <= 42:
        return "Mediterranean"

    # Indian Ocean: east of 20°E (Africa), west of 147°E (Australia), south of 30°N
    if lat < 30 and 20 <= lon <= 147:
        # But exclude Pacific side of Indonesia/Australia
        if lon > 120 and lat > -10:
            # South China Sea / Philippine Sea area — Pacific
            return "Pacific"
        return "Indian"

    # Pacific Ocean
    if lon > 100 or lon < -70:
        # But distinguish Atlantic vs Pacific in Americas
        if -70 <= lon <= -20:
            # Could be either — use Panama (~8°N) as divider
            if lat >= 0:
                # North — between 70W and 20W is Atlantic
                return "Atlantic"
            else:
                # South — Cape Horn is ~67W
                if lon > -67:
                    return "Atlantic"
                else:
                    return "Pacific"
        return "Pacific"

    # Atlantic Ocean (default for remaining)
    return "Atlantic"


def get_season(month, hemisphere):
    """Get meteorological season, adjusted for hemisphere."""
    if month is None:
        return None
    m = int(month)
    if hemisphere == "S":
        # Southern hemisphere: seasons shifted by 6 months
        if m in (12, 1, 2):
            return "JJA"  # Southern summer ≈ Northern winter
        elif m in (3, 4, 5):
            return "SON"
        elif m in (6, 7, 8):
            return "DJF"
        else:
            return "MAM"
    else:
        if m in (12, 1, 2):
            return "DJF"
        elif m in (3, 4, 5):
            return "MAM"
        elif m in (6, 7, 8):
            return "JJA"
        else:
            return "SON"


def main():
    print("=" * 70)
    print("CLIWOC DATA CLEANING — PHASE 5: DERIVED VARIABLES & SPATIAL BINNING")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)
    conn.create_function("classify_ocean", 2, classify_ocean_basin)
    conn.create_function("get_season", 2, get_season)
    cur = conn.cursor()

    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    print(f"\nTotal records: {total:,}")

    # ── Add columns ──
    new_cols = [
        ("grid_5x5", "TEXT"),
        ("hemisphere", "TEXT"),
        ("ocean_basin", "TEXT"),
        ("season", "TEXT"),
        ("W_midpoint", "REAL"),
    ]
    for col, typ in new_cols:
        try:
            cur.execute(f"ALTER TABLE observations ADD COLUMN {col} {typ}")
            print(f"  Added column: {col}")
        except sqlite3.OperationalError:
            print(f"  Column exists: {col}")
    conn.commit()

    # ── 1. Grid 5×5, hemisphere ──
    print("\n── 1. Spatial binning (grid_5x5, hemisphere) ──")
    # Use CAST to convert text lat/lon to REAL, then floor to 5° grid
    cur.execute("""
        UPDATE observations
        SET grid_5x5 = '(' ||
            CAST(CAST(CAST(latitude AS REAL) / 5.0 AS INTEGER) * 5 AS TEXT) || ', ' ||
            CAST(CAST(CAST(longitude AS REAL) / 5.0 AS INTEGER) * 5 AS TEXT) || ')',
            hemisphere = CASE
                WHEN CAST(latitude AS REAL) >= 0 THEN 'N'
                ELSE 'S'
            END
        WHERE latitude IS NOT NULL AND latitude != ''
          AND longitude IS NOT NULL AND longitude != ''
    """)
    n_grid = cur.rowcount
    conn.commit()
    print(f"  Grid + hemisphere assigned: {n_grid:,} records")

    # Check grid distribution
    rows = cur.execute("""
        SELECT grid_5x5, COUNT(*) FROM observations
        WHERE grid_5x5 IS NOT NULL
        GROUP BY grid_5x5 ORDER BY COUNT(*) DESC LIMIT 10
    """).fetchall()
    print("  Top 10 grid cells:")
    for grid, cnt in rows:
        print(f"    {grid:15s}: {cnt:,}")

    hemi = cur.execute("""
        SELECT hemisphere, COUNT(*) FROM observations
        WHERE hemisphere IS NOT NULL GROUP BY hemisphere
    """).fetchall()
    for h, cnt in hemi:
        print(f"  Hemisphere {h}: {cnt:,}")

    # ── 2. Ocean basin ──
    print("\n── 2. Ocean basin classification ──")
    # Use the registered UDF
    cur.execute("""
        UPDATE observations
        SET ocean_basin = classify_ocean(CAST(latitude AS REAL), CAST(longitude AS REAL))
        WHERE latitude IS NOT NULL AND latitude != ''
          AND longitude IS NOT NULL AND longitude != ''
    """)
    n_ocean = cur.rowcount
    conn.commit()
    print(f"  Ocean basin assigned: {n_ocean:,} records")

    rows = cur.execute("""
        SELECT ocean_basin, COUNT(*) FROM observations
        WHERE ocean_basin IS NOT NULL
        GROUP BY ocean_basin ORDER BY COUNT(*) DESC
    """).fetchall()
    for basin, cnt in rows:
        print(f"    {basin:15s}: {cnt:,}")

    # ── 3. Season ──
    print("\n── 3. Season (hemisphere-adjusted) ──")
    cur.execute("""
        UPDATE observations
        SET season = get_season(CAST(Month AS INTEGER), hemisphere)
        WHERE Month IS NOT NULL AND hemisphere IS NOT NULL
    """)
    n_season = cur.rowcount
    conn.commit()
    print(f"  Season assigned: {n_season:,} records")

    rows = cur.execute("""
        SELECT season, COUNT(*) FROM observations
        WHERE season IS NOT NULL GROUP BY season ORDER BY season
    """).fetchall()
    for s, cnt in rows:
        print(f"    {s}: {cnt:,}")

    # ── 4. W_midpoint (Beaufort midpoint wind speed) ──
    print("\n── 4. Beaufort midpoint wind speed (W_midpoint) ──")
    # Build CASE expression for beaufort_corrected → midpoint
    case_parts = " ".join(
        f"WHEN {bf} THEN {mid}" for bf, mid in BEAUFORT_MIDPOINTS.items()
    )
    cur.execute(f"""
        UPDATE observations
        SET W_midpoint = CASE beaufort_corrected {case_parts} ELSE NULL END
        WHERE beaufort_corrected IS NOT NULL
    """)
    n_mid = cur.rowcount
    conn.commit()
    print(f"  W_midpoint assigned: {n_mid:,} records")

    # Also fill from beaufort (non-corrected) where beaufort_corrected is NULL
    cur.execute(f"""
        UPDATE observations
        SET W_midpoint = CASE beaufort {case_parts} ELSE NULL END
        WHERE W_midpoint IS NULL AND beaufort IS NOT NULL
    """)
    n_mid2 = cur.rowcount
    conn.commit()
    print(f"  W_midpoint from beaufort (fallback): {n_mid2:,} additional records")

    # Compare W_corrected vs W_midpoint
    row = cur.execute("""
        SELECT
            AVG(W_corrected / 10.0) as avg_w_corrected,
            AVG(W_midpoint) as avg_w_midpoint,
            COUNT(*) as n
        FROM observations
        WHERE W_corrected IS NOT NULL AND W_midpoint IS NOT NULL
    """).fetchone()
    print(f"  Comparison (n={row[2]:,}):")
    print(f"    Avg W_corrected/10: {row[0]:.2f} m/s (CLIWOC upper-range)")
    print(f"    Avg W_midpoint:     {row[1]:.2f} m/s (Beaufort midpoint)")

    # ── Create indexes ──
    print("\n── Creating indexes ──")
    indexes = [
        ("idx_obs_grid", "grid_5x5"),
        ("idx_obs_hemisphere", "hemisphere"),
        ("idx_obs_ocean_basin", "ocean_basin"),
        ("idx_obs_season", "season"),
    ]
    for name, col in indexes:
        cur.execute(f"CREATE INDEX IF NOT EXISTS {name} ON observations ({col})")
    conn.commit()

    # ── Summary ──
    print("\n" + "=" * 70)
    print("PHASE 5 SUMMARY")
    print("=" * 70)

    for col in ["grid_5x5", "hemisphere", "ocean_basin", "season", "W_midpoint"]:
        r = cur.execute(f"SELECT COUNT(*) FROM observations WHERE {col} IS NOT NULL").fetchone()
        print(f"  {col:20s}: {r[0]:,} / {total:,} ({r[0]/total*100:.1f}%)")

    # Final column count
    all_cols = cur.execute("PRAGMA table_info(observations)").fetchall()
    print(f"\n  Total columns in observations table: {len(all_cols)}")

    conn.close()
    print(f"\nPhase 5 complete. Database: {DB_PATH}")


if __name__ == "__main__":
    main()
