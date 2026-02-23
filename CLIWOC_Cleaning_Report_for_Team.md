# CLIWOC Data Cleaning Report

**Prepared for**: Dagomar Degroot and the "Sailors and Circulation" team
**Date**: February 23, 2026
**Prepared by**: Jim Clifford, with AI-assisted processing (Claude)

## Summary

We have completed a full cleaning pipeline for the CLIWOC 2.1 dataset (287,113 ship logbook records, 1662-1855). The cleaned data is available as a SQLite database and Parquet files, with all transformations documented and auditable.

**Key result**: Our cleaned annual wind velocity trends reproduce your existing published values within **0.025% mean difference** across all 106 years (1750-1855). The cleaning adds 10,477 previously untranslated wind force records (+3.6 percentage points of coverage) without altering the core trends.

## What Was Done

### Phase 1: Foundation
- Loaded all 287,113 records into a structured SQLite database
- Confirmed that the CLIWOC team already converted AT to tenths of degrees Celsius and SLP to tenths of hPa (the unit columns record provenance only, not the current units)
- Converted 4,663 Julian calendar dates (British ships pre-1752) to Gregorian
- Flagged 4,376 potential duplicate records (same date + lat/lon + ship) — not deleted, just flagged
- Created convenience columns: `AT_celsius`, `SLP_hPa`, `date_iso`, `decimal_year`

### Phase 2: Wind Direction
- Cleaned the D (direction) column: normalized special values (361 = calm, 362 = variable)
- Parsed multilingual compass text (English, Dutch, Spanish, French) for 448 records missing numeric direction
- Computed meteorological wind vector components (u_wind, v_wind) for all records with both direction and speed
- Mapped wind speed to integer Beaufort scale (0-12)

### Phase 3: Wind Force Translation (the main contribution)
The original CLIWOC team translated most wind force descriptions to a numeric W value (tenths of m/s), but **14,450 records (5%)** had text descriptions in the `AllWindForces` field with no corresponding W value. We translated these using a three-layer approach:

1. **Dictionary lookup** against the CLIWOC Nautical Terms PDF (330 terms) plus 30,495 terms already translated elsewhere in the database
2. **Compound parsing** for multi-period descriptions (e.g., "FIRST PART MODERATE, LATTER FRESH GALES" — average the component Beaufort values)
3. **Pattern matching** for terms embedded in longer descriptions

**Results**:
- 10,477 records (72.5%) received a Beaufort value
  - 7,003 high confidence (direct dictionary match)
  - 3,773 medium confidence (compound parsing)
  - **2,330 low confidence (substring matching) — flagged for team review**
- 2,629 records correctly identified as NDA (e.g., "VARIABLE", "SQUALLY" — these describe wind character, not force)
- 1,344 records (689 unique terms) left unmatched — mostly rare squall descriptions

**Net effect**: Wind speed coverage increased from 244,552 records (85.2%) to 255,029 (88.8%).

### Phase 4: Weather and Sea State Classification
- Classified 29,070 unique multilingual weather descriptions into 14 standardized categories (CLEAR, FAIR, CLOUDY, OVERCAST, RAIN, DRIZZLE, SHOWERS, SQUALL, STORM, FOG, HAZE, SNOW, THUNDER, MIXED)
- Classified 8,257 unique sea state descriptions to the Douglas Sea Scale (0-9)
- Included Spanish horizon terms ("HORIZONTES ACHUBASCADOS" = SHOWERS), Dutch trade wind terms ("PASSAAT" = FAIR), and French terminology

**Coverage**: 66,483 / 89,793 weather records classified (74.0%); 50,368 / 59,851 sea state records classified (84.2%)

### Phase 5: Derived Variables
- Assigned 5-degree latitude/longitude grid cells for spatial analysis
- Classified ocean basin (Atlantic 73%, Indian 22%, Pacific 4.5%)
- Computed hemisphere-adjusted meteorological seasons
- Created alternative wind speed variable (`W_midpoint`) using Beaufort scale midpoints instead of upper-range values, for sensitivity analysis. Result: negligible difference (7.17 vs 7.22 m/s mean), confirming trends are robust.

### Phase 6: Validation and Export
- Reproduced your published annual mean wind velocity values — **match within 0.025%**
- Exported cleaned Parquet files for analysis
- Generated quality report and full audit trails for all translations

## Wind Velocity Trends: Before and After

The cleaning does not alter the core signal. Decade averages (tenths of m/s):

| Decade | Records | Avg W (original) | Avg W (cleaned) | Added records |
|--------|---------|-------------------|-----------------|---------------|
| 1750s  | 24,204  | 80.4              | 80.6            | +1,067        |
| 1760s  | 31,007  | 83.3              | 83.0            | +1,185        |
| 1770s  | 48,162  | 79.5              | 78.9            | +1,422        |
| 1780s  | 34,995  | 73.0              | 72.7            | +1,352        |
| 1790s  | 31,997  | 70.6              | 70.5            | +1,914        |
| 1800s  | 19,150  | 69.2              | 68.9            | +1,224        |
| 1810s  | 8,615   | 60.0              | 59.6            | +436          |
| 1820s  | 14,695  | 54.7              | 54.6            | +545          |
| 1830s  | 20,483  | 66.3              | 66.0            | +345          |
| 1840s  | 34,820  | 67.2              | 66.8            | +503          |
| 1850s  | 17,847  | 71.5              | 70.6            | +426          |

The well-known decline from ~83 (1760s) to ~55 (1820s) and partial recovery to ~72 (1850s) is fully preserved.

## Where Human Review Is Needed

### 1. Low-Confidence Wind Translations (2,330 records, PRIORITY)

These records were translated by finding a known wind term embedded in a longer compound description. The extracted Beaufort value may not represent the full observation. Examples:

| Term | Assigned BF | Concern |
|------|-------------|---------|
| "'S AVONDS BRAMZEILSKOELTE" | 3 | Dutch evening temporal prefix — BF3 is probably correct |
| "'S AVONDS GEREEFDE MARSZEILSKOELTE" | 5 | Reefed topsail breeze — BF5 seems right |
| "'S MORGENS EEN LANDLUCHTJE" | 2 | "Morning land breeze" — BF2 may be too specific |
| "'S NACHTS SLAPPE KOELTE" | 1 | "Night slack breeze" — BF1 seems correct |

**Most of these Dutch temporal descriptions ('s avonds = evening, 's nachts = night) are correctly translated — the temporal prefix doesn't change the wind force.** But a quick review of the full list (in `wind_term_translations.json`, filter for `"confidence": "low"`) would be valuable.

### 2. Unmatched Wind Terms (1,344 records, 689 unique terms, LOW PRIORITY)

These could not be translated. They represent only 0.5% of all observations. The most common:

| Occurrences | Term | Notes |
|-------------|------|-------|
| 45 | "LATTER SQUALLY" | Describes conditions, not force — legitimately NDA |
| 25 | "MIDDLE SQUALLY" | Same |
| 19 | "HANDZAAM WEER" | Dutch: "manageable weather" — arguably NDA |
| 15 | "ACHUBASCADO" | Spanish: "squally" — arguably NDA |
| 15 | "MOYEN" | French: "moderate" — could be mapped to BF4 |
| 14 | "A RÁFRAGAS" | Spanish: "in gusts" — NDA |
| 12 | "TEMS A PERR" | French (archaic): possibly "temps à perre" |

**Recommendation**: Most of these are legitimately NDA (describe weather conditions, not quantifiable wind force). A few French and Spanish terms could potentially be mapped if a team member with language expertise reviews them.

### 3. Unmatched Weather Descriptions (23,310 records, LOW PRIORITY)

The remaining unclassified weather terms are all <55 occurrences each. Top examples:

| Occurrences | Term | Likely category |
|-------------|------|-----------------|
| 55 | "PM CLOUDY" | CLOUDY (temporal prefix) |
| 53 | "TOLDADO" | OVERCAST (Spanish: covered — variant spelling of "toldado") |
| 53 | "BRUMEAUX" | HAZE (French: misty/hazy — variant of "brumeux") |
| 49 | "TRAVATIGE LUCHT" | CLOUDY (Dutch: "changeable sky") |
| 49 | "DRIJVENDE LUCHT" | CLOUDY (Dutch: "drifting sky") |
| 47 | "HORIZONTES NUBADOS" | CLOUDY (Spanish: variant of "nublados") |
| 45 | "SERENE" | CLEAR (English/Italian) |

These are mostly archaic spellings and temporal compounds. They don't affect the core wind analysis.

### 4. Unmatched Sea State Descriptions (9,483 records, LOW PRIORITY)

| Occurrences | Term | Likely Douglas Scale |
|-------------|------|---------------------|
| 55 | "LARGE HEAD SEA" | 5 (rough, opposing) |
| 50 | "K" | Unknown code — needs investigation |
| 48 | "SWELL FROM THE SW" | 3 (slight — directional swell) |
| 47 | "MEDIANA DEL MISMO VIENTO" | 3-4 (Spanish: "moderate, from the same wind") |
| 44 | "AFSLECHTENDE ZEE" | 3 (Dutch: "decreasing sea") |
| 41 | "MODERADA" | 3 (Spanish: "moderate") |

### 5. Dutch Wind Speed Bias (IMPORTANT FOR ANALYSIS)

The average wind speed for Dutch records (60.2 tenths m/s) is significantly lower than British (85.2) and Spanish (80.4). This is because Dutch logbooks used sail-based terminology (BRAMZEILSKOELTE = "topgallant breeze" = BF3, MARSZEILSKOELTE = "topsail breeze" = BF4) which may systematically underestimate wind force compared to the Beaufort-calibrated terms used by British observers. **This nationality bias should be considered when analyzing temporal trends, since the Dutch contribution shifts over time (dominant before 1800, declining after).**

## Output Files

All outputs are in the `cleaned/` directory:

| File | Size | What it is |
|------|------|------------|
| `cliwoc_cleaned.db` | 273 MB | Full SQLite database — the primary deliverable. Query with any SQL tool. |
| `cliwoc_cleaned.parquet` | 10.3 MB | Same data as a Parquet file (46 key columns) — opens directly in pandas/R. |
| `cliwoc_wind_timeseries.parquet` | 1.9 MB | Pre-aggregated monthly wind data by 5-degree grid cell (75,819 rows). Ready for time series analysis. |
| `wind_term_translations.json` | 996 KB | Full audit trail: every wind term, its Beaufort translation, confidence level, and reasoning. |
| `weather_classifications.json` | 7.6 MB | Audit trail for all 29,070 weather descriptions. |
| `sea_state_classifications.json` | 1.4 MB | Audit trail for all 8,257 sea state descriptions. |
| `quality_report.md` | 2.9 KB | Summary statistics. |

## New Columns Added to the Dataset

| Column | Description | Coverage |
|--------|-------------|----------|
| `W_corrected` | Wind speed with LLM-filled gaps (tenths m/s) | 88.8% |
| `beaufort_corrected` | Integer Beaufort scale (0-12) with LLM fills | 88.8% |
| `W_midpoint` | Beaufort midpoint wind speed in m/s (for sensitivity tests) | 88.8% |
| `D_cleaned` | Wind direction, normalized (degrees, 0-360) | 92.2% |
| `u_wind`, `v_wind` | Zonal and meridional wind components (m/s) | 87.4% |
| `weather_category` | Standardized weather category (14 categories) | 23.2% |
| `sea_state` | Douglas Sea Scale (0-9) | 17.5% |
| `grid_5x5` | 5-degree lat/lon grid cell identifier | 90.8% |
| `ocean_basin` | Atlantic, Indian, Pacific, etc. | 90.8% |
| `hemisphere` | N or S | 90.8% |
| `season` | DJF/MAM/JJA/SON (hemisphere-adjusted) | 90.8% |
| `AT_celsius` | Air temperature in degrees Celsius | 19.2% |
| `SLP_hPa` | Sea level pressure in hPa | 18.1% |
| `date_iso` | ISO date string (YYYY-MM-DD) | 100% |
| `decimal_year` | Decimal year for time series | 100% |
| `qc_*` flags | 8 quality control flags | see report |

## Scripts

All processing scripts are in `scripts/` and can be re-run to reproduce the cleaned dataset from the raw CLIWOC21.tsv:

1. `01_foundation.py` — Load, validate, calendar conversion
2. `02_wind_direction.py` — Direction cleaning, compass parsing
3. `03_wind_force_llm.py` — Wind force translation (three-layer dictionary approach)
4. `04_weather_seastate.py` — Weather/sea state classification dictionaries
5. `04b_apply_classifications.py` — Efficient bulk database update
6. `04c_extend_classifications.py` — Extended multilingual dictionaries
7. `05_derived.py` — Spatial binning, ocean basins, seasons
8. `06_validate_export.py` — Validation against existing trends, Parquet export

## Next Steps

1. **Team review** of 2,330 low-confidence wind translations (see `wind_term_translations.json`)
2. **Discuss** the Dutch wind speed bias and whether nationality-specific adjustments are warranted
3. **Begin analysis** using the wind timeseries parquet or SQLite database
4. The dataset is ready for the extreme journey analysis planned for March-May 2026
