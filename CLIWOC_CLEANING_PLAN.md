# CLIWOC Dataset Cleaning and Improvement Plan for Climate History

## Overview

Clean and enhance the CLIWOC dataset (287,114 records, 1662-1855) to support Dagomar Degroot's climate history research on atmospheric circulation changes.

**Scope**: Comprehensive cleaning of all data quality issues identified.

## Key Data Quality Issues Identified

### 1. Untranslated Wind Forces (14,451 records)
- Records with `AllWindForces` but no numeric `W` value
- Terms like "VARIABLE" (1,718), "SQUALLY" (1,038), "LICHTE KOELTE" (466)
- Composite descriptions: "PM FRESH BREEZES", "FIRST PART MODERATE"

### 2. Wind Force Translation Bias
- CLIWOC uses upper-mid range of Beaufort scale values
- BF 4 (5.5-7.9 m/s) → translated as 6.7 m/s
- BF 5 (8.0-10.7 m/s) → translated as 9.3 m/s
- This systematic bias may affect trend analysis

### 3. Pressure Data (51,937 records) - Multiple Unit Systems
- Inches Mercury (29,978)
- Millimeters Mercury (9,695)
- Dutch systems: DLS12R, DLS1204R, RHINE INCH, etc.
- Values range 135-11,336 (clearly unconverted)

### 4. Temperature Data (55,007 records) - Multiple Scales
- Fahrenheit (52,579)
- Celsius (1,153)
- Réaumur (1,274) - old French scale: °Re × 1.25 = °C
- Not normalized to single scale

### 5. Calendar Systems
- Gregorian (282,450 records)
- Julian (4,663 records) - 11 days offset in 18th century
- Affects time series analysis

### 6. Weather/Sea State Descriptions - Untranslated
- Weather: 89,794 qualitative records in Dutch/Spanish/French/English
- Sea State: 59,851 qualitative records
- Valuable for precipitation/storm analysis but need standardization

### 7. Missing Wind Direction (36,411 records)
- Have wind force but no direction
- Limits atmospheric circulation analysis

### 8. Potential Duplicates
- ~10,169 records flagged as potential duplicates

---

## Implementation Plan

### Phase 1: Core Wind Data Improvements

#### Task 1.1: Translate Remaining Wind Force Terms
- **Input**: 14,451 records with `AllWindForces` but no `W`
- **Approach**:
  - Create Beaufort translation dictionary from CLIWOC documentation
  - Handle multi-part descriptions (e.g., "PM FRESH BREEZES" → use afternoon value)
  - Flag "VARIABLE" and "SQUALLY" as special conditions
- **Output**: `W_corrected` column with Beaufort values (0-12)

#### Task 1.2: Recalculate Wind Force Using Beaufort Midpoints
- **Issue**: Current translations biased toward upper range
- **Approach**: Apply Beaufort midpoint values instead:
  - BF 4: 6.7 m/s → 6.7 m/s (OK)
  - BF 5: 9.3 m/s → 9.4 m/s (minor)
  - BF 6: 12.3 m/s → 12.3 m/s (OK)
- **Output**: `W_midpoint` column for comparison analysis

#### Task 1.3: Add Beaufort Scale Column
- **Output**: `beaufort` column (integer 0-12) for easier analysis
- Standardizes across all wind force representations

### Phase 2: Pressure and Temperature Normalization

#### Task 2.1: Normalize Pressure to Hectopascals
- Convert all pressure readings to hPa/mb:
  - Inches Hg × 33.8639 = hPa
  - mm Hg × 1.33322 = hPa
  - Dutch systems: Research historical conversion factors
- **Output**: `SLP_hPa` column

#### Task 2.2: Normalize Temperature to Celsius
- Convert all temperature readings:
  - (°F - 32) × 5/9 = °C
  - °Ré × 1.25 = °C
- **Output**: `AT_celsius` column

### Phase 3: Calendar and Temporal Standardization

#### Task 3.1: Convert Julian to Gregorian Dates
- Add appropriate offset based on century:
  - 18th century: +11 days
  - 19th century: +12 days
- **Output**: `date_gregorian` column (ISO format)

#### Task 3.2: Add Decimal Year Column
- For time series analysis: `decimal_year` = year + (day_of_year / 365.25)

### Phase 4: Weather Classification

#### Task 4.1: Standardize Weather Descriptions
Create lookup table for weather categories:
- **Clear/Fair**: GOED WEER, MOOI WEER, BEAU TEMPS, FINE, FAIR
- **Cloudy**: CLOUDY, COUVERT, BUIIGE LUCHT
- **Precipitation**: Linked to Rain/Snow flags
- **Stormy**: SQUALLY, UNSETTLED, storm terms
- **Output**: `weather_category` column (standardized English)

#### Task 4.2: Standardize Sea State Descriptions
Map to WMO Douglas Sea Scale (0-9):
- LLANA/SMOOTH = 0-1 (Calm)
- BELLA/BELLE = 1-2 (Smooth)
- PICADA = 3-4 (Slight-Moderate)
- GRUESA/GROSSE = 5-6 (Rough)
- **Output**: `sea_state` column (0-9)

### Phase 5: Data Quality Flags

#### Task 5.1: Add Quality Control Flags
- `qc_duplicate`: Potential duplicate record
- `qc_wind_variable`: Wind marked as variable
- `qc_wind_squally`: Gusty conditions
- `qc_pressure_converted`: Pressure unit converted
- `qc_temp_converted`: Temperature scale converted
- `qc_calendar_converted`: Julian→Gregorian conversion

#### Task 5.2: Remove/Flag Duplicates
- Identify true duplicates vs. multiple observations same day
- Flag rather than delete (preserve provenance)

### Phase 6: Derived Variables for Climate Analysis

#### Task 6.1: Wind Vector Components
- `u_wind`: Zonal (east-west) component = -speed × sin(direction)
- `v_wind`: Meridional (north-south) component = -speed × cos(direction)
- Essential for atmospheric circulation analysis

#### Task 6.2: Spatial Binning
- Add grid cell identifiers (e.g., 5° × 5° lat/lon)
- `grid_cell`: For aggregating observations

#### Task 6.3: Climate Indices Preparation
- Add columns for linking to:
  - `nao_index`: North Atlantic Oscillation (external dataset)
  - `volcanic_forcing`: Major eruption dates (external dataset)

---

## Output Files

1. **`CLIWOC21_cleaned.csv`** - Full cleaned dataset
2. **`CLIWOC21_wind_timeseries.csv`** - Aggregated wind data by month/year
3. **`CLIWOC21_translation_dictionary.json`** - All term translations
4. **`CLIWOC21_quality_report.md`** - Data quality summary

---

## Critical Files

- **Input**: `/home/jic823/climate/CLIWOC21.tsv`
- **Output**: `/home/jic823/climate/CLIWOC21_cleaned.csv`
- **Scripts**: `/home/jic823/climate/scripts/` (new directory)

---

## Verification Plan

1. **Wind force validation**: Compare translated values to existing `W` column
2. **Temporal consistency**: Plot time series before/after cleaning
3. **Unit conversion verification**: Spot-check pressure/temperature conversions
4. **Duplicate detection**: Review flagged duplicates manually (sample)
5. **Comparison with Dagomar's results**: Reproduce wind speed decline 1780-1830

---

## External Data Integration (Future)

For comprehensive climate analysis, merge with:
- **Trans-Atlantic Slave Trade Database** (slavevoyages.org)
- **NAO reconstruction** (paleoclimate proxies)
- **Volcanic Forcing Index** (eruption dates/magnitude)
- **ICOADS** (modern marine climate data for calibration)

---

## Column Reference

### Key Original Columns
| Column | Description |
|--------|-------------|
| YR, MO, DY, HR | Date/time components |
| LAT, LON | Position (IMMA format) |
| latitude, longitude | Position (decimal degrees) |
| D | Wind direction (degrees) |
| W | Wind speed (m/s, translated) |
| SLP | Sea level pressure |
| AT | Air temperature |
| Calendar | Gregorian or Julian |
| AirPressureReadingUnits | Pressure unit system |
| AirThermReadingUnits | Temperature scale |
| AllWindForces | Original wind description |
| AllWindDirections | Original wind direction text |
| Weather | Weather description |
| StateSea | Sea state description |

### New Columns to Create
| Column | Description |
|--------|-------------|
| W_corrected | Wind speed with translations fixed |
| W_midpoint | Wind speed using Beaufort midpoints |
| beaufort | Beaufort scale (0-12) |
| SLP_hPa | Pressure in hectopascals |
| AT_celsius | Temperature in Celsius |
| date_gregorian | ISO date (all Gregorian) |
| decimal_year | Year as decimal for time series |
| weather_category | Standardized weather category |
| sea_state | Douglas Sea Scale (0-9) |
| u_wind | Zonal wind component |
| v_wind | Meridional wind component |
| grid_cell | 5° × 5° spatial bin |
| qc_* | Quality control flags |
