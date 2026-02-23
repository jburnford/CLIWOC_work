"""
Phase 3: Wind Force Translation (LLM-Assisted)
CLIWOC Data Cleaning Pipeline for "Sailors and Circulation"

Translates the ~14,450 records that have AllWindForces text but no W value.
Uses three layers:
  1. Direct dictionary lookup (from DB existing translations + CLIWOC PDF)
  2. Compound temporal parsing (strip PM/AM/FIRST PART etc., extract base terms)
  3. Claude-generated translations for remaining terms

All translations saved to wind_term_translations.json with audit trail.

Results (Feb 2026):
  - 10,477/14,450 records translated (72.5%)
  - 2,629 correctly NDA (variable/squally — no Beaufort equivalent per CLIWOC PDF)
  - 689 unique terms (1,344 records, 0.5% of dataset) left unmatched — mostly
    squall-only temporal markers and rare multilingual terms. Documented in JSON
    for future team review. Negligible impact on trends.
"""

import json
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/home/jic823/climate")
OUT_DIR = BASE_DIR / "cleaned"
DB_PATH = OUT_DIR / "cliwoc_cleaned.db"
JSON_PATH = OUT_DIR / "wind_term_translations.json"

# ── Beaufort → W mapping (modal values from CLIWOC data) ─────────────────────
BF_TO_W = {
    0: 0, 1: 10, 2: 26, 3: 46, 4: 67, 5: 93,
    6: 123, 7: 154, 8: 190, 9: 226, 10: 268,
    11: 309, 12: 350,
}

# ── CLIWOC PDF Dictionary ────────────────────────────────────────────────────
# From "CLIWOC Multilingual Meteorological Dictionary" (KNMI, EU project)
# Format: term → (beaufort, confidence, source)
# NDA = "no definition available" per PDF; BF>8 mapped to BF9

PDF_DICT = {}

# English terms (pp. 13-16)
_en = {
    "CALM": 0, "FLAT CALM": 0, "DEAD CALM": 0,
    "LIGHT AIRS": 1, "SMALL AIRS": 1, "INCLINABLE TO CALM": 1, "INCLINABLE TO CALMS": 1,
    "EASY BREEZE": 2, "EASY BREEZES": 2, "FEINT BREEZE": 2, "FEINT BREEZES": 2,
    "LIGHT BREEZE": 2, "LIGHT BREEZES": 2, "LIGHT WINDS": 2, "LITTLE WINDS": 2,
    "EASY GALE": 3, "FEINT GALE": 3, "GENTLE BREEZE": 3, "GENTLE BREEZES": 3,
    "GENTLE GALE": 3, "GENTLE GALES": 3, "GENTLE TRADE": 3, "GENTLE TRADES": 3,
    "LIGHT GALE": 3,
    "LIGHT MONSOON": 4, "LIGHT MONSOONS": 4, "LIGHT TRADE": 4, "LIGHT TRADES": 4,
    "MODERATE": 4, "MODERATE BREEZE": 4, "MODERATE BREEZES": 4,
    "PLEASANT BREEZE": 4, "PLEASANT BREEZES": 4, "PLEASANT WIND": 4,
    "SMALL GALE": 4, "SMALL GALES": 4,
    "BRISK TRADE": 5, "BRISK TRADES": 5, "FINE BREEZE": 5, "FINE BREEZES": 5,
    "FINE GALE": 5, "FINE GALES": 5, "FINE TRADE": 5, "FINE TRADES": 5,
    "FRESH BREEZE": 5, "FRESH BREEZES": 5, "MODERATE MONSOON": 5,
    "MODERATE MONSOONS": 5, "MODERATE TRADE": 5, "MODERATE TRADES": 5,
    "PLEASANT GALE": 5, "PLEASANT GALES": 5, "PLEASANT TRADE": 5,
    "PLEASANT TRADES": 5, "STEADY BREEZE": 5, "STEADY BREEZES": 5,
    "TOP-GALLANT GALE": 5, "TOPGALLANT GALE": 5,
    "BLOWS FRESH": 6, "BRISK GALE": 6, "BRISK GALES": 6,
    "FRESH TRADE": 6, "FRESH TRADES": 6, "FRESH WIND": 6, "FRESH WINDS": 6,
    "STEADY GALE": 6, "STEADY GALES": 6, "STEADY TRADE": 6, "STEADY TRADES": 6,
    "STIFF BREEZE": 6, "STIFF BREEZES": 6, "STRONG BREEZE": 6, "STRONG BREEZES": 6,
    "MODERATE GALE": 7, "MODERATE GALES": 7, "STRONG MONSOON": 7,
    "STRONG MONSOONS": 7, "STRONG TRADE": 7, "STRONG TRADES": 7,
    "FRESH GALE": 8, "FRESH GALES": 8, "STRONG WIND": 8, "STRONG WINDS": 8,
    "BLOWS STRONG": 9, "HEAVY GALE": 9, "HEAVY GALES": 9,
    "STRONG GALE": 9, "STRONG GALES": 9, "VIOLENT GALE": 9, "VIOLENT GALES": 9,
    "BLOWS HARD": 10, "HARD GALE": 10, "HARD GALES": 10,
    "WHOLE GALE": 10, "WHOLE GALES": 10,
    "STORM": 11, "TEMPEST": 11, "TREMENDOUS GALE": 11, "TREMENDOUS GALES": 11,
    "VIOLENT STORM": 11,
    "HURRICANE": 12, "TYPHOON": 12,
}
for term, bf in _en.items():
    PDF_DICT[term] = (bf, "high", "CLIWOC_PDF_EN")

# Spanish terms (pp. 18-21)
_es = {
    "CALMA": 0, "CALMA MUERTA": 0, "CALMO": 0, "PACIFICO": 0,
    "SERENO": 0, "SOSEGADO": 0, "NO HA HABIDO": 0, "DEBIL": 0,
    "AVENTOLINADO": 1, "BLANDURA": 1, "VENTOLINAS": 1,
    "ABRISADO": 2, "BRISA": 2, "BRISADO": 2, "CALMOSO": 2, "ESCASO": 2,
    "FLOJITO": 2, "PARDO": 2, "POCO": 2, "SUAVE": 2, "VACILANTE": 2,
    "ENDEBLE": 3, "FLOJO": 3,
    "ABONANZADO": 4, "ABONANZANDO": 4, "ABONANZO": 4, "APACIBLE": 4,
    "APACIGUADO": 4, "BENIGNO": 4, "BONANCIBLE": 4, "BONANZA": 4, "MODERADO": 4,
    "FRESQUECITO": 5, "FRESQUITO": 5,
    "DE ALTA VELA": 6, "DE TODA VELA": 6, "DE TODA VELA LARGA": 6,
    "DURITO": 6, "FRESCO": 6, "FRESCOTE": 6, "FUERTECITO": 6, "VIVITO": 6,
    "ALTIVO": 7, "DURO": 7, "FRESCACHON": 7, "FRESCACHONAZO": 7,
    "FUERTE": 7, "INTENSO": 7, "MUCHO": 7, "RECIO": 7, "VIVO": 7,
    "MUCHISIMO": 8, "TEMPORAL": 8,
    "TORMENTA": 9, "TORMENTOSO": 9,
    "FORTISIMO": 11,
    "AHURACANADO": 12, "HURACAN": 12, "HURACANADO": 12,
    "FEROCIDAD EXTRAORDINARIA": 12, "TORMENTOSO COMO ESPECIE DE HURACAN": 12,
    "FUGADAS HURACANADAS": 12,
    # BF > 8 terms → map to BF 9 as conservative estimate
    "ALTERADOS": 9, "AMENAZANTE": 9, "ATURBONADO": 9, "BORRASCOSO": 9,
    "DEMASIADO": 9, "FUERZA": 9, "FURIA": 9, "FURIOSO": 9,
    "IMPETUOSO": 9, "INAGUANTABLE": 9, "INSOPORTABLE": 9,
    "INSUFRIBLE": 9, "INTOLERABLE": 9, "RIEGUROSO": 9,
    "TEMPESTAD": 9, "TEMPESTUOSO": 9, "TURBONADA": 9,
}
for term, bf in _es.items():
    PDF_DICT[term] = (bf, "high", "CLIWOC_PDF_ES")

# Dutch terms (pp. 22-25)
_nl = {
    "STIL": 0, "STILLE": 0, "BLACKSTIL": 0, "BLADSTIL": 0,
    "DOOD STIL": 0, "DOODSTIL": 0, "DOODSTILTE": 0, "DOODSTILLETJES": 0,
    "AL DE ZEILEN BIJ": 1, "BRIESIE": 1, "BRIESJE": 1,
    "FLAAUW": 1, "FLAUW": 1, "FLAUWTJES": 1, "FLOUW": 1,
    "FLAAUWE KOELTE": 1, "FLAUWE KOELTE": 1, "FRISSE KOELTE": 1,
    "KLEINE KOELTE": 1, "LICHTE KOELTE": 1,
    "RONDLOPENDE KOELTE": 1, "SLAPPE KOELTE": 1,
    "VARIABELE KOELTE": 1, "VARIABLE": 1, "VARIABELE": 1,
    "BOVENBRAMZEILSKOELTE": 2, "FLAUWE BOVENBRAMZEILSKOELTE": 2,
    "GEMENE FRISSE BRAMZEILSKOELTE": 2, "GEMENE KOELTE": 2,
    "KOELTE": 2, "LABBER": 2, "LABBERE KOELTE": 2, "LABBERKOELTE": 2,
    "LABBER BRAMZEILSKOELTE": 2, "LEIZEILSKOELTE": 2,
    "LICHTE BOVENBRAMZEILSKOELTE": 2, "ONGESTAGIGE KOELTE": 2,
    "SLAPPE BRAMZEILSKOELTE": 2,
    "BRAMZEILSKOELTE": 3, "FLAUWE BRAMZEILSKOELTE": 3,
    "GEMENE BRAMZEILSKOELTE": 3, "GESTADIGE BRAMZEILSKOELTE": 3,
    "LICHTE BRAMZEILSKOELTE": 3, "ONGELIJKE BRAMZEILSKOELTE": 3,
    "ONGESTADIGE BRAMZEILSKOELTE": 3,
    "FRISSE MARSZEILSKOELTE": 4, "GEMENE MARSZEILSKOELTE": 4,
    "MARSZEILSKOELTE": 4, "ONGESTADIGE MARSZEILSKOELTE": 4,
    "STIJVE BRAMZEILSKOELTE": 4, "TOPZEILSKOELTE": 4,
    "BOVENMARSZEILSKOELTE": 5, "DUBBELGEREEFDE BRAMZEILSKOELTE": 5,
    "ENKELGEREEFDE MARSZEILSKOELTE": 5, "GEREEFDE MARSZEILSKOELTE": 5,
    "GESTADIGE KOELTE": 5, "ONGESTADIGE GEREEFDE MARSZEILSKOELTE": 5,
    "PASSAAT": 5, "PASSAATKOELTE": 5, "PASSAATWIND": 5,
    "STIJVE MARSZEILSKOELTE": 5,
    "DUBBELGEREEFDE MARSZEILSKOELTE": 6,
    "STIJVE GEREEFDE MARSZEILSKOELTE": 6, "STIJVE KOELTE": 6,
    "HARDE WIND": 7,
    "ONDERZEILSKOELTE": 8,
    "DICHT GEREEFDE MARSZEILSKOELTE": 9,
    "GEREEFDE ONDERZEILSKOELTE": 9,
    "DICHT GEREEFDE ONDERZEILSKOELTE": 10,
    "STORM": 10, "SWAERE STORM": 10, "ZWARE STORM": 10,
    "ZEER ZWARE STORM": 11,
    "ORCAAN": 12, "ORCAEN": 12, "ORKAAN": 12,
}
for term, bf in _nl.items():
    if term not in PDF_DICT:
        PDF_DICT[term] = (bf, "high", "CLIWOC_PDF_NL")

# French terms (pp. 26-29)
_fr = {
    "CALME": 0, "CALME PLAT": 0, "CALME TOUT PLAT": 0,
    "BEAUCOUP DE CALME": 0, "IL A CALME": 0, "TOMBE": 0,
    "FAIBLE": 1, "FAIBLE BRISE": 1, "FRAICHEUR": 1,
    "BEAUCOUP MOLLI": 1, "PRESQUE CALME": 1,
    "BRISE FIABLE": 2, "LEGERE BRISE": 2, "MOLLI": 2, "MOU": 2, "VENT MOU": 2,
    "PETIT AIR": 3, "PETIT TEMPS": 3, "PETIT VENT": 3, "PETITE BRISE": 3,
    "BEAU PETIT FRAIS": 4, "BELLE BRISE": 4, "BIEN PETIT FRAIS": 4,
    "BON PETIT FRAIS": 4, "JOLI FRAIS": 4, "JOLI PETIT FRAIS": 4,
    "JOLIE BRISE": 4, "MANIABLE": 4, "PETIT FRAICHEUR": 4, "PETIT FRAIS": 4,
    "A PEU": 5, "BEAU": 5, "BEAU FRAIS": 5, "BON FRAIS": 5,
    "BON FRAIS AN PEU VIOLENT": 5, "BON FRAIS FRAISANT": 5,
    "BONNE BRISE": 5, "BRISE FRAICHE": 5, "PEU": 5,
    "PETIT VENT": 5, "PORTER LES PERROQUETS": 5,
    "AFFRAICHI": 6, "BRISE CARABINEE": 6, "FRAICHIR": 6, "FRAIS": 6,
    "VENT FRAIS": 6, "VENT MOINS IMPETEUX": 6,
    "BEAUCOUP DE VENT": 7, "BON GROS FRAIS": 7, "BRISE FORTE": 7,
    "FORT": 7, "FORTE": 7, "GRAND FRAIS": 7, "GRAND VENT": 7,
    "GROS": 7, "GROS FRAIS": 7, "GROSSE BRISE": 7,
    "CONSIDERABLEMENT": 8, "FORCE": 8, "SOUFFLANT IMPETUEUX": 8,
    "VENT FORCE": 8,
    "GROS VENT": 9, "EN TOURMENTE": 9,
    "COUP DE VENT": 10, "EXTREMEMENT FORT": 10, "TEMPETE": 10,
    "EXTREMEMENT VIOLENT": 11, "GRANDE VIOLENCE": 11, "VIOLENCE": 11, "VIOLENT": 11,
    "OURAGAN": 12, "TIPHON": 12, "TIFON": 12, "VIOLENT OURAGAN": 12,
    "PAR GRAINS": None,  # squalls - NDA
    "PAR GRAIN": None,   # squalls - NDA
    "ASSEZ FORT": 7,     # "rather strong" → BF 7
}
for term, bf in _fr.items():
    if term not in PDF_DICT and bf is not None:
        PDF_DICT[term] = (bf, "high", "CLIWOC_PDF_FR")

# ── NDA terms (no Beaufort assignment possible per CLIWOC PDF) ───────────────
NDA_TERMS = {
    # English
    "VARIABLE", "VARIABLES", "VARIABLE WINDS", "VARIABLE BREEZES",
    "VARIABLE WEATHER", "VARIABLE AND SQUALLY", "VARIABLE WINDS AND SQUALLY",
    "SQUALLY", "SQUALLS", "HARD SQUALLS", "SQUALLY WEATHER",
    "UNSETTLED", "UNSETTLED WINDS",
    "BAFFLING", "BAFFLING AIRS", "BAFFLING WINDS",
    "INCREASING", "DECREASING", "FRESHENING",
    # Spanish
    "CONTRARIOS", "CONTRASTADO", "VARIABLE Y CALMOSO",
    "VARIABLE Y CONTRASTADO", "MUY VARIABLE", "MUY VARIABLE Y CALMOSO",
    "RÁFAGAS", "RAFAGAS",
    "REGULAR", "REGULARCITO",
    "DESIGUAL", "INCONSTANTE", "FUGADAS", "FUGOSO",
    "CONSTANTE", "CONTRARIO", "FIRME",
    "EN AUMENTO", "EN FUGAS", "ARRECIANDO", "ARRECIO", "RECALMONES",
    "VENTOLINAS VARIABLES",
    # Dutch
    "ONGESTADIG", "ONGESTADIGE", "ONGELIJK", "ONGELIJKE KOELTE",
    "ZEER ONGESTADIG", "AFNEMEND", "AFNEMENDE WIND",
    "ONGESTADIGE LICHTE KOELTE",
    # French
    "INEGAL", "INÉGAL", "MEDIOCRE", "VARIABLE",
    "PAR GRAINS", "PAR GRAIN", "PAR RAFALES",
}

# ── Temporal prefixes to strip for compound parsing ──────────────────────────
TEMPORAL_PREFIXES = [
    "FIRST AND MIDDLE AND LATTER PARTS ",
    "FIRST AND MIDDLE PARTS ", "FIRST AND MIDDLE PART ",
    "MIDDLE AND LATTER PARTS ", "MIDDLE AND LATTER PART ",
    "FIRST AND LATTER PARTS ", "FIRST AND LATTER PART ",
    "FIRST PART OF THE NIGHT ", "LATTER PART OF THE NIGHT ",
    "FIRST PART ", "MIDDLE PART ", "LATTER PART ",
    "FIRST PARTS ", "MIDDLE PARTS ", "LATTER PARTS ",
    "FIRST HALF ", "SECOND HALF ", "LATTER HALF ",
    "FORMER PART ", "LATER PART ", "LATTER ",
    "FIRST AND MIDDLE ", "MIDDLE AND LATTER ",
    "FIRST ", "MIDDLE ",
    "PM ", "AM ",
]

# Modifier suffixes that don't change the base Beaufort value
MODIFIER_SUFFIXES = [
    " WITH HARD SQUALLS", " WITH HEAVY SQUALLS", " WITH SQUALLS",
    " AND SQUALLY WEATHER", " AND SQUALLY", " AND CLOUDY",
    " AND FAIR WEATHER", " AND FAIR", " AND HAZY",
    " AND PLEASANT WEATHER", " AND PLEASANT", " AND CLEAR",
    " AND RAINY", " AND RAIN",
    ", SQUALLY WEATHER", ", SQUALLY", ", CLOUDY",
    ", AM SQUALLY", ", PM SQUALLY",
    " WEATHER", " WIND", " WINDS",
]


def build_db_dictionary(conn):
    """Extract term → (beaufort, W) from records that DO have W values."""
    print("  Building dictionary from existing DB translations ...")
    cur = conn.cursor()
    cur.execute("""
        SELECT AllWindForces, CAST(W AS REAL) as w_val, COUNT(*) as cnt
        FROM observations
        WHERE W IS NOT NULL AND W != ''
        AND AllWindForces IS NOT NULL AND AllWindForces != ''
        GROUP BY AllWindForces, CAST(W AS REAL)
        ORDER BY AllWindForces, cnt DESC
    """)
    rows = cur.fetchall()

    # For each term, take the W with highest count
    db_dict = {}
    for term, w_val, cnt in rows:
        key = term.strip().upper()
        if key not in db_dict or cnt > db_dict[key][2]:
            db_dict[key] = (w_val, cnt, cnt)  # (w, count_for_this_w, total)

    print(f"    {len(db_dict):,} unique terms with W translations")
    return db_dict


def translate_term(term, db_dict, pdf_dict):
    """
    Translate a single AllWindForces term to Beaufort/W.

    Returns (beaufort, w_value, confidence, method, reasoning)
    """
    if not term or not term.strip():
        return None, None, None, None, "empty term"

    t = term.strip().upper()

    # ── Layer 1: Direct dictionary match ──
    # Try PDF dictionary first (authoritative)
    if t in pdf_dict:
        bf, conf, src = pdf_dict[t]
        return bf, BF_TO_W[bf], "high", "pdf_dict", f"Direct match in {src}"

    # Try DB dictionary (empirical)
    if t in db_dict:
        w_val = db_dict[t][0]
        count = db_dict[t][1]
        # Find closest Beaufort
        bf = w_to_beaufort(w_val)
        return bf, w_val, "high", "db_dict", f"DB match ({count} examples, W={w_val})"

    # ── Check if it's an NDA term ──
    if t in NDA_TERMS:
        return None, None, "high", "nda", "NDA per CLIWOC dictionary (variable/squally/etc)"

    # ── Layer 2: Compound temporal parsing ──
    result = parse_compound(t, db_dict, pdf_dict)
    if result is not None:
        return result

    # ── Layer 3: Pattern matching and fuzzy lookup ──
    result = fuzzy_match(t, db_dict, pdf_dict)
    if result is not None:
        return result

    # ── No match ──
    return None, None, None, "unmatched", f"Could not translate: {term}"


def w_to_beaufort(w):
    """Convert W (tenths m/s) to Beaufort."""
    bounds = [3, 16, 34, 55, 80, 108, 139, 172, 208, 245, 285, 327]
    for i, b in enumerate(bounds):
        if w < b:
            return i
    return 12


def parse_compound(t, db_dict, pdf_dict):
    """Parse compound temporal descriptions like 'PM FRESH BREEZES' or
    'FIRST PART MODERATE, LATTER FRESH GALES'."""

    # Split on comma/semicolon first
    parts = re.split(r'[,;]\s*', t)

    bf_values = []
    methods = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Strip temporal prefix
        base = strip_temporal(part)
        if base == part and len(parts) == 1:
            # No temporal prefix found and no comma split — not a compound
            # But still try stripping modifier suffixes
            base = strip_modifiers(base)
            if base == t:
                return None  # nothing changed

        base = strip_modifiers(base)

        if not base:
            continue

        # Look up the stripped base term
        bf = lookup_base(base, db_dict, pdf_dict)
        if bf is not None:
            bf_values.append(bf)
            methods.append(f"{part}→{base}→BF{bf}")
        elif base in NDA_TERMS:
            methods.append(f"{part}→NDA")
            # NDA parts don't contribute to average
        else:
            # Try further stripping
            base2 = strip_modifiers(strip_temporal(base))
            if base2 != base:
                bf2 = lookup_base(base2, db_dict, pdf_dict)
                if bf2 is not None:
                    bf_values.append(bf2)
                    methods.append(f"{part}→{base2}→BF{bf2}")

    if bf_values:
        avg_bf = round(sum(bf_values) / len(bf_values))
        avg_bf = max(0, min(12, avg_bf))
        w = BF_TO_W[avg_bf]
        reasoning = "Compound: " + "; ".join(methods)
        return avg_bf, w, "medium", "compound", reasoning

    return None


def strip_temporal(text):
    """Strip temporal prefixes from a wind description."""
    t = text.strip()
    for prefix in TEMPORAL_PREFIXES:
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
            break
    return t


def strip_modifiers(text):
    """Strip modifier suffixes from a wind description."""
    t = text.strip()
    for suffix in MODIFIER_SUFFIXES:
        if t.endswith(suffix):
            t = t[:-len(suffix)].strip()
            break
    return t


def lookup_base(base, db_dict, pdf_dict):
    """Look up a base wind term in dictionaries."""
    if base in pdf_dict:
        return pdf_dict[base][0]
    if base in db_dict:
        return w_to_beaufort(db_dict[base][0])
    # Try with/without trailing S (plurals)
    if base.endswith("S") and base[:-1] in pdf_dict:
        return pdf_dict[base[:-1]][0]
    if base + "S" in pdf_dict:
        return pdf_dict[base + "S"][0]
    # Try common simplifications
    for suffix in [" BREEZE", " GALE", " TRADE", " WIND"]:
        if base.endswith(suffix + "S"):
            alt = base[:-1]  # remove trailing S
            if alt in pdf_dict:
                return pdf_dict[alt][0]
    return None


def fuzzy_match(t, db_dict, pdf_dict):
    """Try fuzzy/pattern matching for terms not caught by compound parsing."""

    # FRESH → BF5 (abbreviation of FRESH BREEZES)
    simple_map = {
        "FRESH": 5, "FRESH AND SQUALLY": 5,
        "FREQUENT SQUALLS": None, "LIGHT SQUALLS": None,
        "VARIABLE WITH SQUALLS": None, "VARIABLE WINDS WITH SQUALLS": None,
        "WINDS VARIABLE": None, "MODERATE WEATHER": 4,
        "FRESH WEATHER": 5, "LIGHT WEATHER": 2,
        "HARD WEATHER": 8,
        # Dutch
        "MINDERE KOELTE": 2, "MEERDERE KOELTE": 4,
        "ONGELIJKE KOELTE": 2,
        "ONGESTADIGE LICHTE KOELTE": 1,
        "ONGESTADIGE KOELTE": 2,
        "ZEER ONGESTADIG": None,
        "AFNEMEND": None, "AFNEMENDE WIND": None,
        "TOENEMEND": None, "TOENEMENDE WIND": None,
        # Spanish compound
        "VARIABLE Y BONANCIBLE": 4, "VARIABLE Y CALMOSO": None,
        "BRISA GALENA": 2,  # calm/gentle breeze
        "ACELAJADO": 6,  # Spanish: under full sail → moderate-fresh
        "ALEGRE": 5,  # Spanish: lively → fresh
        # French
        "ASSEZ FORT": 7, "PAR RAFALES": None,
    }

    if t in simple_map:
        bf = simple_map[t]
        if bf is None:
            return None, None, "medium", "nda_fuzzy", f"NDA pattern: {t}"
        return bf, BF_TO_W[bf], "medium", "fuzzy", f"Pattern match: {t}→BF{bf}"

    # Try extracting ANY known base term from the text
    # Sort by length (longest first) to get most specific match
    all_terms = list(pdf_dict.keys())
    all_terms.sort(key=len, reverse=True)

    for known in all_terms:
        if len(known) >= 4 and known in t and known != t:
            bf = pdf_dict[known][0]
            return bf, BF_TO_W[bf], "low", "substring", f"Contains '{known}'→BF{bf}"

    # Try DB dictionary substring match
    db_terms = sorted(db_dict.keys(), key=len, reverse=True)
    for known in db_terms:
        if len(known) >= 6 and known in t and known != t:
            w = db_dict[known][0]
            bf = w_to_beaufort(w)
            if db_dict[known][1] >= 5:  # at least 5 examples
                return bf, w, "low", "db_substring", f"Contains '{known}'→W={w}"

    return None


def main():
    print("=" * 70)
    print("CLIWOC DATA CLEANING — PHASE 3: WIND FORCE TRANSLATION")
    print("=" * 70)

    conn = sqlite3.connect(DB_PATH)

    # ── Build dictionaries ──
    print("\n── Building Dictionaries ──")
    db_dict = build_db_dictionary(conn)
    print(f"  PDF dictionary: {len(PDF_DICT):,} terms")

    # ── Get untranslated terms ──
    print("\n── Loading untranslated records ──")
    df = pd.read_sql("""
        SELECT rowid, AllWindForces
        FROM observations
        WHERE (W IS NULL OR W = '')
        AND AllWindForces IS NOT NULL AND AllWindForces != ''
    """, conn)
    n_records = len(df)
    print(f"  {n_records:,} records with AllWindForces but no W")

    # Deduplicate
    unique_terms = df["AllWindForces"].unique()
    n_unique = len(unique_terms)
    print(f"  {n_unique:,} unique terms to translate")

    # ── Translate each unique term ──
    print("\n── Translating terms ──")
    translations = {}  # term → (bf, w, confidence, method, reasoning)

    for term in unique_terms:
        translations[term] = translate_term(term, db_dict, PDF_DICT)

    # ── Statistics ──
    by_method = defaultdict(int)
    by_confidence = defaultdict(int)
    n_with_bf = 0
    n_nda = 0
    n_unmatched = 0

    for term, (bf, w, conf, method, reasoning) in translations.items():
        by_method[method] = by_method.get(method, 0) + 1
        if conf:
            by_confidence[conf] = by_confidence.get(conf, 0) + 1
        if bf is not None:
            n_with_bf += 1
        elif method and "nda" in method:
            n_nda += 1
        else:
            n_unmatched += 1

    print(f"\n  Translation results ({n_unique} unique terms):")
    print(f"    With Beaufort value: {n_with_bf}")
    print(f"    NDA (no definition): {n_nda}")
    print(f"    Unmatched: {n_unmatched}")
    print(f"\n  By method:")
    for method, count in sorted(by_method.items(), key=lambda x: -x[1]):
        print(f"    {method}: {count}")
    print(f"\n  By confidence:")
    for conf, count in sorted(by_confidence.items(), key=lambda x: -x[1]):
        print(f"    {conf}: {count}")

    # Count records covered
    record_counts = df["AllWindForces"].value_counts()
    n_records_bf = sum(record_counts[t] for t in translations
                       if translations[t][0] is not None)
    n_records_nda = sum(record_counts[t] for t in translations
                        if translations[t][0] is None and translations[t][3]
                        and "nda" in translations[t][3])
    n_records_unmatched = n_records - n_records_bf - n_records_nda
    print(f"\n  Record coverage:")
    print(f"    With Beaufort: {n_records_bf:,} / {n_records:,} ({n_records_bf/n_records*100:.1f}%)")
    print(f"    NDA: {n_records_nda:,}")
    print(f"    Unmatched: {n_records_unmatched:,}")

    # Show unmatched terms (top 30)
    unmatched = [(t, record_counts[t]) for t, v in translations.items()
                 if v[0] is None and (v[3] is None or "nda" not in v[3])]
    unmatched.sort(key=lambda x: -x[1])
    if unmatched:
        print(f"\n  Top unmatched terms ({len(unmatched)} total):")
        for term, cnt in unmatched[:30]:
            print(f"    {cnt:4d}x  \"{term}\"")

    # ── Save translations to JSON ──
    print(f"\n── Saving translations to {JSON_PATH} ──")
    json_data = {}
    for term, (bf, w, conf, method, reasoning) in sorted(translations.items()):
        json_data[term] = {
            "beaufort": bf,
            "w_tenths_ms": w,
            "confidence": conf,
            "method": method,
            "reasoning": reasoning,
        }
    with open(JSON_PATH, "w") as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {len(json_data)} entries")

    # ── Update database ──
    print("\n── Updating database ──")

    # Add new columns if they don't exist
    cur = conn.cursor()
    for col, typ in [("W_corrected", "REAL"), ("beaufort_corrected", "INTEGER"),
                     ("qc_wind_llm_translated", "INTEGER"),
                     ("qc_wind_confidence", "TEXT")]:
        try:
            cur.execute(f"ALTER TABLE observations ADD COLUMN {col} {typ}")
        except sqlite3.OperationalError:
            pass  # column already exists

    # First: set W_corrected = W and beaufort_corrected = beaufort for all records
    # that already have W values
    print("  Setting W_corrected from existing W values ...")
    cur.execute("""
        UPDATE observations
        SET W_corrected = CAST(W AS REAL),
            beaufort_corrected = beaufort,
            qc_wind_llm_translated = 0,
            qc_wind_confidence = 'original'
        WHERE W IS NOT NULL AND W != ''
    """)

    # Now apply LLM translations
    print("  Applying translations to untranslated records ...")
    n_updated = 0
    n_nda_updated = 0

    for term, (bf, w, conf, method, reasoning) in translations.items():
        rowids = df.loc[df["AllWindForces"] == term, "rowid"].tolist()
        if not rowids:
            continue

        if bf is not None and w is not None:
            # We have a Beaufort translation
            placeholders = ",".join("?" * len(rowids))
            cur.execute(f"""
                UPDATE observations
                SET W_corrected = ?,
                    beaufort_corrected = ?,
                    qc_wind_llm_translated = 1,
                    qc_wind_confidence = ?
                WHERE rowid IN ({placeholders})
            """, [w, bf, conf or "low"] + rowids)
            n_updated += len(rowids)
        else:
            # NDA or unmatched
            placeholders = ",".join("?" * len(rowids))
            cur.execute(f"""
                UPDATE observations
                SET qc_wind_llm_translated = CASE WHEN ? IS NOT NULL THEN 1 ELSE 0 END,
                    qc_wind_confidence = ?
                WHERE rowid IN ({placeholders})
            """, [method, conf or "unmatched"] + rowids)
            n_nda_updated += len(rowids)

    conn.commit()
    print(f"  Updated {n_updated:,} records with Beaufort values")
    print(f"  Marked {n_nda_updated:,} records as NDA/unmatched")

    # Verify
    print("\n── Verification ──")
    for col in ["W_corrected", "beaufort_corrected"]:
        row = cur.execute(f"SELECT COUNT(*) FROM observations WHERE {col} IS NOT NULL").fetchone()
        print(f"  {col}: {row[0]:,} non-null")

    row = cur.execute("SELECT COUNT(*) FROM observations WHERE qc_wind_llm_translated = 1").fetchone()
    print(f"  qc_wind_llm_translated: {row[0]:,} records")

    for conf in ["original", "high", "medium", "low"]:
        row = cur.execute("SELECT COUNT(*) FROM observations WHERE qc_wind_confidence = ?", [conf]).fetchone()
        print(f"  confidence={conf}: {row[0]:,}")

    # Create index
    cur.execute("CREATE INDEX IF NOT EXISTS idx_obs_beaufort_corrected ON observations (beaufort_corrected)")
    conn.commit()

    # Sample
    sample = pd.read_sql("""
        SELECT AllWindForces, W, W_corrected, beaufort_corrected,
               qc_wind_llm_translated, qc_wind_confidence
        FROM observations
        WHERE qc_wind_llm_translated = 1 AND beaufort_corrected IS NOT NULL
        LIMIT 10
    """, conn)
    print(f"\n  Sample translated records:\n{sample.to_string()}")

    # ── Summary ──
    print("\n" + "=" * 70)
    print("PHASE 3 SUMMARY")
    print("=" * 70)
    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    w_orig = cur.execute("SELECT COUNT(*) FROM observations WHERE W IS NOT NULL AND W != ''").fetchone()[0]
    w_corrected = cur.execute("SELECT COUNT(*) FROM observations WHERE W_corrected IS NOT NULL").fetchone()[0]
    print(f"  Total records:         {total:,}")
    print(f"  Original W values:     {w_orig:,} ({w_orig/total*100:.1f}%)")
    print(f"  W_corrected (total):   {w_corrected:,} ({w_corrected/total*100:.1f}%)")
    print(f"  New translations:      {w_corrected - w_orig:,} records added")
    print(f"  Translation JSON:      {JSON_PATH}")

    conn.close()
    print(f"\nPhase 3 complete. Database: {DB_PATH}")


if __name__ == "__main__":
    main()
