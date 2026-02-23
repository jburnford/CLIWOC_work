"""
Phase 2: Wind Direction Cleaning
CLIWOC Data Cleaning Pipeline for "Sailors and Circulation"

Normalizes D values (calm/variable flags), parses AllWindDirections text,
computes u/v wind vector components, and creates Beaufort column.

Strategy:
  - Only load the 3 columns we need (D, W, AllWindDirections) + rowid
  - Deduplicate direction text: parse 261 unique values, not 287K rows
  - Write results back with SQL UPDATEs in batches (no table drop/recreate)
"""

import math
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/jic823/climate")
OUT_DIR = BASE_DIR / "cleaned"
DB_PATH = OUT_DIR / "cliwoc_cleaned.db"

# ── Compass dictionaries ──────────────────────────────────────────────────────

# Standard English 32-point compass
COMPASS_EN = {
    "N": 0, "NBE": 11.25, "NNE": 22.5, "NEBN": 33.75,
    "NE": 45, "NEBE": 56.25, "ENE": 67.5, "EBN": 78.75,
    "E": 90, "EBS": 101.25, "ESE": 112.5, "SEBE": 123.75,
    "SE": 135, "SEBS": 146.25, "SSE": 157.5, "SBE": 168.75,
    "S": 180, "SBW": 191.25, "SSW": 202.5, "SWBS": 213.75,
    "SW": 225, "SWBW": 236.25, "WSW": 247.5, "WBS": 258.75,
    "W": 270, "WBN": 281.25, "WNW": 292.5, "NWBW": 303.75,
    "NW": 315, "NWBN": 326.25, "NNW": 337.5, "NBW": 348.75,
    # Additional English variants seen in data
    "EBW": 270 - 78.75,  # not standard, but appears: E by W doesn't make sense,
    # treat as typo — skip (handled below)
    "NEBW": 348.75,  # NE by W? Probably NBW = 348.75
}

# Dutch compass (O=Oost=East, Z=Zuid=South)
COMPASS_NL = {
    "N": 0, "NTO": 11.25, "NNO": 22.5, "NOTN": 33.75,
    "NO": 45, "NOTO": 56.25, "ONO": 67.5, "OTN": 78.75,
    "O": 90, "OTZ": 101.25, "OZO": 112.5, "ZOTO": 123.75,
    "ZO": 135, "ZOTZ": 146.25, "ZZO": 157.5, "ZTO": 168.75,
    "Z": 180, "ZTW": 191.25, "ZZW": 202.5, "ZWTZ": 213.75,
    "ZW": 225, "ZWTW": 236.25, "WZW": 247.5, "WTZ": 258.75,
    "W": 270, "WTN": 281.25, "WNW": 292.5, "NWTW": 303.75,
    "NW": 315, "NWTN": 326.25, "NNW": 337.5, "NTW": 348.75,
}

# Spanish compass (O=Oeste=West)
COMPASS_ES = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSO": 202.5, "SO": 225, "OSO": 247.5,
    "O": 270, "ONO": 292.5, "NO": 315, "NNO": 337.5,
}

# French compass (O=Ouest=West)
COMPASS_FR = {
    "N": 0, "NNE": 22.5, "NE": 45, "ENE": 67.5,
    "E": 90, "ESE": 112.5, "SE": 135, "SSE": 157.5,
    "S": 180, "SSO": 202.5, "SO": 225, "OSO": 247.5,
    "O": 270, "ONO": 292.5, "NO": 315, "NNO": 337.5,
}

# Dutch doubling abbreviations observed in data:
# NEE = midpoint of NE(45) and E(90) = ENE(67.5)
# NEN = midpoint of NE(45) and N(0) = NNE(22.5)
# NON = midpoint of NO(45) and N(0) = NNO(22.5) [Dutch]
# NOO = midpoint of NO(45) and O(90) = ONO(67.5) [Dutch]
# SEE = midpoint of SE(135) and E(90) = ESE(112.5)
# SES = midpoint of SE(135) and S(180) = SSE(157.5)
# SOO = midpoint of SO(225) and O(270) = OSO(247.5) [Spanish]
# SOS = midpoint of SO(225) and S(180) = SSO(202.5) [Spanish]
# OTE = midpoint of O(90) and ?(probably Dutch abbreviation anomaly)
# ONE = midpoint of O(270) and NE(45)? [Spanish O=W] → unclear
# ENO = midpoint of E(90) and NO(315)? → unclear
DOUBLED_ABBREVS = {
    "NEE": 67.5,   # NE→E = ENE
    "NEN": 22.5,   # NE→N = NNE
    "NON": 22.5,   # NO→N = NNO (Dutch NO=NE)
    "NOO": 67.5,   # NO→O = ONO (Dutch NO=NE, O=E)
    "SEE": 112.5,  # SE→E = ESE
    "SES": 157.5,  # SE→S = SSE
    "SOO": 247.5,  # SO→O = OSO (Spanish SO=SW, O=W)
    "SOS": 202.5,  # SO→S = SSO (Spanish SO=SW)
    "NWW": 292.5,  # NW→W = WNW
    "ZWW": 247.5,  # ZW→W = WZW (Dutch ZW=SW)
    "ONE": 292.5,  # O→NE? Hard to tell. Spanish O=W, probably ONO(292.5)
    "ENO": 67.5,   # E→NO? Dutch ONO = 67.5
    "OTE": 78.75,  # Dutch: probably OTN (East by North) = 78.75
    "NN": 0,       # North
    "SS": 180,     # South
}

# Dutch adjectival forms (-elijk / -elijk suffix)
DUTCH_ADJECTIVAL = {
    "ZUIDOOSTELIJK": 135,   # southeasterly = ZO
    "OOSTELIJK": 90,        # easterly = O
    "NOORDOOSTELIJK": 45,   # northeasterly = NO
    "ZUIDELIJK": 180,       # southerly = Z
    "NOORDELIJK": 0,        # northerly = N
    "WESTELIJK": 270,       # westerly = W
    "ZUIDWESTELIJK": 225,   # southwesterly = ZW
    "NOORDWESTELIJK": 315,  # northwesterly = NW
}

# Terms indicating variable/calm
VARIABLE_TERMS = {
    "VARIABLE", "VARIABLES", "VARIABEL", "VARIABELE",
    "LOPENDE WINDEN", "LOPENDE WIND", "LOPEND",
    "VARIABLE AND CALMS", "VARIABLE WINDS", "LIGHT AND VARIABLE",
    "VARIABLE LIGHT AIRS", "LIGHT VARIABLE AIRS",
    "ZEER VARIABEL", "WISSELEND", "VERANDERLIJK",
    "VARIABELE WIND", "VARIABELE LUCHTJES EN STIL",
    "VARIABLE WITH CALMS", "VARIABLE WITH LAND AND SEA BREEZES",
    "VARIABLE WINDS AND FAIR", "VARIABLE, OPKRIMPEND",
    "OMLOPENDE ONGESTADIGDE WINDEN", "NOGAL LOPENDE WINDEN",
    "RONDLOPEND", "KOMPAS ROND", "WIND INT ROND",
    "DE WIND RONDOM", "VAN NW HET KOMPASROND EN OP EN NEER",
    "LE VENT AFAIT LE TOUR DU COMPAS",
    "TOUTES PARTIES", "TOUTES PARTIES JUSQUÉ", "TOUTE PARTIES",
    "DE TOUTES PART",
    "ROLO TODA LA AGUJA",  # Spanish: wind went all around the compass
    "DAN OVER DE ENE KANT DAN OVER DE ANDERE",
    "W-OP EN NEER", "W, OP EN NEER", "DE WIND OP EN NEER",
    "NU, DAN OM", "IN- EN UITLOPEND", "IN, UITLOPEND", "IN, UITLOOPEND",
    "WIND ZEER ONGELIJK", "WINDSTOTEN",
    "4° AL 1° QTE", "3° QTE", "2° QTE", "3 Y 4º QTE",
}

CALM_TERMS = {
    "CALM", "CALMS", "CALMA", "CALMAS", "KALM", "KALMTE", "STILTE",
    "STIL", "CALMA MUERTA",
}

# Non-directional terms (land/sea breezes, regional wind names)
NONDIRECTIONAL_TERMS = {
    "LAND, ZEEWIND", "LANDWIND", "ZEEWIND", "LAND AND SEA BREEZES",
    "SEA BREEZE", "LAND BREEZE", "SEA AND LAND BREEZES",
    "A LA TIERRA", "A TIERRA", "TERRAL", "DE TIERRA", "DE LA TIERRA",
    "TERRALES Y VIRAZONES", "TERRAL Y VIRAZON",
    "BRISA", "VIRAZÓN", "VIRAZON",
    "HARDE LAND, ZEEWIND", "WIND VAN LAND",
    "L(AND)WIND", "LANDELIJK", "LANDLIJK", "LANDIG",
    "PAMPERO",  # Argentine SW squall wind
    "PONIENTE", "PONIENTES",  # Spanish: westerly (can't be more specific)
    "LEVANTE",  # Spanish: easterly (Strait of Gibraltar term)
    "DE POPA",  # Spanish: from the stern (following wind — direction depends on course)
    "VOORDELIGE WIND", "IN ONS VOORDEEL",  # Dutch: favorable wind
    "FAVORABEL",  # French: favorable
    "CONTRARIE WIND",  # Dutch: contrary wind
    "TEGEN DE MIDDAG VERANDERT DE WIND IN ONS VOORDEEL",
}


def build_compass_lookup():
    """Build a unified compass lookup from all languages + extensions."""
    lookup = {}
    for d in [COMPASS_EN, COMPASS_NL, COMPASS_ES, COMPASS_FR,
              DOUBLED_ABBREVS, DUTCH_ADJECTIVAL]:
        for term, deg in d.items():
            if term not in lookup:
                lookup[term] = deg
    return lookup


COMPASS_LOOKUP = build_compass_lookup()


def circular_mean(degrees_list):
    """Compute circular mean of a list of degree values."""
    sin_sum = sum(math.sin(math.radians(d)) for d in degrees_list)
    cos_sum = sum(math.cos(math.radians(d)) for d in degrees_list)
    return math.degrees(math.atan2(sin_sum, cos_sum)) % 360


def parse_direction_text(text, compass=COMPASS_LOOKUP):
    """
    Parse AllWindDirections text into degrees.

    Returns (degrees, method) where method is:
      - 'compass': direct compass point match
      - 'mean': mean of multiple compass points
      - 'variable': variable wind
      - 'calm': calm conditions
      - 'nondirectional': land/sea breeze etc.
      - None: couldn't parse
    """
    if not isinstance(text, str) or not text.strip():
        return np.nan, None

    text = text.strip().upper()

    # Check variable/calm/nondirectional
    if text in VARIABLE_TERMS:
        return np.nan, "variable"
    if text in CALM_TERMS:
        return np.nan, "calm"
    if text in NONDIRECTIONAL_TERMS:
        return np.nan, "nondirectional"

    # Direct compass lookup (includes doubled abbrevs and adjectival forms)
    if text in compass:
        return compass[text], "compass"

    # Handle "VARIABEL" prefix with direction: "VARIABEL EN NOORDELIJK" etc.
    var_dir = re.match(r'^VARIABEL\w*\s+(?:EN\s+|TOT\s+)?(\w+)$', text)
    if var_dir:
        term = var_dir.group(1)
        if term in compass:
            return np.nan, "variable"  # variable with dominant direction — still variable

    # Handle fractional points: "ZW 1/4 W", "NO 1/4 NO", "E 1/4 E"
    frac_match = re.match(r'^([A-Z]+)\s+(\d)/(\d)\s+([A-Z]+)$', text)
    if frac_match:
        base, num, den, toward = frac_match.groups()
        if base in compass and toward in compass:
            base_deg = compass[base]
            toward_deg = compass[toward]
            diff = toward_deg - base_deg
            if diff > 180:
                diff -= 360
            elif diff < -180:
                diff += 360
            result = (base_deg + diff * int(num) / int(den)) % 360
            return result, "compass"
        # Self-referential like "NO 1/4 NO" → just use base
        if base in compass:
            return compass[base], "compass"

    # Handle range patterns: "ZO-ZZO", "NO-NOTO", "OZO-O"
    range_match = re.match(r'^([A-Z]+)\s*[-–]\s*([A-Z]+)$', text)
    if range_match:
        a, b = range_match.group(1), range_match.group(2)
        if a in compass and b in compass:
            return circular_mean([compass[a], compass[b]]), "mean"
        # One side might be a doubled abbrev
        if a in compass:
            return compass[a], "compass"
        if b in compass:
            return compass[b], "compass"

    # Handle "STIL-ZO" (calm then direction) — use the direction
    stil_match = re.match(r'^STIL\s*[-–]\s*([A-Z]+)$', text)
    if stil_match and stil_match.group(1) in compass:
        return compass[stil_match.group(1)], "compass"

    # Handle compound with "SW1/2W, WBW" style
    compound_match = re.match(r'^([A-Z]+)(\d)/(\d)([A-Z]+)', text)
    if compound_match:
        base, num, den, toward = compound_match.groups()
        if base in compass and toward in compass:
            base_deg = compass[base]
            toward_deg = compass[toward]
            diff = toward_deg - base_deg
            if diff > 180:
                diff -= 360
            elif diff < -180:
                diff += 360
            result = (base_deg + diff * int(num) / int(den)) % 360
            return result, "compass"

    # Multi-part: split on comma, semicolon, "AND", "EN", "&"
    parts = re.split(r'[,;&]\s*|\s+AND\s+|\s+EN\s+', text)
    degrees = []
    for part in parts:
        part = part.strip()
        if part in compass:
            degrees.append(compass[part])

    if len(degrees) == 1:
        return degrees[0], "compass"
    elif len(degrees) > 1:
        return circular_mean(degrees), "mean"

    # Try extracting any compass point from within the text
    # For complex descriptions like "FIRST AND MIDDLE PART WIND AT NE, LATTER PART DRAWING ROUND"
    found = []
    for term in sorted(compass.keys(), key=len, reverse=True):
        if re.search(r'\b' + re.escape(term) + r'\b', text):
            found.append(compass[term])
            break  # take the first (longest) match

    if len(found) == 1:
        return found[0], "compass"

    return np.nan, None


def main():
    print("=" * 70)
    print("CLIWOC DATA CLEANING — PHASE 2: WIND DIRECTION")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)

    # ── Step 1: Load only the columns we need ──
    print("\nLoading D, W, AllWindDirections from database ...")
    df = pd.read_sql("SELECT rowid, D, W, AllWindDirections FROM observations", conn)
    n_total = len(df)
    print(f"  Loaded {n_total:,} rows (3 columns + rowid)")

    D = pd.to_numeric(df["D"], errors="coerce")
    W = pd.to_numeric(df["W"], errors="coerce")

    # ── Step 2: Classify D values ──
    print("\n── Wind Direction Cleaning ──")

    # Valid compass bearings (0-360)
    valid_mask = D.notna() & (D >= 0) & (D <= 360)
    n_valid = valid_mask.sum()
    print(f"  Valid D (0-360): {n_valid:,}")

    # D=361 → calm
    calm_mask = D == 361
    n_calm = calm_mask.sum()
    print(f"  D=361 (calm): {n_calm:,}")

    # D=362 → variable
    var_mask = D == 362
    n_var = var_mask.sum()
    print(f"  D=362 (variable): {n_var:,}")

    # Missing D
    missing_d = D.isna() | (D > 362)
    n_missing = missing_d.sum()
    print(f"  Missing D (null or >362): {n_missing:,}")

    # ── Step 3: Parse AllWindDirections for missing D records ──
    has_text = df["AllWindDirections"].notna() & (df["AllWindDirections"] != "")
    to_parse = missing_d & has_text
    n_to_parse = to_parse.sum()
    print(f"  Missing D with text to parse: {n_to_parse:,}")

    # Deduplicate: get unique text values and parse each once
    if n_to_parse > 0:
        unique_texts = df.loc[to_parse, "AllWindDirections"].unique()
        print(f"  Unique direction texts: {len(unique_texts)}")

        text_lookup = {}  # text → (degrees, method)
        for text in unique_texts:
            text_lookup[text] = parse_direction_text(text)

        # Count by method
        methods = {}
        for text, (deg, method) in text_lookup.items():
            methods[method] = methods.get(method, 0) + 1
        for method, count in sorted(methods.items(), key=lambda x: -x[1]):
            print(f"    {method}: {count} unique terms")

        # Show unparseable terms
        unparseable = [(t, df.loc[to_parse & (df["AllWindDirections"] == t)].shape[0])
                       for t, (d, m) in text_lookup.items() if m is None]
        if unparseable:
            unparseable.sort(key=lambda x: -x[1])
            print(f"\n  Unparseable terms ({len(unparseable)} unique, "
                  f"{sum(c for _, c in unparseable)} records):")
            for text, count in unparseable[:15]:
                print(f"    {count:3d}x  \"{text}\"")
            if len(unparseable) > 15:
                print(f"    ... and {len(unparseable) - 15} more")

    # ── Step 4: Build result arrays ──
    print("\n── Building result columns ──")

    D_cleaned = np.full(n_total, np.nan)
    qc_wind_calm = np.zeros(n_total, dtype=bool)
    qc_wind_variable = np.zeros(n_total, dtype=bool)
    qc_direction_imputed = np.zeros(n_total, dtype=bool)

    # Valid D values
    D_cleaned[valid_mask.values] = D[valid_mask].values

    # D=361 calm
    qc_wind_calm[calm_mask.values] = True

    # D=362 variable
    qc_wind_variable[var_mask.values] = True

    # Text-parsed directions
    if n_to_parse > 0:
        for i in df.loc[to_parse].index:
            text = df.at[i, "AllWindDirections"]
            deg, method = text_lookup[text]

            if method == "variable":
                qc_wind_variable[i] = True
            elif method == "calm":
                qc_wind_calm[i] = True
            elif method in ("compass", "mean"):
                D_cleaned[i] = deg
                qc_direction_imputed[i] = True
            # nondirectional and None: leave as NaN

    # ── Step 5: Beaufort scale ──
    print("\n── Beaufort Scale ──")
    # Beaufort upper bounds in tenths of m/s
    bounds = np.array([3, 16, 34, 55, 80, 108, 139, 172, 208, 245, 285, 327])
    beaufort = np.full(n_total, np.nan)
    w_valid = W.notna()
    beaufort[w_valid.values] = np.searchsorted(bounds, W[w_valid].values, side="left")

    n_bf = np.isfinite(beaufort).sum()
    print(f"  Beaufort values assigned: {n_bf:,}")

    # Distribution
    bf_ints = beaufort[np.isfinite(beaufort)].astype(int)
    for bf_val in range(13):
        count = (bf_ints == bf_val).sum()
        if count > 0:
            print(f"    BF{bf_val}: {count:,}")

    # ── Step 6: Wind vector components ──
    print("\n── Wind Vector Components ──")
    speed_ms = W.values / 10.0  # tenths m/s → m/s
    D_rad = np.radians(D_cleaned)
    has_both = np.isfinite(speed_ms) & np.isfinite(D_cleaned)
    u_wind = np.where(has_both, -speed_ms * np.sin(D_rad), np.nan)
    v_wind = np.where(has_both, -speed_ms * np.cos(D_rad), np.nan)

    n_vec = has_both.sum()
    print(f"  Wind vectors computed: {n_vec:,}")
    u_finite = u_wind[np.isfinite(u_wind)]
    v_finite = v_wind[np.isfinite(v_wind)]
    if len(u_finite) > 0:
        print(f"  u_wind range: [{u_finite.min():.2f}, {u_finite.max():.2f}] m/s")
        print(f"  v_wind range: [{v_finite.min():.2f}, {v_finite.max():.2f}] m/s")

    # ── Step 7: Write to database via batch UPDATEs ──
    print("\n── Saving to database ──")

    # Get rowids
    rowids = df["rowid"].values

    # Drop stale temp table if exists
    conn.execute("DROP TABLE IF EXISTS _phase2_tmp")

    # Use a temp table approach: write results to temp table, then UPDATE join
    # This is much faster than row-by-row UPDATEs
    results = pd.DataFrame({
        "_rowid": rowids,
        "D_cleaned": D_cleaned,
        "beaufort": beaufort,
        "u_wind": u_wind,
        "v_wind": v_wind,
        "qc_wind_calm": qc_wind_calm.astype(int),
        "qc_wind_variable": qc_wind_variable.astype(int),
        "qc_direction_imputed": qc_direction_imputed.astype(int),
    })

    print("  Writing temp table ...")
    results.to_sql("_phase2_results", conn, index=False, if_exists="replace")

    print("  Updating observations table ...")
    conn.execute("""
        UPDATE observations
        SET D_cleaned = (SELECT D_cleaned FROM _phase2_results WHERE _phase2_results._rowid = observations.rowid),
            beaufort = (SELECT beaufort FROM _phase2_results WHERE _phase2_results._rowid = observations.rowid),
            u_wind = (SELECT u_wind FROM _phase2_results WHERE _phase2_results._rowid = observations.rowid),
            v_wind = (SELECT v_wind FROM _phase2_results WHERE _phase2_results._rowid = observations.rowid),
            qc_wind_calm = (SELECT qc_wind_calm FROM _phase2_results WHERE _phase2_results._rowid = observations.rowid),
            qc_wind_variable = (SELECT qc_wind_variable FROM _phase2_results WHERE _phase2_results._rowid = observations.rowid),
            qc_direction_imputed = (SELECT qc_direction_imputed FROM _phase2_results WHERE _phase2_results._rowid = observations.rowid)
    """)
    conn.commit()

    # Verify
    print("  Verifying ...")
    for col in ["D_cleaned", "beaufort", "u_wind", "v_wind"]:
        row = conn.execute(f"SELECT COUNT(*) FROM observations WHERE {col} IS NOT NULL").fetchone()
        print(f"    {col}: {row[0]:,} non-null")
    for col in ["qc_wind_calm", "qc_wind_variable", "qc_direction_imputed"]:
        row = conn.execute(f"SELECT COUNT(*) FROM observations WHERE {col} = 1").fetchone()
        print(f"    {col}: {row[0]:,} flagged")

    # Create beaufort index
    conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_beaufort ON observations (beaufort)")

    # Clean up temp tables
    conn.execute("DROP TABLE IF EXISTS _phase2_results")
    conn.execute("DROP TABLE IF EXISTS _phase2_tmp")
    conn.commit()

    # Sample
    sample = pd.read_sql(
        "SELECT D, D_cleaned, beaufort, u_wind, v_wind, qc_wind_calm, qc_wind_variable "
        "FROM observations WHERE D_cleaned IS NOT NULL LIMIT 5", conn)
    print(f"\n  Sample:\n{sample.to_string()}")

    db_size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"\n  Database size: {db_size_mb:.1f} MB")

    # ── Summary ──
    n_with_d = int(conn.execute("SELECT COUNT(*) FROM observations WHERE D_cleaned IS NOT NULL").fetchone()[0])
    n_calm = int(conn.execute("SELECT COUNT(*) FROM observations WHERE qc_wind_calm = 1").fetchone()[0])
    n_variable = int(conn.execute("SELECT COUNT(*) FROM observations WHERE qc_wind_variable = 1").fetchone()[0])
    n_imputed = int(conn.execute("SELECT COUNT(*) FROM observations WHERE qc_direction_imputed = 1").fetchone()[0])
    n_no_dir = n_total - n_with_d - n_calm - n_variable

    print("\n" + "=" * 70)
    print("PHASE 2 SUMMARY")
    print("=" * 70)
    print(f"  Total records:        {n_total:,}")
    print(f"  With bearing:         {n_with_d:,} ({n_with_d/n_total*100:.1f}%)")
    print(f"  Calm (no direction):  {n_calm:,}")
    print(f"  Variable:             {n_variable:,}")
    print(f"  Imputed from text:    {n_imputed:,}")
    print(f"  No direction info:    {n_no_dir:,}")
    print(f"  With Beaufort:        {n_bf:,}")
    print(f"  With wind vectors:    {n_vec:,}")

    conn.close()
    print(f"\nPhase 2 complete. Database: {DB_PATH}")


if __name__ == "__main__":
    main()
