"""
Phase 4: Weather & Sea State Classification
CLIWOC Data Cleaning Pipeline for "Sailors and Circulation"

Classifies the free-text Weather and StateSea columns into standardized categories.
Uses three layers (same approach as Phase 3):
  1. CLIWOC coded values (W00, W01, Z01, etc.)
  2. Dictionary lookup (multilingual term → category)
  3. Pattern/substring matching for compound descriptions

Outputs:
  - weather_category column (CLEAR, FAIR, CLOUDY, OVERCAST, RAIN, DRIZZLE,
    SHOWERS, SQUALL, STORM, FOG, HAZE, SNOW, THUNDER, MIXED)
  - sea_state column (integer 0-9, Douglas Sea Scale)
  - weather_classifications.json — audit trail
  - sea_state_classifications.json — audit trail
"""

import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/jic823/climate")
OUT_DIR = BASE_DIR / "cleaned"
DB_PATH = OUT_DIR / "cliwoc_cleaned.db"
WEATHER_JSON = OUT_DIR / "weather_classifications.json"
SEA_STATE_JSON = OUT_DIR / "sea_state_classifications.json"

# ══════════════════════════════════════════════════════════════════════════════
# WEATHER CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

# Categories: CLEAR, FAIR, CLOUDY, OVERCAST, RAIN, DRIZZLE, SHOWERS,
#             SQUALL, STORM, FOG, HAZE, SNOW, THUNDER, MIXED

# ── CLIWOC coded values (W## codes found in Weather column) ────────────────
# These appear to be partial WMO present weather codes applied by CLIWOC team
WEATHER_CODES = {
    "W00": "CLEAR",      # No significant weather
    "W01": "FAIR",       # Clouds dissolving / improving
    "W02": "FAIR",       # State of sky unchanged
    "W03": "CLOUDY",     # Clouds forming
    "W10": "HAZE",       # Mist / haze
    "W20": "DRIZZLE",    # Drizzle
    "W21": "RAIN",       # Rain
    "W22": "SNOW",       # Snow
    "W23": "RAIN",       # Rain and snow mixed
    "W24": "RAIN",       # Freezing drizzle/rain
    "W25": "SHOWERS",    # Rain showers
    "W26": "SHOWERS",    # Snow showers
    "W27": "HAZE",       # Haze (dust/sand)
    "W28": "FOG",        # Fog
    "W29": "THUNDER",    # Thunderstorm
    "W30": "STORM",      # Dust/sand storm
    "W40": "FOG",        # Fog at distance
    "W50": "DRIZZLE",    # Drizzle (continuous)
    "W60": "RAIN",       # Rain (continuous)
    "W70": "SNOW",       # Snow (continuous)
    "W80": "SHOWERS",    # Rain showers
    "W90": "THUNDER",    # Thunderstorm
}

# ── Multilingual weather dictionaries ──────────────────────────────────────

# English weather terms → category
WEATHER_EN = {
    # CLEAR
    "CLEAR": "CLEAR", "CLEAR WEATHER": "CLEAR", "CLEAR SKY": "CLEAR",
    "FINE AND CLEAR": "CLEAR", "FINE CLEAR WEATHER": "CLEAR",
    "VERY CLEAR": "CLEAR",

    # FAIR
    "FAIR": "FAIR", "FAIR WEATHER": "FAIR", "FINE": "FAIR",
    "FINE WEATHER": "FAIR", "PLEASANT": "FAIR", "PLEASANT WEATHER": "FAIR",
    "MODERATE AND FAIR": "FAIR", "MODERATE WEATHER": "FAIR",
    "MODERATE AND PLEASANT": "FAIR", "MILD": "FAIR", "MILD WEATHER": "FAIR",
    "AGREEABLE WEATHER": "FAIR", "GOOD WEATHER": "FAIR",
    "SETTLED WEATHER": "FAIR",

    # CLOUDY
    "CLOUDY": "CLOUDY", "CLOUDY WEATHER": "CLOUDY",
    "CLOUDS": "CLOUDY", "DULL": "CLOUDY", "DULL WEATHER": "CLOUDY",
    "DARK": "CLOUDY", "DARK WEATHER": "CLOUDY", "GLOOMY": "CLOUDY",
    "GLOOMY WEATHER": "CLOUDY", "HEAVY CLOUDS": "CLOUDY",
    "THICK WEATHER": "CLOUDY", "THICK": "CLOUDY",
    "CLOSE WEATHER": "CLOUDY", "HAZY AND CLOUDY": "CLOUDY",

    # OVERCAST
    "OVERCAST": "OVERCAST", "OVERCAST SKY": "OVERCAST",
    "COMPLETELY OVERCAST": "OVERCAST",

    # RAIN
    "RAIN": "RAIN", "RAINY": "RAIN", "RAINY WEATHER": "RAIN",
    "HEAVY RAIN": "RAIN", "MUCH RAIN": "RAIN",
    "CONSTANT RAIN": "RAIN", "INCESSANT RAIN": "RAIN",
    "RAIN ALL DAY": "RAIN", "WET": "RAIN", "WET WEATHER": "RAIN",

    # DRIZZLE
    "DRIZZLE": "DRIZZLE", "DRIZZLY": "DRIZZLE",
    "DRIZZLING RAIN": "DRIZZLE", "SMALL RAIN": "DRIZZLE",
    "LIGHT RAIN": "DRIZZLE", "MIZZLE": "DRIZZLE",

    # SHOWERS
    "SHOWERS": "SHOWERS", "SHOWERY": "SHOWERS",
    "SHOWERY WEATHER": "SHOWERS", "RAIN SHOWERS": "SHOWERS",
    "PASSING SHOWERS": "SHOWERS", "OCCASIONAL SHOWERS": "SHOWERS",
    "HEAVY SHOWERS": "SHOWERS",

    # SQUALL
    "SQUALL": "SQUALL", "SQUALLS": "SQUALL", "SQUALLY": "SQUALL",
    "SQUALLY WEATHER": "SQUALL", "HARD SQUALLS": "SQUALL",
    "HEAVY SQUALLS": "SQUALL", "FREQUENT SQUALLS": "SQUALL",
    "VIOLENT SQUALLS": "SQUALL",

    # STORM
    "STORM": "STORM", "STORMY": "STORM", "STORMY WEATHER": "STORM",
    "TEMPEST": "STORM", "TEMPESTUOUS": "STORM",
    "HURRICANE": "STORM", "TYPHOON": "STORM",
    "GALE": "STORM", "HEAVY GALE": "STORM",

    # FOG
    "FOG": "FOG", "FOGGY": "FOG", "FOGGY WEATHER": "FOG",
    "THICK FOG": "FOG", "DENSE FOG": "FOG",
    "MISTY": "FOG", "MIST": "FOG",

    # HAZE
    "HAZE": "HAZE", "HAZY": "HAZE", "HAZY WEATHER": "HAZE",
    "HAZEY": "HAZE", "HAZEY WEATHER": "HAZE",

    # SNOW
    "SNOW": "SNOW", "SNOWY": "SNOW", "SNOWING": "SNOW",
    "HEAVY SNOW": "SNOW", "SLEET": "SNOW",

    # THUNDER
    "THUNDER": "THUNDER", "THUNDER AND LIGHTNING": "THUNDER",
    "THUNDERSTORM": "THUNDER", "LIGHTNING": "THUNDER",
    "THUNDER SQUALLS": "THUNDER", "THUNDER SHOWERS": "THUNDER",
}

# Dutch weather terms → category
WEATHER_NL = {
    # CLEAR
    "HELDER": "CLEAR", "HELDERE LUCHT": "CLEAR", "HELDER WEER": "CLEAR",
    "HELDER EN KLAAR": "CLEAR", "KLAAR": "CLEAR", "KLAAR WEER": "CLEAR",
    "KLARE LUCHT": "CLEAR",

    # FAIR
    "GOED WEER": "FAIR", "MOOI WEER": "FAIR", "SCHOON WEER": "FAIR",
    "GOED": "FAIR", "MOOI": "FAIR", "SCHOON": "FAIR",
    "AANGENAAM WEER": "FAIR", "FRAAI WEER": "FAIR", "FRAAI": "FAIR",
    "BEST WEER": "FAIR", "STIL WEER": "FAIR",

    # CLOUDY
    "BEWOLKT": "CLOUDY", "BEWOLKTE LUCHT": "CLOUDY",
    "BETROKKEN": "CLOUDY", "BETROKKEN LUCHT": "CLOUDY",
    "DONKER": "CLOUDY", "DONKERE LUCHT": "CLOUDY",
    "DIKKE LUCHT": "CLOUDY", "DICHTE LUCHT": "CLOUDY",
    "OVERDRIJVENDE LUCHT": "CLOUDY", "SOMBER": "CLOUDY",
    "SOMBERE LUCHT": "CLOUDY", "DAMPIG": "CLOUDY",
    "DAMPIGE LUCHT": "CLOUDY",

    # OVERCAST
    "LUCHT GEHEEL BETROKKEN": "OVERCAST",
    "GEHEEL BETROKKEN": "OVERCAST",
    "GEHEEL BEWOLKT": "OVERCAST",

    # RAIN
    "REGEN": "RAIN", "REGENACHTIG": "RAIN", "REGENACHTIG WEER": "RAIN",
    "VEEL REGEN": "RAIN", "HARD REGEN": "RAIN", "STORTBUIEN": "RAIN",

    # DRIZZLE
    "MOTREGEN": "DRIZZLE", "MOTTIG": "DRIZZLE",
    "MOTTIGE LUCHT": "DRIZZLE",

    # SHOWERS
    "BUIIG": "SHOWERS", "BUIIG WEER": "SHOWERS",
    "BUIIGE LUCHT": "SHOWERS", "REGENBUIEN": "SHOWERS",

    # SQUALL
    "BUIEN": "SQUALL", "ZWARE BUIEN": "SQUALL",
    "HARDE BUIEN": "SQUALL", "RUKWINDEN": "SQUALL",

    # STORM
    "STORM": "STORM", "STORMACHTIG": "STORM",
    "STORMACHTIG WEER": "STORM", "ORKAAN": "STORM",
    "ONWEER": "STORM",

    # FOG
    "MIST": "FOG", "MISTIG": "FOG", "MISTIGE LUCHT": "FOG",
    "DICHTE MIST": "FOG", "DIKKE MIST": "FOG",
    "NEVEL": "FOG", "NEVELIG": "FOG",

    # HAZE
    "HEIIG": "HAZE", "HEIIGE LUCHT": "HAZE",
    "NEVELACHTIG": "HAZE", "WAZIG": "HAZE",

    # SNOW
    "SNEEUW": "SNOW", "SNEEUWEN": "SNOW", "SNEEUWIG": "SNOW",
    "HAGEL": "SNOW",

    # THUNDER
    "DONDER": "THUNDER", "DONDER EN BLIKSEM": "THUNDER",
    "ONWEER": "THUNDER", "WEERLICHT": "THUNDER",
    "BLIKSEM": "THUNDER",
}

# Spanish weather terms → category
WEATHER_ES = {
    # CLEAR
    "CLARO": "CLEAR", "CLAROS": "CLEAR", "CIELO CLARO": "CLEAR",
    "CIELOS CLAROS": "CLEAR", "DESPEJADO": "CLEAR", "DESPEJADOS": "CLEAR",
    "CIELOS Y HORIZONTES CLAROS": "CLEAR",
    "HORIZONTES CLAROS": "CLEAR", "LIMPIO": "CLEAR",

    # FAIR
    "BUEN TIEMPO": "FAIR", "BUENO": "FAIR", "BONANZA": "FAIR",
    "SERENO": "FAIR", "APACIBLE": "FAIR",
    "BONANCIBLE": "FAIR", "TRANQUILO": "FAIR",

    # CLOUDY
    "NUBLADO": "CLOUDY", "NUBLADOS": "CLOUDY", "NUBOSO": "CLOUDY",
    "CUBIERTO": "CLOUDY", "CIELO CUBIERTO": "CLOUDY",
    "OSCURO": "CLOUDY", "HORIZONTES CARGADOS": "CLOUDY",
    "CARGADO": "CLOUDY", "CARGADOS": "CLOUDY",
    "CERRADO": "CLOUDY", "ENCAPOTADO": "CLOUDY",
    "CIELOS Y HORIZONTES CARGADOS": "CLOUDY",
    "CARIZ": "CLOUDY", "HORIZONTES CERRADOS": "CLOUDY",
    "CIELOS Y HORIZONTES CERRADOS": "CLOUDY",

    # OVERCAST
    "MUY CUBIERTO": "OVERCAST", "TODO CUBIERTO": "OVERCAST",
    "CIELO MUY CUBIERTO": "OVERCAST",

    # RAIN
    "LLUVIA": "RAIN", "LLUVIOSO": "RAIN", "LLOVIENDO": "RAIN",
    "MUCHA LLUVIA": "RAIN", "AGUA": "RAIN",
    "AGUACERO": "RAIN", "AGUACEROS": "RAIN",

    # DRIZZLE
    "LLOVIZNA": "DRIZZLE", "LLOVIZNANDO": "DRIZZLE",
    "GARUA": "DRIZZLE",

    # SHOWERS
    "CHUBASCOS": "SHOWERS", "CHUBASCO": "SHOWERS",
    "CHUBASQUILLO": "SHOWERS",

    # SQUALL
    "TURBONADA": "SQUALL", "TURBONADAS": "SQUALL",
    "FUGADAS": "SQUALL", "FUGOSO": "SQUALL",
    "RACHAS": "SQUALL", "RAFAGAS": "SQUALL",

    # STORM
    "TEMPORAL": "STORM", "TEMPESTAD": "STORM", "TEMPESTUOSO": "STORM",
    "TORMENTA": "STORM", "TORMENTOSO": "STORM",
    "HURACAN": "STORM", "HURACANADO": "STORM",

    # FOG
    "NEBLINA": "FOG", "NEBLINOSO": "FOG", "NIEBLA": "FOG",
    "CERRAZON": "FOG", "BRUMA": "FOG",

    # HAZE
    "CALIMA": "HAZE", "CALINA": "HAZE", "BRUMOSO": "HAZE",

    # SNOW
    "NIEVE": "SNOW", "NEVANDO": "SNOW", "GRANIZO": "SNOW",

    # THUNDER
    "TRUENOS": "THUNDER", "TRUENO": "THUNDER",
    "RELAMPAGO": "THUNDER", "RELAMPAGOS": "THUNDER",
    "RELÁMPAGOS": "THUNDER", "RAYOS": "THUNDER",
}

# French weather terms → category
WEATHER_FR = {
    # CLEAR
    "CLAIR": "CLEAR", "CIEL CLAIR": "CLEAR",
    "TEMPS CLAIR": "CLEAR", "SEREIN": "CLEAR",

    # FAIR
    "BEAU TEMPS": "FAIR", "BEAU": "FAIR", "BON TEMPS": "FAIR",
    "JOLI TEMPS": "FAIR", "AGREABLE": "FAIR",

    # CLOUDY
    "COUVERT": "CLOUDY", "NUAGEUX": "CLOUDY", "BRUMEUX": "CLOUDY",
    "SOMBRE": "CLOUDY", "CIEL COUVERT": "CLOUDY",
    "TEMPS COUVERT": "CLOUDY", "NEBULEUX": "CLOUDY",

    # OVERCAST
    "TRES COUVERT": "OVERCAST", "TOUT COUVERT": "OVERCAST",

    # RAIN
    "PLUIE": "RAIN", "PLUVIEUX": "RAIN",
    "BEAUCOUP DE PLUIE": "RAIN", "TEMPS DE PLUIE": "RAIN",

    # DRIZZLE
    "BRUINE": "DRIZZLE", "CRACHIN": "DRIZZLE",
    "PETITE PLUIE": "DRIZZLE",

    # SHOWERS
    "AVERSES": "SHOWERS", "AVERSE": "SHOWERS",
    "GRAINS": "SHOWERS", "GRAIN": "SHOWERS",

    # SQUALL
    "GRAINS VIOLENTS": "SQUALL", "RAFALES": "SQUALL",
    "BOURRASQUE": "SQUALL", "BOURRASQUES": "SQUALL",

    # STORM
    "TEMPETE": "STORM", "TOURMENTE": "STORM",
    "OURAGAN": "STORM", "ORAGE": "STORM",

    # FOG
    "BROUILLARD": "FOG", "BRUME": "FOG",

    # HAZE
    "BRUME SECHE": "HAZE", "EMBRUME": "HAZE",

    # SNOW
    "NEIGE": "SNOW", "GRELE": "SNOW",

    # THUNDER
    "TONNERRE": "THUNDER", "ECLAIRS": "THUNDER",
    "ORAGE": "THUNDER",
}

# Merge all weather dictionaries
WEATHER_DICT = {}
for d in [WEATHER_EN, WEATHER_NL, WEATHER_ES, WEATHER_FR]:
    WEATHER_DICT.update(d)

# ── Pattern-based weather classification ───────────────────────────────────
# Keywords that indicate a category when found as a substring
# Ordered by specificity (most specific first)
WEATHER_PATTERNS = [
    # Thunder (check before rain/storm since "thunder showers" = thunder)
    (r"\b(THUNDER|LIGHTNING|DONDER|BLIKSEM|TRUENO|RELAMPAGO|TONNERRE|ECLAIRS|ONWEER)\b", "THUNDER"),
    # Snow
    (r"\b(SNOW|SNEEUW|NIEVE|NEIGE|SLEET|HAGEL|HAIL|GRELE|GRANIZO)\b", "SNOW"),
    # Fog
    (r"\b(FOG|FOGGY|MIST|MISTIG|NIEBLA|NEBLINA|BROUILLARD|BRUME|CERRAZON)\b", "FOG"),
    # Haze
    (r"\b(HAZE|HAZY|HAZEY|HEIIG|CALIMA|CALINA|BRUMOSO)\b", "HAZE"),
    # Storm / hurricane
    (r"\b(HURRICANE|TYPHOON|TEMPEST|ORKAAN|HURACAN|OURAGAN|TEMPETE)\b", "STORM"),
    (r"\b(STORM|STORMY|STORMACHTIG|TEMPORAL|TEMPESTAD|TOURMENTE)\b", "STORM"),
    # Squall
    (r"\b(SQUALL|SQUALLY|TURBONADA|FUGADAS|RAFALES|BOURRASQUE|RUKWIND)\b", "SQUALL"),
    # Showers
    (r"\b(SHOWER|SHOWERY|CHUBASC|AVERSE|GRAIN)\b", "SHOWERS"),
    # Drizzle
    (r"\b(DRIZZL|MIZZL|MOTREGEN|MOTTIG|LLOVIZN|GARUA|BRUINE|CRACHIN)\b", "DRIZZLE"),
    # Rain
    (r"\b(RAIN|RAINY|REGEN|LLUVI|LLOVIEN|PLUIE|PLUVIEUX|WET)\b", "RAIN"),
    # Overcast
    (r"\b(OVERCAST|GEHEEL BETROKKEN|MUY CUBIERTO|TRES COUVERT)\b", "OVERCAST"),
    # Cloudy
    (r"\b(CLOUD|BEWOLKT|BETROKKEN|DONKER|NUBLAD|CUBIERT|COUVERT|SOMBRE|DULL|GLOOMY|THICK|CARGAD|CERRAD|ENCAPOTAD|DAMPIG|DIKKE)\b", "CLOUDY"),
    # Clear
    (r"\b(CLEAR|HELDER|KLAAR|CLARO|DESPEJAD|CLAIR|SEREIN|LIMPIO)\b", "CLEAR"),
    # Fair (check last — most general)
    (r"\b(FINE|FAIR|PLEASANT|GOED WEER|MOOI WEER|SCHOON|BUEN TIEMPO|BEAU TEMPS|BEAU|FRAAI)\b", "FAIR"),
]

WEATHER_PATTERNS_COMPILED = [(re.compile(pat, re.IGNORECASE), cat) for pat, cat in WEATHER_PATTERNS]


# ══════════════════════════════════════════════════════════════════════════════
# SEA STATE CLASSIFICATION (Douglas Scale 0-9)
# ══════════════════════════════════════════════════════════════════════════════

# ── CLIWOC coded values (Z## codes in StateSea column) ─────────────────────
SEA_STATE_CODES = {
    "Z00": 0,  # Calm (glassy)
    "Z01": 1,  # Calm (rippled)
    "Z02": 2,  # Smooth
    "Z03": 3,  # Slight
    "Z04": 4,  # Moderate
    "Z05": 5,  # Rough
    "Z06": 6,  # Very rough
    "Z07": 7,  # High
    "Z08": 8,  # Very high
    "Z09": 9,  # Phenomenal
}

# ── Multilingual sea state dictionaries ────────────────────────────────────

# Spanish (dominant for sea state: 35K records)
SEA_STATE_ES = {
    # 0 - Calm (glassy)
    "CALMA": 0, "CALMA MUERTA": 0, "EN CALMA": 0,
    "MAR EN CALMA": 0, "MAR DE LECHE": 0,

    # 1 - Calm (rippled) / very smooth
    "LLANA": 1, "LLANADA": 1, "MAR LLANA": 1,
    "BELLA": 1, "MAR BELLA": 1, "BONANZA": 1,
    "BONANCIBLE": 1, "TRANQUILA": 1, "MAR TRANQUILA": 1,
    "RIZADA": 1, "RIZO": 1,

    # 2 - Smooth (wavelets)
    "MAREJADILLA": 2, "ALGO LLANA": 2,
    "POCA MAR": 2, "POCO MOVIDA": 2,

    # 3 - Slight
    "ALGO PICADA": 3, "ALGO MOVIDA": 3, "MEDIO PICADA": 3,
    "MAREJADA": 3, "MAR ALGO PICADA": 3,
    "ALGO GRUESA": 3,

    # 4 - Moderate
    "PICADA": 4, "MAR PICADA": 4, "MOVIDA": 4,
    "MAR MOVIDA": 4, "REVUELTA": 4, "MAR REVUELTA": 4,

    # 5 - Rough
    "GRUESA": 5, "MAR GRUESA": 5, "BASTANTE GRUESA": 5,
    "MUY PICADA": 5, "ALBOROTADA": 5, "MAR ALBOROTADA": 5,
    "BRAVA": 5,

    # 6 - Very rough
    "MUY GRUESA": 6, "ARBOLADA": 6, "MAR ARBOLADA": 6,
    "MUY ALBOROTADA": 6, "FURIOSA": 6,

    # 7 - High
    "MONTAÑOSA": 7, "MAR MONTAÑOSA": 7,
    "MONTANA": 7, "MAR MONTANA": 7,
    "ENORME": 7,

    # 8 - Very high
    "MUY MONTAÑOSA": 8, "MUY MONTANA": 8,
    "FORMIDABLE": 8,

    # 9 - Phenomenal
    "MONSTRUOSA": 9,

    # Swell terms (map to approximate sea state)
    "MARETA": 3, "MARETADA": 4, "MAREJADA SORDA": 3,
    "MAR SORDA": 2, "MAR DE FONDO": 3,
    "MAR DEL NORTE": 4, "MAR DEL SUR": 4, "MAR DEL ESTE": 4,
    "MAR DEL OESTE": 4, "MAR DE LEVA": 5,
}

# English
SEA_STATE_EN = {
    # 0 - Calm
    "CALM SEA": 0, "CALM WATER": 0, "CALM": 0,
    "GLASSY": 0, "DEAD CALM": 0,

    # 1 - Calm (rippled)
    "SMOOTH": 1, "SMOOTH SEA": 1, "SMOOTH WATER": 1,
    "FINE": 1,

    # 2 - Smooth
    "SLIGHT SEA": 2, "SLIGHT SWELL": 2,

    # 3 - Slight
    "MODERATE SEA": 3, "MODERATE SWELL": 3,
    "SHORT SEA": 3,

    # 4 - Moderate
    "ROUGH SEA": 4, "ROUGH": 4, "CHOPPY": 4,
    "CHOPPY SEA": 4, "CROSS SEA": 4,

    # 5 - Rough
    "HEAVY SEA": 5, "LARGE SEA": 5, "HIGH SEA": 5,
    "LARGE SWELL": 5, "HEAVY SWELL": 5,

    # 6 - Very rough
    "VERY HEAVY SEA": 6, "VERY ROUGH SEA": 6,
    "CONFUSED SEA": 6, "VERY LARGE SEA": 6,

    # 7 - High
    "MOUNTAINOUS SEA": 7, "TREMENDOUS SEA": 7,
    "ENORMOUS SEA": 7,
}

# Dutch
SEA_STATE_NL = {
    # 0 - Calm
    "STILLE ZEE": 0, "GLADDE ZEE": 0,

    # 1 - Calm (rippled)
    "KALME ZEE": 1, "EFFEN ZEE": 1,

    # 2 - Smooth
    "VLAKKE ZEE": 2,

    # 3 - Slight
    "WEINIG ZEE": 3, "KORTE ZEE": 3,

    # 4 - Moderate
    "ONSTUIMIGE ZEE": 4, "HOGE ZEE": 4,
    "HOLLE ZEE": 4,

    # 5 - Rough
    "HOGE DEINING": 5, "ZWARE ZEE": 5,
    "ZWARE DEINING": 5, "HOGE GOLVEN": 5,

    # 6 - Very rough
    "ZEER HOGE ZEE": 6, "ZEER ZWARE ZEE": 6,
    "ONSTUIMIG": 6,

    # Swell
    "DEINING": 3, "LANGE DEINING": 3, "KORTE DEINING": 2,
    "ZEE": 3,
}

# French
SEA_STATE_FR = {
    # 0 - Calm
    "CALME": 0, "MER CALME": 0,

    # 1 - Calm (rippled)
    "BELLE": 1, "BELLE MER": 1, "MER BELLE": 1,

    # 2 - Smooth
    "PEU AGITEE": 2, "PLATE": 2,

    # 3 - Slight
    "AGITEE": 3, "CLAPOTEUSE": 3,

    # 4 - Moderate
    "FORTE": 4, "HOULEUSE": 4, "MER HOULEUSE": 4,

    # 5 - Rough
    "GROSSE": 5, "GROSSE MER": 5, "MER GROSSE": 5,
    "GROSSE HOULE": 5, "TRES AGITEE": 5,

    # 6 - Very rough
    "TRES GROSSE": 6, "TRES FORTE": 6, "DEMONTER": 6,
    "DEMONTEE": 6,

    # 7 - High
    "ENORME": 7,

    # Swell
    "HOULE": 3, "LONGUE HOULE": 3,
}

# Merge all sea state dictionaries
SEA_STATE_DICT = {}
for d in [SEA_STATE_ES, SEA_STATE_EN, SEA_STATE_NL, SEA_STATE_FR]:
    SEA_STATE_DICT.update(d)

# ── Pattern-based sea state classification ─────────────────────────────────
# Keywords for Douglas scale ranges
SEA_STATE_PATTERNS = [
    # 0 - Calm
    (r"\b(CALMA MUERTA|DEAD CALM|CALME PLAT)\b", 0),
    # 1 - Calm/smooth
    (r"\b(LLANA|LLANADA|SMOOTH|BELLA|TRANQUIL|RIZADA|BONANCIBLE|BELLE|EFFEN)\b", 1),
    # 2 - Smooth (wavelets)
    (r"\b(MAREJADILLA|POCO MOVID|POCA MAR|SLIGHT SWELL|MAR SORDA)\b", 2),
    # 3 - Slight
    (r"\b(ALGO PICAD|ALGO MOVID|ALGO GRUES|MAREJADA|MODERATE SEA|MODERATE SWELL|SHORT SEA|DEINING|HOULE|MARETA\b)\b", 3),
    # 4 - Moderate
    (r"\b(PICADA|MOVIDA|REVUELT|ROUGH|CHOPPY|CROSS SEA|HOGE ZEE|HOLLE ZEE|HOULEUSE|FORTE)\b", 4),
    # 5 - Rough
    (r"\b(GRUESA|HEAVY SEA|LARGE SEA|HIGH SEA|HEAVY SWELL|LARGE SWELL|BRAVA|ALBOROTAD|ZWARE ZEE|GROSSE)\b", 5),
    # 6 - Very rough
    (r"\b(MUY GRUESA|ARBOLAD|FURIOS|VERY HEAVY|VERY ROUGH|VERY LARGE|CONFUSED|DEMONTE|ONSTUIMIG)\b", 6),
    # 7+ - High/phenomenal
    (r"\b(MONTANA|MONTAÑOSA|MOUNTAINOUS|TREMENDOUS|ENORMOUS|ENORME|MONSTRUOS|FORMIDABLE)\b", 7),
]

SEA_STATE_PATTERNS_COMPILED = [(re.compile(pat, re.IGNORECASE), val) for pat, val in SEA_STATE_PATTERNS]


# ══════════════════════════════════════════════════════════════════════════════
# CLASSIFICATION FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def classify_weather(term):
    """
    Classify a weather description into a standardized category.
    Returns (category, confidence, method, reasoning).
    """
    if not term or not term.strip():
        return None, None, None, "empty"

    t = term.strip().upper()

    # Layer 1: CLIWOC coded values
    if t in WEATHER_CODES:
        return WEATHER_CODES[t], "high", "code", f"CLIWOC code {t}"

    # Also check if code is embedded (e.g., "W00 FINE WEATHER")
    code_match = re.match(r'^(W\d{2})\b', t)
    if code_match:
        code = code_match.group(1)
        if code in WEATHER_CODES:
            return WEATHER_CODES[code], "high", "code", f"CLIWOC code prefix {code}"

    # Layer 2: Direct dictionary match
    if t in WEATHER_DICT:
        return WEATHER_DICT[t], "high", "dict", f"Direct match: {t}"

    # Layer 3: Pattern matching
    for pat, cat in WEATHER_PATTERNS_COMPILED:
        if pat.search(t):
            return cat, "medium", "pattern", f"Pattern match in: {t}"

    # Layer 4: Check if it's a compound description with recognizable parts
    # Split on common delimiters and check each part
    parts = re.split(r'[,;/&]\s*|\s+AND\s+|\s+WITH\s+|\s+Y\s+|\s+EN\s+|\s+ET\s+', t)
    categories = []
    for part in parts:
        part = part.strip()
        if part in WEATHER_DICT:
            categories.append(WEATHER_DICT[part])
        else:
            for pat, cat in WEATHER_PATTERNS_COMPILED:
                if pat.search(part):
                    categories.append(cat)
                    break

    if categories:
        # Pick the most "severe" category (storm > rain > cloudy > fair > clear)
        severity = ["CLEAR", "FAIR", "HAZE", "CLOUDY", "OVERCAST", "FOG",
                     "DRIZZLE", "RAIN", "SHOWERS", "SNOW", "SQUALL", "THUNDER", "STORM"]
        best = max(categories, key=lambda c: severity.index(c) if c in severity else -1)
        if len(set(categories)) > 1:
            return "MIXED", "medium", "compound", f"Multiple categories in compound: {categories}"
        return best, "medium", "compound", f"Compound parse: {categories}"

    return None, None, "unmatched", f"Could not classify: {term}"


def classify_sea_state(term):
    """
    Classify a sea state description to Douglas Scale (0-9).
    Returns (scale, confidence, method, reasoning).
    """
    if not term or not term.strip():
        return None, None, None, "empty"

    t = term.strip().upper()

    # Layer 1: CLIWOC coded values
    if t in SEA_STATE_CODES:
        return SEA_STATE_CODES[t], "high", "code", f"CLIWOC code {t}"

    code_match = re.match(r'^(Z\d{2})\b', t)
    if code_match:
        code = code_match.group(1)
        if code in SEA_STATE_CODES:
            return SEA_STATE_CODES[code], "high", "code", f"CLIWOC code prefix {code}"

    # Layer 2: Direct dictionary match
    if t in SEA_STATE_DICT:
        return SEA_STATE_DICT[t], "high", "dict", f"Direct match: {t}"

    # Layer 3: Pattern matching
    for pat, val in SEA_STATE_PATTERNS_COMPILED:
        if pat.search(t):
            return val, "medium", "pattern", f"Pattern match in: {t}"

    # Layer 4: Compound — split and average
    parts = re.split(r'[,;/&]\s*|\s+Y\s+|\s+AND\s+|\s+ET\s+|\s+EN\s+', t)
    values = []
    for part in parts:
        part = part.strip()
        if part in SEA_STATE_DICT:
            values.append(SEA_STATE_DICT[part])
        else:
            for pat, val in SEA_STATE_PATTERNS_COMPILED:
                if pat.search(part):
                    values.append(val)
                    break

    if values:
        avg = round(sum(values) / len(values))
        return avg, "medium", "compound", f"Compound average: {values}"

    return None, None, "unmatched", f"Could not classify: {term}"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("CLIWOC DATA CLEANING — PHASE 4: WEATHER & SEA STATE CLASSIFICATION")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)

    # ── Part 1: Weather Classification ──
    print("\n── Part 1: Weather Classification ──")

    # Get all unique weather terms
    weather_df = pd.read_sql("""
        SELECT DISTINCT Weather
        FROM observations
        WHERE Weather IS NOT NULL AND Weather != ''
    """, conn)
    unique_weather = weather_df["Weather"].tolist()
    print(f"  {len(unique_weather):,} unique weather terms to classify")

    # Count records per term for statistics
    weather_counts = pd.read_sql("""
        SELECT Weather, COUNT(*) as cnt
        FROM observations
        WHERE Weather IS NOT NULL AND Weather != ''
        GROUP BY Weather
    """, conn)
    weather_count_map = dict(zip(weather_counts["Weather"], weather_counts["cnt"]))
    total_weather_records = sum(weather_count_map.values())
    print(f"  {total_weather_records:,} total records with weather data")

    # Classify each unique term
    weather_translations = {}
    for term in unique_weather:
        cat, conf, method, reasoning = classify_weather(term)
        weather_translations[term] = {
            "category": cat,
            "confidence": conf,
            "method": method,
            "reasoning": reasoning,
        }

    # Statistics
    w_by_cat = defaultdict(int)
    w_by_method = defaultdict(int)
    w_by_conf = defaultdict(int)
    w_records_classified = 0
    w_records_unmatched = 0

    for term, info in weather_translations.items():
        cnt = weather_count_map.get(term, 0)
        w_by_method[info["method"]] += cnt
        if info["category"]:
            w_by_cat[info["category"]] += cnt
            w_records_classified += cnt
            if info["confidence"]:
                w_by_conf[info["confidence"]] += cnt
        else:
            w_records_unmatched += cnt

    n_terms_classified = sum(1 for v in weather_translations.values() if v["category"])
    n_terms_unmatched = sum(1 for v in weather_translations.values() if not v["category"])

    print(f"\n  Classification results ({len(unique_weather):,} unique terms):")
    print(f"    Classified: {n_terms_classified:,} terms ({w_records_classified:,} records, "
          f"{w_records_classified / total_weather_records * 100:.1f}%)")
    print(f"    Unmatched:  {n_terms_unmatched:,} terms ({w_records_unmatched:,} records, "
          f"{w_records_unmatched / total_weather_records * 100:.1f}%)")

    print(f"\n  By category (records):")
    for cat, cnt in sorted(w_by_cat.items(), key=lambda x: -x[1]):
        print(f"    {cat:12s}: {cnt:,}")

    print(f"\n  By method (records):")
    for method, cnt in sorted(w_by_method.items(), key=lambda x: -x[1]):
        print(f"    {method:12s}: {cnt:,}")

    print(f"\n  By confidence (records):")
    for conf, cnt in sorted(w_by_conf.items(), key=lambda x: -x[1]):
        print(f"    {conf:8s}: {cnt:,}")

    # Show top unmatched
    unmatched_weather = [(t, weather_count_map.get(t, 0))
                         for t, v in weather_translations.items() if not v["category"]]
    unmatched_weather.sort(key=lambda x: -x[1])
    if unmatched_weather:
        print(f"\n  Top 30 unmatched weather terms ({len(unmatched_weather)} total):")
        for term, cnt in unmatched_weather[:30]:
            print(f"    {cnt:5d}x  \"{term}\"")

    # ── Part 2: Sea State Classification ──
    print("\n\n── Part 2: Sea State Classification ──")

    sea_df = pd.read_sql("""
        SELECT DISTINCT StateSea
        FROM observations
        WHERE StateSea IS NOT NULL AND StateSea != ''
    """, conn)
    unique_sea = sea_df["StateSea"].tolist()
    print(f"  {len(unique_sea):,} unique sea state terms to classify")

    sea_counts = pd.read_sql("""
        SELECT StateSea, COUNT(*) as cnt
        FROM observations
        WHERE StateSea IS NOT NULL AND StateSea != ''
        GROUP BY StateSea
    """, conn)
    sea_count_map = dict(zip(sea_counts["StateSea"], sea_counts["cnt"]))
    total_sea_records = sum(sea_count_map.values())
    print(f"  {total_sea_records:,} total records with sea state data")

    sea_translations = {}
    for term in unique_sea:
        scale, conf, method, reasoning = classify_sea_state(term)
        sea_translations[term] = {
            "douglas_scale": scale,
            "confidence": conf,
            "method": method,
            "reasoning": reasoning,
        }

    # Statistics
    s_by_scale = defaultdict(int)
    s_by_method = defaultdict(int)
    s_by_conf = defaultdict(int)
    s_records_classified = 0
    s_records_unmatched = 0

    douglas_labels = {
        0: "Calm (glassy)", 1: "Calm (rippled)", 2: "Smooth",
        3: "Slight", 4: "Moderate", 5: "Rough",
        6: "Very rough", 7: "High", 8: "Very high", 9: "Phenomenal",
    }

    for term, info in sea_translations.items():
        cnt = sea_count_map.get(term, 0)
        s_by_method[info["method"]] += cnt
        if info["douglas_scale"] is not None:
            s_by_scale[info["douglas_scale"]] += cnt
            s_records_classified += cnt
            if info["confidence"]:
                s_by_conf[info["confidence"]] += cnt
        else:
            s_records_unmatched += cnt

    n_sea_classified = sum(1 for v in sea_translations.values() if v["douglas_scale"] is not None)
    n_sea_unmatched = sum(1 for v in sea_translations.values() if v["douglas_scale"] is None)

    print(f"\n  Classification results ({len(unique_sea):,} unique terms):")
    print(f"    Classified: {n_sea_classified:,} terms ({s_records_classified:,} records, "
          f"{s_records_classified / total_sea_records * 100:.1f}%)")
    print(f"    Unmatched:  {n_sea_unmatched:,} terms ({s_records_unmatched:,} records, "
          f"{s_records_unmatched / total_sea_records * 100:.1f}%)")

    print(f"\n  By Douglas Scale (records):")
    for scale in range(10):
        cnt = s_by_scale.get(scale, 0)
        label = douglas_labels[scale]
        if cnt > 0:
            print(f"    {scale} ({label:17s}): {cnt:,}")

    print(f"\n  By method (records):")
    for method, cnt in sorted(s_by_method.items(), key=lambda x: -x[1]):
        print(f"    {method:12s}: {cnt:,}")

    print(f"\n  By confidence (records):")
    for conf, cnt in sorted(s_by_conf.items(), key=lambda x: -x[1]):
        print(f"    {conf:8s}: {cnt:,}")

    # Show top unmatched
    unmatched_sea = [(t, sea_count_map.get(t, 0))
                     for t, v in sea_translations.items() if v["douglas_scale"] is None]
    unmatched_sea.sort(key=lambda x: -x[1])
    if unmatched_sea:
        print(f"\n  Top 30 unmatched sea state terms ({len(unmatched_sea)} total):")
        for term, cnt in unmatched_sea[:30]:
            print(f"    {cnt:5d}x  \"{term}\"")

    # ── Save JSON audit trails ──
    print(f"\n\n── Saving classification files ──")

    with open(WEATHER_JSON, "w") as f:
        json.dump(weather_translations, f, indent=2, ensure_ascii=False)
    print(f"  Weather: {WEATHER_JSON} ({len(weather_translations)} entries)")

    with open(SEA_STATE_JSON, "w") as f:
        json.dump(sea_translations, f, indent=2, ensure_ascii=False)
    print(f"  Sea state: {SEA_STATE_JSON} ({len(sea_translations)} entries)")

    # ── Update database ──
    print("\n── Updating database ──")
    cur = conn.cursor()

    # Add columns
    for col, typ in [("weather_category", "TEXT"), ("sea_state", "INTEGER")]:
        try:
            cur.execute(f"ALTER TABLE observations ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # already exists

    # Apply weather classifications
    print("  Applying weather classifications ...")
    n_weather_updated = 0
    for term, info in weather_translations.items():
        if info["category"]:
            cur.execute("""
                UPDATE observations
                SET weather_category = ?
                WHERE Weather = ?
            """, [info["category"], term])
            n_weather_updated += cur.rowcount

    # Apply sea state classifications
    print("  Applying sea state classifications ...")
    n_sea_updated = 0
    for term, info in sea_translations.items():
        if info["douglas_scale"] is not None:
            cur.execute("""
                UPDATE observations
                SET sea_state = ?
                WHERE StateSea = ?
            """, [info["douglas_scale"], term])
            n_sea_updated += cur.rowcount

    conn.commit()
    print(f"  Weather: {n_weather_updated:,} records updated")
    print(f"  Sea state: {n_sea_updated:,} records updated")

    # Create indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_obs_weather_category ON observations (weather_category)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_obs_sea_state ON observations (sea_state)")
    conn.commit()

    # ── Verification ──
    print("\n── Verification ──")

    for col in ["weather_category", "sea_state"]:
        row = cur.execute(f"SELECT COUNT(*) FROM observations WHERE {col} IS NOT NULL").fetchone()
        total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        print(f"  {col}: {row[0]:,} / {total:,} non-null ({row[0]/total*100:.1f}%)")

    # Weather category distribution
    print("\n  Weather category distribution:")
    rows = cur.execute("""
        SELECT weather_category, COUNT(*) as cnt
        FROM observations
        WHERE weather_category IS NOT NULL
        GROUP BY weather_category
        ORDER BY cnt DESC
    """).fetchall()
    for cat, cnt in rows:
        print(f"    {cat:12s}: {cnt:,}")

    # Sea state distribution
    print("\n  Sea state distribution:")
    rows = cur.execute("""
        SELECT sea_state, COUNT(*) as cnt
        FROM observations
        WHERE sea_state IS NOT NULL
        GROUP BY sea_state
        ORDER BY cnt DESC
    """).fetchall()
    for scale, cnt in rows:
        label = douglas_labels.get(scale, "?")
        print(f"    {scale} ({label:17s}): {cnt:,}")

    # Sample
    print("\n  Sample classified records:")
    sample = pd.read_sql("""
        SELECT Weather, weather_category, StateSea, sea_state, Nationality1
        FROM observations
        WHERE weather_category IS NOT NULL AND sea_state IS NOT NULL
        LIMIT 15
    """, conn)
    print(sample.to_string())

    # ── Summary ──
    print("\n" + "=" * 70)
    print("PHASE 4 SUMMARY")
    print("=" * 70)
    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    print(f"  Total records:              {total:,}")
    print(f"  Weather text available:     {total_weather_records:,} ({total_weather_records/total*100:.1f}%)")
    print(f"  Weather classified:         {n_weather_updated:,} ({n_weather_updated/total*100:.1f}%)")
    print(f"  Weather unmatched:          {w_records_unmatched:,} ({w_records_unmatched/total_weather_records*100:.1f}% of weather records)")
    print(f"  Sea state text available:   {total_sea_records:,} ({total_sea_records/total*100:.1f}%)")
    print(f"  Sea state classified:       {n_sea_updated:,} ({n_sea_updated/total*100:.1f}%)")
    print(f"  Sea state unmatched:        {s_records_unmatched:,} ({s_records_unmatched/total_sea_records*100:.1f}% of sea state records)")
    print(f"\n  Output files:")
    print(f"    {WEATHER_JSON}")
    print(f"    {SEA_STATE_JSON}")

    conn.close()
    print(f"\nPhase 4 complete. Database: {DB_PATH}")


if __name__ == "__main__":
    main()
