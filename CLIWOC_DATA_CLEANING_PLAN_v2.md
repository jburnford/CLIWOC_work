# CLIWOC Data Cleaning Plan

## Project Context

### The Research Project: "Sailors and Circulation"
- **Team**: Dagomar Degroot, Lucy Leonard, Matthew Toohey, Hunter Hughes, Mae Saslaw, Laurits Støvring Andreasen, Jim Clifford, Tripti Bhattacharya
- **Goal**: Publish in Nature/Science/PNAS on atmospheric circulation changes 1750-1855
- **Research plan**: `/home/jic823/climate/Sailors and Circulation Plan.md`
- **Current phase**: March-May 2026 — literature review, team meeting, extreme journey analysis
- **Environmental History article**: Already submitted (Dec 2025) — methodological piece on AI-assisted climate history
- **Key question**: How did atmospheric circulation (winds) change 1750-1855, and how did this affect ship journeys?

### Related Work
- **Kelly & Ó Gráda (2019)**: "Speed under Sail during the Early Industrial Revolution" — used same CLIWOC data to show British ships got ~50% faster 1750-1830 due to copper hulls and rigging improvements. Published in *Economic History Review*.
- **Chris Hay (IBM)**: Built an MCP server for maritime archives including CLIWOC (47 tools). YouTube video (Feb 2026) shows AI autonomously designing experiments with the data. Repo cloned at `/home/jic823/climate/chuk-mcp-maritime-archives/`.
- **Dagomar's existing analysis**: CSVs in `/home/jic823/climate/DagomarDatasets/Datasets/` show annual wind velocity trends correlated with NAO, ENSO. Used raw W column averaged per year.

### Data Source
- **CLIWOC 2.1**: 287,116 ship logbook records (1662-1855) from Dutch (44%), British (33%), Spanish (19%), French (4%) ships
- **Raw file**: `/home/jic823/climate/CLIWOC21.tsv` (160 MB, tab-separated)
- **Documentation**: `/home/jic823/climate/DagomarDatasets/Datasets/CLIWOC Guide.pdf` and `CLIWOC Nautical Terms.pdf`

### Why This Cleaning Is Needed
Dagomar's existing analysis uses the raw W column (wind speed in tenths m/s) directly averaged per year — but the dataset has known quality issues that peer reviewers at top journals will scrutinize. This cleaning pipeline produces a defensible, reproducible, and documented cleaned dataset.

### Critical Finding: The Data Is Cleaner Than Expected

Investigation of the raw CLIWOC21.tsv reveals that the **original CLIWOC team already performed unit conversions**:
- **AT column**: Already in tenths of °C (value 267 = 26.7°C), regardless of AirThermReadingUnits
- **SLP column**: Already in tenths of hPa (value 10160 = 1016.0 hPa), regardless of AirPressureReadingUnits
- **W column**: Already in tenths of m/s, translated from Beaufort scale by CLIWOC team
- **D column**: Already in degrees (0-360), corrected for magnetic declination

The `AirThermReadingUnits` and `AirPressureReadingUnits` fields record the **original observer's unit** (provenance), not the column's current unit. This means Phases 2.1 and 2.2 of the original CLIWOC_CLEANING_PLAN.md (pressure/temperature unit conversion) are **unnecessary** — the conversion is already done.

### What Actually Needs Cleaning

| Issue | Records | Severity | Approach |
|-------|---------|----------|----------|
| Untranslated compound wind descriptions | 14,451 (5%) | HIGH | LLM-assisted translation |
| Wind direction edge cases (D > 360, missing) | ~12,500 | MEDIUM | Rule-based normalization |
| Pressure/temperature outliers | ~50 | LOW | Flag and remove |
| Julian calendar dates | 4,663 (1.6%) | LOW | Arithmetic conversion |
| Potential duplicates | ~2,231 (0.8%) | LOW | Flag, don't delete |
| Weather descriptions (multilingual) | 29,070 distinct values | MEDIUM | LLM-assisted classification |
| Sea state descriptions (multilingual) | 8,257 distinct values | MEDIUM | LLM-assisted classification |

## Output Files

All outputs go to `/home/jic823/climate/cleaned/`:

### Primary Database
1. **`cliwoc_cleaned.db`** — SQLite database (primary format)
   - Table `observations`: All 287,116 records with original + cleaned columns
   - Table `wind_translations`: LLM translation audit trail (term → Beaufort, confidence, reasoning)
   - Table `weather_classifications`: Weather description → category mappings
   - Table `sea_state_classifications`: Sea state → Douglas scale mappings
   - Table `quality_summary`: Per-column quality statistics
   - Indexed on: year, nationality, grid_cell, ship_name, beaufort

### Export Formats
2. **`cliwoc_cleaned.parquet`** — Parquet export for pandas/R dataframe workflows
3. **`cliwoc_wind_timeseries.parquet`** — Aggregated wind data by month/year/grid

### Reference Data (JSON — small, auditable, human-readable)
4. **`wind_term_translations.json`** — All LLM-assisted term translations with confidence + reasoning
5. **`weather_classifications.json`** — Weather description → category mappings
6. **`sea_state_classifications.json`** — Sea state → Douglas scale mappings

### Documentation
7. **`quality_report.md`** — Data quality summary with statistics

## Implementation

### Phase 1: Foundation — Load, Validate, Calendar Fix
**File**: `scripts/01_foundation.py` + `notebooks/01_foundation.ipynb`

**Tasks**:
1. Load CLIWOC21.tsv with pandas (tab-separated, 287,116 rows) into SQLite as `observations` table
2. Verify AT is tenths °C: spot-check values across AirThermReadingUnits types
3. Verify SLP is tenths hPa: spot-check values across AirPressureReadingUnits types
4. Convert Julian → Gregorian for 4,663 British records (pre-1752): add +11 days
5. Create `date_iso` column (YYYY-MM-DD, Gregorian)
6. Create `decimal_year` column for time series
7. Flag ~2,231 potential duplicates (same date + lat + lon + ship) as `qc_duplicate=True`
8. Create `AT_celsius` (= AT / 10), `SLP_hPa` (= SLP / 10) convenience columns
9. Flag outliers: SLP < 870 hPa or > 1084 hPa; AT < -40°C or > 50°C
10. Save intermediate checkpoint

**Key columns created**: `date_iso`, `decimal_year`, `AT_celsius`, `SLP_hPa`, `qc_duplicate`, `qc_temp_outlier`, `qc_pressure_outlier`, `qc_calendar_converted`

### Phase 2: Wind Direction Cleaning
**File**: `scripts/02_wind_direction.py` + `notebooks/02_wind_direction.ipynb`

**Tasks**:
1. Normalize D values > 360: map 361 → "calm" flag, 362 → "variable" flag, others → D mod 360
2. Parse AllWindDirections text for records missing D:
   - Build compass point → degree dictionary (N=0, NNE=22.5, NE=45, ... including Dutch: N=0, NNO=22.5, NO=45, O=90, ZO=135, Z=180, ZW=225, W=270, NW=315)
   - Handle compound directions ("SBE" → 168.75°, "SEBE" → 157.5°)
   - For multi-part directions ("E, EBN, ENE"), take the mean
3. Create `D_cleaned` column (0-360 or NaN)
4. Create `qc_wind_calm` and `qc_wind_variable` flags
5. Compute wind vector components: `u_wind = -W/10 * sin(D_rad)`, `v_wind = -W/10 * cos(D_rad)`
6. Create `beaufort` column from W: map W ranges → integer 0-12

**Key columns created**: `D_cleaned`, `beaufort`, `u_wind`, `v_wind`, `qc_wind_calm`, `qc_wind_variable`, `qc_direction_imputed`

### Phase 3: Wind Force Translation (LLM-Assisted)
**File**: `scripts/03_wind_force_llm.py` + `notebooks/03_wind_force_translation.ipynb`

This is the hardest phase. 14,451 records have AllWindForces text but no W value.

**Step 3.1: Build base dictionary**
- Extract all known term → Beaufort mappings from the CLIWOC Nautical Terms PDF
- Includes English, Dutch, Spanish, French terms
- Source: `/home/jic823/climate/DagomarDatasets/Datasets/CLIWOC Nautical Terms.pdf`
- Store as `wind_term_dictionary.json`

**Step 3.2: Classify the 14,451 untranslated records**
- Extract unique AllWindForces values from untranslated records
- Group by pattern type:
  - **Simple untranslated** (single term, just not in CLIWOC dictionary): e.g., "LIGHT WINDS"
  - **Compound temporal** (multi-period): e.g., "FIRST PART MODERATE, LATTER FRESH GALES"
  - **Condition modifiers** (qualitative): e.g., "SQUALLY", "VARIABLE", "GUSTY"
  - **Dutch sail-based** (specific VOC terminology): e.g., "BRAMZEILSKOELTE EN MINDERE KOELTE"

**Step 3.3: LLM-assisted translation**
- For each unique AllWindForces term (not each record — deduplicate first):
  - Send term + CLIWOC Nautical Terms context to Claude
  - Request: Beaufort force estimate, confidence level (high/medium/low), reasoning
  - For compound descriptions: request representative single Beaufort value (weighted average or dominant period)
- Store all translations in `wind_term_translations.json` with full audit trail
- **Human review**: Flag all low-confidence translations for team review

**Step 3.4: Apply translations**
- Create `W_corrected` column: original W where available, LLM-translated value where not
- Create `beaufort_corrected` column
- Create `qc_wind_llm_translated` flag (True for LLM-filled records)
- Create `qc_wind_confidence` column (high/medium/low)

**Key columns created**: `W_corrected`, `beaufort_corrected`, `qc_wind_llm_translated`, `qc_wind_confidence`

**Important**: There are ~35,074 unique AllWindForces values total, but only a few thousand unique values among the 14,451 untranslated records. The LLM only needs to translate unique terms, not all 14,451 records individually.

#### Phase 3 Results (completed Feb 2026)

**Translation approach** (three-layer, no external API calls — Claude translated inline):
1. **Direct dictionary lookup**: 30,495 terms from DB existing translations + 330 from CLIWOC PDF
2. **Compound temporal parsing**: Strip prefixes ("PM", "FIRST PART", "LATTER"), extract base wind terms, average Beaufort values across parts
3. **Substring/pattern matching**: Find known terms embedded in longer descriptions

**Results (14,450 records, 4,768 unique terms)**:
- **10,477 records (72.5%)** received a Beaufort value
  - 7,003 high confidence (direct dictionary match)
  - 3,773 medium confidence (compound parsing, pattern match)
  - 2,330 low confidence (substring match in longer descriptions — flagged for team review)
- **2,629 records (18.2%)** correctly identified as NDA — terms like "VARIABLE", "SQUALLY", "ONGESTADIG" that describe wind character, not force (per CLIWOC PDF: "no definition available")
- **1,344 records (9.3%)** from 689 unique terms left unmatched

**Decision: leave 689 unmatched terms for now.** Rationale:
- They represent only 1,344 records (0.5% of all 287,113 observations) — negligible impact on trends
- Most are squall-only temporal markers ("LATTER SQUALLY", "PM SQUALLY", "AM SQUALLY") that are legitimately NDA — they describe a weather *condition* during a watch period, not a wind *force*
- The remaining ~200 are rare multilingual terms with ≤10 occurrences each (e.g., "HANDZAAM WEER", "ACHUBASCADO", "TEMS A PERR")
- All 689 are documented in `cleaned/wind_term_translations.json` with `"method": "unmatched"` for future review by the team
- If needed, a second pass can target these specifically — the JSON audit trail makes it trivial to re-process

**Net effect**: W_corrected covers 255,029 records (88.8%) vs original W covering 244,552 (85.2%), a gain of +10,477 records (+3.6pp)

### Phase 4: Weather & Sea State Classification (LLM-Assisted)
**File**: `scripts/04_weather_seastate.py` + `notebooks/04_weather_seastate.ipynb`

**Step 4.1: Weather classification**
- 29,070 distinct weather descriptions in Dutch, Spanish, French, English
- Extract unique values, deduplicate near-duplicates
- LLM-classify each into standardized categories:
  - CLEAR, FAIR, CLOUDY, OVERCAST, RAIN, DRIZZLE, SHOWERS, SQUALL, STORM, FOG, HAZE, SNOW, THUNDER, MIXED
- Handle coded values (W00, W01, W10, Z00-Z07, K, D) — investigate whether these are CLIWOC internal codes
- Store mappings in `weather_classifications.json`
- Create `weather_category` column

**Step 4.2: Sea state classification**
- 8,257 distinct descriptions
- Map to WMO Douglas Sea Scale (0-9):
  - 0: Calm (glassy) — LLANA, CALMA
  - 1: Calm (rippled) — BELLA, BELLE
  - 2: Smooth — SMOOTH WATER
  - 3: Slight — ALGO PICADA
  - 4: Moderate — PICADA
  - 5: Rough — GRUESA, GROSSE
  - 6-9: Very rough to phenomenal
- Handle coded values (Z01, Z02, etc.)
- Store mappings in `sea_state_classifications.json`
- Create `sea_state` column (integer 0-9)

**Key columns created**: `weather_category`, `sea_state`

#### Phase 4 Results (completed Feb 22-23 2026)

**Implementation**: `scripts/04_weather_seastate.py` (classification logic + JSON generation) + `scripts/04b_apply_classifications.py` (efficient bulk DB update) + `scripts/04c_extend_classifications.py` (extended dictionaries)

**Technical note**: The original `04_weather_seastate.py` stalled during the DB update phase — it ran ~37K individual `UPDATE ... WHERE Weather = ?` statements, each scanning 287K rows, producing a 125MB journal file. Fixed by switching to temp table + single bulk UPDATE approach in `04b` and `04c`.

**Classification approach** (four layers, same as Phase 3):
1. **CLIWOC coded values**: W00, W01, W10, etc. (weather) and Z00-Z09 (sea state)
2. **Multilingual dictionary lookup**: English, Dutch, Spanish, French terms → category
3. **Regex pattern matching**: Keywords within compound descriptions
4. **Compound splitting**: Split on delimiters, classify parts, pick most severe (weather) or average (sea state)

**Extended dictionaries** (Phase 4c): Added ~150 additional terms identified from top unmatched:
- Spanish horizon descriptions: "HORIZONTES PARDOS" → CLOUDY, "ACHUBASCADOS" → SHOWERS, "ATURBONADOS" → SQUALL, etc.
- Dutch trade wind terms: "PASSAAT" → FAIR, "BUIJIG" → SHOWERS, "STORMWEER" → STORM
- French terms: "PAR GRAINS" → SHOWERS, "NÉBULEUX" → CLOUDY
- Pattern sweep: 2,342 Spanish "HORIZONTES..." variants auto-classified via regex

**Weather classification results (89,793 records with text, 29,070 unique terms)**:
- **66,483 records (74.0%)** classified into 14 categories
  - FAIR: 32,331 | CLOUDY: 10,072 | CLEAR: 9,464 | SHOWERS: 3,378
  - THUNDER: 3,145 | FOG: 2,799 | SQUALL: 2,216 | HAZE: 753
  - STORM: 667 | MIXED: 613 | RAIN: 569 | OVERCAST: 268 | SNOW: 143 | DRIZZLE: 65
- **23,310 records (26.0%)** unmatched — thousands of rare compound descriptions (max 55 occurrences each)

**Sea state classification results (59,851 records with text, 8,257 unique terms)**:
- **50,368 records (84.2%)** classified to Douglas Scale 0-9
  - 1 (Calm/rippled): 19,935 | 4 (Moderate): 11,162 | 5 (Rough): 10,635
  - 3 (Slight): 6,508 | 6 (Very rough): 1,169 | 0 (Calm/glassy): 488
  - 2 (Smooth): 382 | 7 (High): 88 | 8 (Very high): 1
- **9,483 records (15.8%)** unmatched — rare compound descriptions

**Decision: accept current coverage and move to Phase 5.** Rationale:
- Weather 74% and sea state 84.2% classification rates are good for these highly variable multilingual free-text fields
- Remaining unmatched terms are all <55 occurrences — mostly rare compound temporal descriptions, archaic spellings, and terms mixing weather with navigational observations
- Weather and sea state are secondary variables for the core research question (wind/circulation changes) — they provide context but aren't the primary analysis target
- All 29,070 weather and 8,257 sea state term classifications are documented in JSON audit trails (`weather_classifications.json`, `sea_state_classifications.json`) for team review and future extension
- Diminishing returns: adding more terms would require manual review of thousands of rare descriptions for minimal gain

### Phase 5: Derived Variables & Spatial Binning
**File**: `scripts/05_derived.py` + `notebooks/05_derived.ipynb`

**Tasks**:
1. **Spatial binning**: Create `grid_5x5` column (5° × 5° lat/lon cell identifier)
2. **Hemisphere**: Create `hemisphere` column (N/S)
3. **Ocean basin**: Create `ocean_basin` column (Atlantic, Indian, Pacific, etc.) based on lat/lon
4. **Season**: Create `season` column (DJF/MAM/JJA/SON based on hemisphere)
5. **Wind speed midpoint correction**: Create `W_midpoint` using Beaufort midpoint values instead of CLIWOC upper-range values (for sensitivity analysis)

**Key columns created**: `grid_5x5`, `hemisphere`, `ocean_basin`, `season`, `W_midpoint`

#### Phase 5 Results (completed Feb 23 2026)

**Implementation**: `scripts/05_derived.py` — all operations via SQL (UDFs for ocean basin/season classification) to avoid loading full table into memory.

**Coverage**: 260,638 records (90.8%) received spatial/temporal binning — limited by lat/lon availability (26,475 records lack coordinates).

**Spatial distribution**:
- Atlantic: 189,361 (73%) | Indian: 58,212 (22%) | Pacific: 11,702 (4.5%)
- Arctic: 639 | Mediterranean: 591 | Southern: 133
- Northern hemisphere: 151,300 | Southern: 109,338
- Top grid cells: equatorial Atlantic (0°, -20°), Bay of Biscay (45°, -5°), mid-Atlantic (40°, -10°)

**Seasonal distribution**: DJF: 57,265 | MAM: 60,251 | JJA: 72,957 | SON: 70,165

**Sensitivity analysis**: W_midpoint (Beaufort midpoint) vs W_corrected (CLIWOC upper-range):
- Avg W_corrected/10 = 7.22 m/s vs Avg W_midpoint = 7.17 m/s — negligible difference (0.7%)
- This confirms that trends are robust to the choice of Beaufort-to-m/s mapping

### Phase 6: Validation & Output
**File**: `scripts/06_validate.py` + `notebooks/06_validation.ipynb`

**Tasks**:
1. **Reproduce Dagomar's trends**: Compute annual mean wind velocity from cleaned data, compare to `DagomarDatasets/Datasets/CLIWOC Average Annual Wind Velocity and Number of Observations.csv`
   - Should match closely (cleaned data adds ~5% more records but same core W values)
2. **Before/after comparisons**: Plot wind velocity, direction, pressure, temperature time series before and after cleaning
3. **Quality flag statistics**: How many records affected by each flag?
4. **Missing data patterns**: Visualize missingness by year, nationality, variable
5. **LLM translation audit**: Summary statistics of LLM confidence levels
6. **Generate aggregated outputs**:
   - `cliwoc_wind_timeseries.parquet`: Monthly/annual mean wind speed, direction, u/v components, by grid cell
   - `quality_report.md`: Full data quality documentation
7. **Export final outputs**:
   - Write all cleaned data to `cliwoc_cleaned.db` (SQLite) with indexes on year, nationality, grid_cell, ship_name, beaufort
   - Export `cliwoc_cleaned.parquet` for pandas/R workflows
   - Store LLM translation audit trails in `wind_translations` table + JSON

#### Phase 6 Results (completed Feb 23 2026)

**Implementation**: `scripts/06_validate_export.py` — validation via SQL aggregates, parquet export via chunked reads (50K rows/chunk) to avoid memory issues.

**Validation against Dagomar's published trends**:
- **PASS**: Annual mean wind velocity matches within **0.025% mean difference** (max 1.4%)
- 106 years compared (1750-1855), all nearly identical
- Observation count differences: our cleaned DB has ~396 more records/year on average (from additional records with LLM-filled wind values)
- W_corrected adds ~98 observations/year vs original W, with 0.61 tenths m/s mean difference

**Nationality breakdown**:
- Dutch: 126,402 (44%) — 1662-1855, avg W = 60.2 (lower due to sail-based terminology)
- British: 94,859 (33%) — 1750-1829, avg W = 85.2
- Spanish: 54,115 (19%) — 1675-1849, avg W = 80.4
- French: 10,631 (4%) — 1746-1837, avg W = 75.0
- Others: 1,106 (Swedish 700, American 276, Hamburg 68, Danish 62)

**Output files**:
| File | Size | Description |
|------|------|-------------|
| `cliwoc_cleaned.db` | 273 MB | SQLite with 2 tables, 14 indexes |
| `cliwoc_cleaned.parquet` | 10.3 MB | 46 analysis-ready columns |
| `cliwoc_wind_timeseries.parquet` | 1.9 MB | 75,819 monthly × grid cell aggregates |
| `quality_report.md` | 2.9 KB | Data quality summary |
| `wind_term_translations.json` | 996 KB | 4,768 wind term audit trail |
| `weather_classifications.json` | 7.6 MB | 29,070 weather term audit trail |
| `sea_state_classifications.json` | 1.4 MB | 8,257 sea state term audit trail |

## New Columns Summary

| Column | Type | Source |
|--------|------|--------|
| date_iso | str | Phase 1 |
| decimal_year | float | Phase 1 |
| AT_celsius | float | Phase 1 (AT / 10) |
| SLP_hPa | float | Phase 1 (SLP / 10) |
| D_cleaned | float | Phase 2 |
| beaufort | int | Phase 2 |
| u_wind | float | Phase 2 |
| v_wind | float | Phase 2 |
| W_corrected | float | Phase 3 |
| beaufort_corrected | int | Phase 3 |
| weather_category | str | Phase 4 |
| sea_state | int | Phase 4 |
| grid_5x5 | str | Phase 5 |
| hemisphere | str | Phase 5 |
| ocean_basin | str | Phase 5 |
| season | str | Phase 5 |
| W_midpoint | float | Phase 5 |
| qc_duplicate | bool | Phase 1 |
| qc_temp_outlier | bool | Phase 1 |
| qc_pressure_outlier | bool | Phase 1 |
| qc_calendar_converted | bool | Phase 1 |
| qc_wind_calm | bool | Phase 2 |
| qc_wind_variable | bool | Phase 2 |
| qc_direction_imputed | bool | Phase 2 |
| qc_wind_llm_translated | bool | Phase 3 |
| qc_wind_confidence | str | Phase 3 |

## Critical Files

| File | Purpose |
|------|---------|
| `/home/jic823/climate/CLIWOC21.tsv` | Raw input (287,116 records, 160 MB) |
| `/home/jic823/climate/CLIWOC_CLEANING_PLAN.md` | Original cleaning plan (to be superseded) |
| `/home/jic823/climate/DagomarDatasets/Datasets/CLIWOC Nautical Terms.pdf` | Multilingual wind term dictionary |
| `/home/jic823/climate/DagomarDatasets/Datasets/CLIWOC Guide.pdf` | Dataset documentation |
| `/home/jic823/climate/DagomarDatasets/Datasets/CLIWOC Average Annual Wind Velocity and Number of Observations.csv` | Dagomar's existing analysis (validation target) |
| `/home/jic823/climate/chuk-mcp-maritime-archives/src/chuk_mcp_maritime_archives/core/cliwoc_tracks.py` | Chris Hay's speed computation (reference) |

## Dependencies

```
pandas, numpy, pyarrow, jupyter, matplotlib, seaborn
```
(All standard — no exotic packages. SQLite via Python stdlib `sqlite3`. Parquet via `pyarrow`.)

## Verification

1. **Unit test**: Confirm AT/10 produces reasonable Celsius values across all AirThermReadingUnits types
2. **Unit test**: Confirm SLP/10 produces reasonable hPa values across all AirPressureReadingUnits types
3. **Regression test**: Cleaned annual wind means match Dagomar's published values within ±2%
4. **Audit**: Review all low-confidence LLM wind translations manually
5. **Sensitivity test**: Compare trends using W (original), W_corrected (with LLM fills), and W_midpoint (Beaufort midpoint) — trends should be robust across all three

## Data Investigation Findings (from Feb 21 2026 session)

These findings were established by direct analysis of the raw TSV and took significant effort. Do not re-investigate — build on these.

### Units Already Converted
- **AT column**: Values like 267, 278, 272 are tenths of °C (26.7°C, 27.8°C, 27.2°C). Confirmed by checking that FAHRENHEIT-labeled records cluster around tropical temperatures when divided by 10.
- **SLP column**: Values like 10160, 10126 are tenths of hPa (1016.0, 1012.6 hPa). Normal atmospheric range.
- **W column**: Values like 67, 93, 46, 123 are tenths of m/s. Map to Beaufort upper-midpoints (BF4=6.7, BF5=9.3, etc.)
- **AirThermReadingUnits / AirPressureReadingUnits**: Record the ORIGINAL observer's unit (provenance), NOT the column's current unit. The CLIWOC team already converted everything.

### Wind Data Statistics
- 287,116 total records
- 244,553 (85%) have numeric W values
- 14,451 (5%) have AllWindForces text but NO W value — these need LLM translation
- 258,987 (90%) have AllWindForces text
- 264,401 (92%) have numeric D (direction) values
- 35,074 unique AllWindForces values (!!) — includes Dutch, Spanish, French, English
- 38,207 unique AllWindDirections values
- Most common untranslated terms: VARIABLE (1,718), SQUALLY (1,038), compound temporal descriptions

### Wind Term Language Breakdown
- **Dutch (66K occurrences)**: BRAMZEILSKOELTE (34,022), MARSZEILSKOELTE (13,016), KOELTE variants
- **Spanish (35K)**: BONANCIBLE (8,933), FRESQUITO (7,599), FRESCO (7,312)
- **English (158K)**: MODERATE (10,395), FRESH BREEZES (7,273), FRESH GALES (4,311)
- **French (small)**: BON FRAIS (1,655), PETITE FRAIS (1,144)

### Compound Wind Descriptions (the hard problem)
- 15,293 records (5.9%) contain multi-period descriptions
- Examples: "FIRST PART MODERATE, LATTER FRESH GALES", "PM LIGHT WINDS", "FIRST PART FRESH GALES, MIDDLE AND LATTER SQUALLY"
- These are 24-hour observations split by watch period — can't simply regex parse
- Strategy: LLM interprets the compound term and assigns a representative single Beaufort value

### Direction Special Values
- D=361 means "calm" (no wind direction)
- D=362 means "variable" (shifting direction)
- Some D values slightly > 360 (362, 363) — normalize with mod 360
- Dutch compass system: N, NNO, NO, ONO, O, OZO, ZO, ZZO, Z, ZZW, ZW, WZW, W, WNW, NW, NNW

### Temperature & Pressure
- 81.9% of records have NO pressure data (only 51,935 with SLP)
- 80.8% have NO temperature data (only 55,006 with AT)
- ~50 outlier records with impossible values (SLP=135, SLP=11336)
- Temperature data is CLEAN when properly interpreted as tenths °C

### Calendar
- 4,663 Julian calendar records — all British ships pre-1752
- Add +11 days for 18th century Julian → Gregorian conversion
- 3 records with no calendar specified

### Duplicates
- ~2,231 duplicate records (0.78%) — same date + lat + lon + ship
- Mostly Spanish ships (DILIGENTE, PODEROSO) with slight weather description variations
- Flag but don't delete — may be legitimate multiple observations

### Weather & Sea State
- 29,070 distinct weather descriptions across 4 languages
- 8,257 distinct sea state descriptions
- Top weather: GOED WEER (8,622), MOOI WEER (7,859), FINE (1,860), BEAU TEMPS (1,777)
- Coded values exist: W00, W01, W10, Z00-Z07 — need investigation
- Top sea state: LLANA (8,998), PICADA (4,427), BELLA (3,500)

### Chris Hay's MCP Server Approach
- Uses WindScale field (Beaufort 0-12), not W (tenths m/s)
- Computes ship speed from haversine distance between positions, NOT from wind data
- Wind force is metadata only in speed calculations
- 47 tools including statistical tests (Mann-Whitney U, DiD) and wind rose analysis
- Public server at `https://maritime-archives.chukai.io/mcp`

### Dagomar's Analysis Method
- Simple annual mean of W column values → "Average Wind Velocity (tenths of m/s)"
- Uses CLIWOC's already-translated W field directly (no additional translation)
- Files in `DagomarDatasets/Datasets/`: wind + NAO, wind + ENSO, wind + observations, wind by quadrant
- Shows clear wind velocity decline ~1783-1830, partial recovery after 1830

### User Preferences (from this session)
- **Format**: SQLite (primary) + Parquet (export) — NOT CSV (corruption risk with messy text)
- **Scope**: Full clean of all variables (wind, pressure, temp, weather, sea state)
- **Wind translation approach**: LLM-assisted with human review
- **Output**: Jupyter notebooks for documentation, Python scripts for processing
