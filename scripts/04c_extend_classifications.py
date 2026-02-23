"""
Phase 4c: Extend weather & sea state classifications with additional terms
found in the unmatched records, then re-apply to the database.

Adds ~200+ terms identified from the top unmatched descriptions.
"""

import json
import sqlite3
from pathlib import Path

BASE_DIR = Path("/home/jic823/climate")
OUT_DIR = BASE_DIR / "cleaned"
DB_PATH = OUT_DIR / "cliwoc_cleaned.db"
WEATHER_JSON = OUT_DIR / "weather_classifications.json"
SEA_STATE_JSON = OUT_DIR / "sea_state_classifications.json"

# ══════════════════════════════════════════════════════════════════════════════
# ADDITIONAL WEATHER TERMS (identified from top unmatched)
# ══════════════════════════════════════════════════════════════════════════════

EXTRA_WEATHER = {
    # English
    "UNSETTLED": ("CLOUDY", "high", "dict_ext", "Unsettled = disturbed/changeable"),
    "UNSETTLED WEATHER": ("CLOUDY", "high", "dict_ext", "Unsettled weather"),
    "VARIABLE": ("MIXED", "medium", "dict_ext", "Variable = changing conditions"),
    "VARIABLE WEATHER": ("MIXED", "medium", "dict_ext", "Variable weather"),
    "CLOSE": ("CLOUDY", "medium", "dict_ext", "Close = heavy/oppressive atmosphere"),
    "CLOSE WEATHER": ("CLOUDY", "medium", "dict_ext", "Close weather"),
    "SULTRY": ("FAIR", "high", "dict_ext", "Sultry = hot and humid, no precip"),
    "SULTRY WEATHER": ("FAIR", "high", "dict_ext", "Sultry weather"),
    "HOT SULTRY WEATHER": ("FAIR", "high", "dict_ext", "Hot sultry = hot/humid fair"),
    "HOT": ("FAIR", "medium", "dict_ext", "Hot weather, no precip"),
    "HOT WEATHER": ("FAIR", "medium", "dict_ext", "Hot weather"),
    "WARM": ("FAIR", "medium", "dict_ext", "Warm weather"),
    "WARM WEATHER": ("FAIR", "medium", "dict_ext", "Warm weather"),
    "COLD": ("FAIR", "medium", "dict_ext", "Cold weather, no precip info"),
    "COLD WEATHER": ("FAIR", "medium", "dict_ext", "Cold weather"),
    "FOLLOWING SEA": ("FAIR", "low", "dict_ext", "Following sea (sea state, not weather)"),
    "MODERATE AND CLOUDY": ("CLOUDY", "high", "dict_ext", "Compound: moderate + cloudy"),
    "FINE AND CLOUDY": ("CLOUDY", "high", "dict_ext", "Compound: fine + cloudy"),
    "MODERATE AND CLEAR": ("CLEAR", "high", "dict_ext", "Moderate + clear"),

    # Spanish horizon descriptions (very common in CLIWOC)
    "HORIZONTES PARDOS": ("CLOUDY", "high", "dict_ext", "Spanish: brownish/gray horizons"),
    "HORIZONTES ABRISADOS": ("FAIR", "high", "dict_ext", "Spanish: trade wind horizons = favorable"),
    "CIELOS Y HORIZONTES ABRISADOS": ("FAIR", "high", "dict_ext", "Spanish: skies and horizons with trades"),
    "HORIZONTES ACHUBASCADOS": ("SHOWERS", "high", "dict_ext", "Spanish: squally/showery horizons"),
    "CIELOS Y HORIZONTES ACHUBASCADOS": ("SHOWERS", "high", "dict_ext", "Spanish: squally skies"),
    "HORIZONTES ATURBONADOS": ("SQUALL", "high", "dict_ext", "Spanish: squall-like horizons"),
    "CIELOS Y HORIZONTES ATURBONADOS": ("SQUALL", "high", "dict_ext", "Spanish: squall-like skies"),
    "CIELOS Y HORIZONTES TOLDADOS": ("OVERCAST", "high", "dict_ext", "Spanish: awning-covered skies"),
    "HORIZONTES TOLDADOS": ("OVERCAST", "high", "dict_ext", "Spanish: covered horizons"),
    "HORIZONTES OFUSCADOS": ("CLOUDY", "high", "dict_ext", "Spanish: darkened horizons"),
    "CIELOS Y HORIZONTES OFUSCADOS": ("CLOUDY", "high", "dict_ext", "Spanish: darkened skies"),
    "HORIZONTES NUBLADOS": ("CLOUDY", "high", "dict_ext", "Spanish: cloudy horizons"),
    "CIELOS Y HORIZONTES NUBLADOS": ("CLOUDY", "high", "dict_ext", "Spanish: cloudy skies"),
    "HORIZONTES OSCUROS": ("CLOUDY", "high", "dict_ext", "Spanish: dark horizons"),
    "CIELOS Y HORIZONTES OSCUROS": ("CLOUDY", "high", "dict_ext", "Spanish: dark skies"),
    "HORIZONTES AGUACERADOS": ("RAIN", "high", "dict_ext", "Spanish: rain-shower horizons"),
    "CIELOS Y HORIZONTES AGUACERADOS": ("RAIN", "high", "dict_ext", "Spanish: rainy skies"),
    "HORIZONTES CARGADOS CON ALGUNOS CHUBASCOS": ("SHOWERS", "high", "dict_ext", "Spanish: charged horizons with showers"),
    "CARGADOS DE MAL SEMBLANTE": ("CLOUDY", "high", "dict_ext", "Spanish: charged with bad appearance"),
    "ACELAJADO": ("CLOUDY", "high", "dict_ext", "Spanish: clouded over"),
    "SIN NOVEDAD": ("FAIR", "high", "dict_ext", "Spanish: nothing notable = fair"),
    "ACHUBASCADO": ("SHOWERS", "high", "dict_ext", "Spanish: squally/showery"),
    "CALIMOSO": ("HAZE", "high", "dict_ext", "Spanish: hazy"),
    "CALINOSO": ("HAZE", "high", "dict_ext", "Spanish: hazy"),
    "ABONANZADO": ("FAIR", "high", "dict_ext", "Spanish: calming/fair"),
    "ANUBARRADO": ("CLOUDY", "high", "dict_ext", "Spanish: very cloudy"),
    "ATURBONADO": ("SQUALL", "high", "dict_ext", "Spanish: squally"),
    "CERRAZON": ("FOG", "high", "dict_ext", "Spanish: thick fog/overcast"),
    "CELAJES": ("CLOUDY", "medium", "dict_ext", "Spanish: cloud formations"),
    "CELAJE": ("CLOUDY", "medium", "dict_ext", "Spanish: cloud formation"),
    "BRUMOSO": ("HAZE", "high", "dict_ext", "Spanish: hazy/misty"),
    "GARUANDO": ("DRIZZLE", "high", "dict_ext", "Spanish: drizzling"),
    "LLOVIENDO": ("RAIN", "high", "dict_ext", "Spanish: raining"),
    "LLOVIZNANDO": ("DRIZZLE", "high", "dict_ext", "Spanish: drizzling"),
    "NEBLINA": ("FOG", "high", "dict_ext", "Spanish: mist/fog"),
    "HORIZONTES CERRADOS Y ACHUBASCADOS": ("SHOWERS", "high", "dict_ext", "Spanish: closed/showery horizons"),
    "HORIZONTES CLAROS Y ABRISADOS": ("CLEAR", "high", "dict_ext", "Spanish: clear trade-wind horizons"),
    "CIELOS CLAROS Y HORIZONTES ABRISADOS": ("CLEAR", "high", "dict_ext", "Spanish: clear skies, trade horizons"),
    "HORIZONTES CARGADOS Y ACHUBASCADOS": ("SHOWERS", "high", "dict_ext", "Spanish: charged/showery horizons"),

    # Dutch
    "PASSAAT": ("FAIR", "high", "dict_ext", "Dutch: trade wind = steady fair weather"),
    "PASSAAT WEER": ("FAIR", "high", "dict_ext", "Dutch: trade wind weather"),
    "OOK DROOG WEER": ("FAIR", "high", "dict_ext", "Dutch: also dry weather"),
    "DROOG WEER": ("FAIR", "high", "dict_ext", "Dutch: dry weather"),
    "DROOG": ("FAIR", "medium", "dict_ext", "Dutch: dry"),
    "BUIJIG": ("SHOWERS", "high", "dict_ext", "Dutch variant of buiig = showery"),
    "BUIJIG WEER": ("SHOWERS", "high", "dict_ext", "Dutch: showery weather"),
    "WOLKDRIJVENDE LUCHT": ("CLOUDY", "high", "dict_ext", "Dutch: cloud-drifting sky"),
    "BUIEN VAN WIND": ("SQUALL", "high", "dict_ext", "Dutch: gusts/squalls of wind"),
    "STORMWEER": ("STORM", "high", "dict_ext", "Dutch: storm weather"),
    "ONGESTADIG WEER": ("MIXED", "high", "dict_ext", "Dutch: unsteady weather"),
    "ONGESTADIG": ("MIXED", "high", "dict_ext", "Dutch: unsteady"),
    "REGENBUIJIG": ("SHOWERS", "high", "dict_ext", "Dutch: rain-showery"),
    "DONDERWEER": ("THUNDER", "high", "dict_ext", "Dutch: thunder weather"),
    "DONDERBUI": ("THUNDER", "high", "dict_ext", "Dutch: thunderstorm"),
    "ONWEER": ("THUNDER", "high", "dict_ext", "Dutch: thunderstorm"),
    "SLAGREGENS": ("RAIN", "high", "dict_ext", "Dutch: heavy rain"),
    "SLAGREGEN": ("RAIN", "high", "dict_ext", "Dutch: heavy rain"),
    "VERANDERLIJKE LUCHT": ("MIXED", "high", "dict_ext", "Dutch: changeable sky"),
    "DRUKKEND WEER": ("FAIR", "medium", "dict_ext", "Dutch: oppressive/muggy weather"),
    "DAMP": ("HAZE", "medium", "dict_ext", "Dutch: mist/haze"),
    "DAMPIG WEER": ("HAZE", "high", "dict_ext", "Dutch: hazy weather"),
    "SNEEUWJACHT": ("SNOW", "high", "dict_ext", "Dutch: blowing snow"),
    "HAGELBUIEN": ("SNOW", "high", "dict_ext", "Dutch: hail showers"),

    # French
    "PAR GRAINS": ("SHOWERS", "high", "dict_ext", "French: by squalls/showers"),
    "NÉBULEUX": ("CLOUDY", "high", "dict_ext", "French: nebulous/cloudy"),
    "NEBULEUX": ("CLOUDY", "high", "dict_ext", "French: nebulous/cloudy (no accent)"),
    "TEMPS VARIABLE": ("MIXED", "high", "dict_ext", "French: variable weather"),
    "CIEL NEBULEUX": ("CLOUDY", "high", "dict_ext", "French: nebulous sky"),
    "VARIABLE ET COUVERT": ("CLOUDY", "high", "dict_ext", "French: variable and overcast"),
    "BEAU ET CLAIR": ("CLEAR", "high", "dict_ext", "French: beautiful and clear"),
    "EMBRUMÉ": ("HAZE", "high", "dict_ext", "French: misty/hazy"),
    "ORAGEUX": ("THUNDER", "high", "dict_ext", "French: stormy/thundery"),
    "CALME": ("CLEAR", "medium", "dict_ext", "French: calm (weather context)"),

    # CLIWOC codes not in original dict
    "W11": ("HAZE", "medium", "dict_ext", "CLIWOC code W11 - probable haze/mist variant"),
}

# ══════════════════════════════════════════════════════════════════════════════
# ADDITIONAL SEA STATE TERMS
# ══════════════════════════════════════════════════════════════════════════════

EXTRA_SEA_STATE = {
    # Spanish
    "CRECIDA": (5, "high", "dict_ext", "Spanish: swollen/grown sea"),
    "MUY CRECIDA": (6, "high", "dict_ext", "Spanish: very swollen sea"),
    "GRANDE": (5, "high", "dict_ext", "Spanish: large sea"),
    "MUY GRANDE": (6, "high", "dict_ext", "Spanish: very large sea"),
    "APACIBLE": (1, "high", "dict_ext", "Spanish: gentle/calm sea"),
    "BUENA": (1, "high", "dict_ext", "Spanish: good/nice sea"),
    "DEL VIENTO": (4, "medium", "dict_ext", "Spanish: wind sea (from current wind)"),
    "DEL VTO": (4, "medium", "dict_ext", "Spanish abbrev: wind sea"),
    "CONTRASTADA": (4, "high", "dict_ext", "Spanish: contrasted/opposing seas"),
    "ALTIBA": (5, "high", "dict_ext", "Spanish: high/proud sea (variant of altiva)"),
    "ALTIVA": (5, "high", "dict_ext", "Spanish: high/proud sea"),
    "MUCHA": (5, "high", "dict_ext", "Spanish: much sea / heavy sea"),
    "ALTERADA": (4, "high", "dict_ext", "Spanish: disturbed sea"),
    "PROPORCIONADA": (3, "medium", "dict_ext", "Spanish: proportionate/moderate sea"),
    "ENCONTRADA": (4, "high", "dict_ext", "Spanish: opposing/cross sea"),
    "CORTA": (3, "medium", "dict_ext", "Spanish: short sea"),
    "LARGA": (3, "medium", "dict_ext", "Spanish: long sea"),
    "TENDIDA": (3, "medium", "dict_ext", "Spanish: stretched out sea"),
    "SORDA": (2, "high", "dict_ext", "Spanish: dead/muffled swell"),
    "ABONANZADA": (1, "high", "dict_ext", "Spanish: calming sea"),

    # Spanish directional seas (del N, del NE, etc.) - moderate by default
    "DEL NO": (3, "medium", "dict_ext", "Spanish: sea from NW"),
    "DEL NE": (3, "medium", "dict_ext", "Spanish: sea from NE"),
    "DEL SE": (3, "medium", "dict_ext", "Spanish: sea from SE"),
    "DEL SO": (3, "medium", "dict_ext", "Spanish: sea from SW"),
    "DEL N": (3, "medium", "dict_ext", "Spanish: sea from N"),
    "DEL S": (3, "medium", "dict_ext", "Spanish: sea from S"),
    "DEL E": (3, "medium", "dict_ext", "Spanish: sea from E"),
    "DEL O": (3, "medium", "dict_ext", "Spanish: sea from W"),
    "DEL NOROESTE": (3, "medium", "dict_ext", "Spanish: sea from NW (full)"),
    "DEL NORDESTE": (3, "medium", "dict_ext", "Spanish: sea from NE (full)"),
    "DEL SUDESTE": (3, "medium", "dict_ext", "Spanish: sea from SE (full)"),
    "DEL SUDOESTE": (3, "medium", "dict_ext", "Spanish: sea from SW (full)"),

    # English swell directions
    "SWELL": (3, "medium", "dict_ext", "General swell"),
    "SWELL FROM SW": (3, "medium", "dict_ext", "Swell from SW"),
    "SWELL FROM S": (3, "medium", "dict_ext", "Swell from S"),
    "SWELL FROM SE": (3, "medium", "dict_ext", "Swell from SE"),
    "SWELL FROM W": (3, "medium", "dict_ext", "Swell from W"),
    "SWELL FROM NW": (3, "medium", "dict_ext", "Swell from NW"),
    "SWELL FROM E": (3, "medium", "dict_ext", "Swell from E"),
    "SWELL FROM NE": (3, "medium", "dict_ext", "Swell from NE"),
    "SWELL FROM N": (3, "medium", "dict_ext", "Swell from N"),
    "SW SWELL": (3, "medium", "dict_ext", "SW swell"),
    "NW SWELL": (3, "medium", "dict_ext", "NW swell"),
    "SE SWELL": (3, "medium", "dict_ext", "SE swell"),
    "NE SWELL": (3, "medium", "dict_ext", "NE swell"),
    "N SWELL": (3, "medium", "dict_ext", "N swell"),
    "S SWELL": (3, "medium", "dict_ext", "S swell"),
    "W SWELL": (3, "medium", "dict_ext", "W swell"),
    "E SWELL": (3, "medium", "dict_ext", "E swell"),
    "LARGE SWELL": (5, "high", "dict_ext", "Large swell"),
    "LARGE SW SWELL": (5, "high", "dict_ext", "Large SW swell"),
    "LARGE NW SWELL": (5, "high", "dict_ext", "Large NW swell"),
    "LONG SWELL": (3, "medium", "dict_ext", "Long period swell"),
    "HEAVY SWELL": (5, "high", "dict_ext", "Heavy swell"),
    "FOLLOWING SEA": (3, "medium", "dict_ext", "Following sea"),
    "LARGE FOLLOWING SEA": (5, "high", "dict_ext", "Large following sea"),
    "HEAD SEA": (4, "medium", "dict_ext", "Head sea (opposing)"),
    "CROSS SEA": (4, "medium", "dict_ext", "Cross sea"),
    "GREAT SEA": (5, "high", "dict_ext", "Great sea"),

    # Dutch
    "AANSCHIETENDE ZEE": (4, "high", "dict_ext", "Dutch: approaching/building sea"),
    "HOGE AANSCHIETENDE ZEE": (5, "high", "dict_ext", "Dutch: high approaching sea"),
    "AFNEMENDE ZEE": (3, "high", "dict_ext", "Dutch: diminishing sea"),
    "MOEILIJKE ZEE": (5, "high", "dict_ext", "Dutch: difficult sea"),
    "KALM": (0, "high", "dict_ext", "Dutch: calm"),
    "KALME ZEE": (0, "high", "dict_ext", "Dutch: calm sea"),
    "STERKE RAVELING VAN STROOM": (4, "medium", "dict_ext", "Dutch: strong current tide rip"),
    "HOGE ZEE": (5, "high", "dict_ext", "Dutch: high sea"),
    "WOELIGE ZEE": (5, "high", "dict_ext", "Dutch: turbulent sea"),
    "RUWE ZEE": (5, "high", "dict_ext", "Dutch: rough sea"),
    "HOOGE ZEE": (5, "high", "dict_ext", "Dutch archaic: high sea"),
    "STIJVE ZEE": (4, "high", "dict_ext", "Dutch: stiff sea"),
    "STOMPE ZEE": (3, "medium", "dict_ext", "Dutch: blunt/short sea"),
    "LANGE DEINING": (3, "medium", "dict_ext", "Dutch: long swell"),
    "KORTE DEINING": (2, "medium", "dict_ext", "Dutch: short swell"),

    # French
    "BELLE": (1, "high", "dict_ext", "French: beautiful/calm sea"),
    "GROSSE": (5, "high", "dict_ext", "French: large sea"),
    "CALME": (0, "high", "dict_ext", "French: calm sea"),
}


def main():
    print("=" * 70)
    print("PHASE 4c: EXTEND CLASSIFICATIONS + RE-APPLY")
    print("=" * 70)

    # ── Load and extend weather JSON ──
    print("\nLoading weather_classifications.json ...")
    with open(WEATHER_JSON) as f:
        weather_map = json.load(f)

    added_w = 0
    for term, (cat, conf, method, reasoning) in EXTRA_WEATHER.items():
        # Check both exact case and upper case
        if term not in weather_map and term.upper() not in weather_map:
            weather_map[term] = {
                "category": cat, "confidence": conf,
                "method": method, "reasoning": reasoning,
            }
            added_w += 1
        elif term in weather_map and weather_map[term]["category"] is None:
            weather_map[term] = {
                "category": cat, "confidence": conf,
                "method": method, "reasoning": reasoning,
            }
            added_w += 1

    print(f"  Added/updated {added_w} weather terms")

    # Also do a pattern sweep: match any unmatched term that contains known keywords
    import re
    # Spanish horizon patterns (very common structure)
    horizon_patterns = [
        (r"HORIZONTES?\s+(CLAROS?|ABRISADOS?)", "CLEAR"),
        (r"CIELOS?\s+Y\s+HORIZONTES?\s+(CLAROS?|ABRISADOS?)", "CLEAR"),
        (r"HORIZONTES?\s+(PARDOS?|OSCUROS?|OFUSCADOS?|NUBLADOS?|CARGADOS?)", "CLOUDY"),
        (r"CIELOS?\s+Y\s+HORIZONTES?\s+(PARDOS?|OSCUROS?|OFUSCADOS?|NUBLADOS?|CARGADOS?)", "CLOUDY"),
        (r"HORIZONTES?\s+(ACHUBASCADOS?|CHUBASC)", "SHOWERS"),
        (r"CIELOS?\s+Y\s+HORIZONTES?\s+(ACHUBASCADOS?|CHUBASC)", "SHOWERS"),
        (r"HORIZONTES?\s+(ATURBONADOS?|TURBONADOS?)", "SQUALL"),
        (r"CIELOS?\s+Y\s+HORIZONTES?\s+(ATURBONADOS?|TURBONADOS?)", "SQUALL"),
        (r"HORIZONTES?\s+(TOLDADOS?|CERRADOS?)", "OVERCAST"),
        (r"CIELOS?\s+Y\s+HORIZONTES?\s+(TOLDADOS?|CERRADOS?)", "OVERCAST"),
        (r"HORIZONTES?\s+(AGUACERADOS?)", "RAIN"),
        (r"CIELOS?\s+Y\s+HORIZONTES?\s+(AGUACERADOS?)", "RAIN"),
    ]
    horizon_compiled = [(re.compile(p, re.IGNORECASE), c) for p, c in horizon_patterns]

    pattern_added_w = 0
    for term, info in weather_map.items():
        if info["category"] is None:
            for pat, cat in horizon_compiled:
                if pat.search(term):
                    info["category"] = cat
                    info["confidence"] = "medium"
                    info["method"] = "pattern_ext"
                    info["reasoning"] = f"Spanish horizon pattern match: {term}"
                    pattern_added_w += 1
                    break
    print(f"  Pattern-matched {pattern_added_w} additional weather terms (Spanish horizons)")

    # ── Load and extend sea state JSON ──
    print("\nLoading sea_state_classifications.json ...")
    with open(SEA_STATE_JSON) as f:
        sea_map = json.load(f)

    added_s = 0
    for term, (scale, conf, method, reasoning) in EXTRA_SEA_STATE.items():
        if term not in sea_map and term.upper() not in sea_map:
            sea_map[term] = {
                "douglas_scale": scale, "confidence": conf,
                "method": method, "reasoning": reasoning,
            }
            added_s += 1
        elif term in sea_map and sea_map[term]["douglas_scale"] is None:
            sea_map[term] = {
                "douglas_scale": scale, "confidence": conf,
                "method": method, "reasoning": reasoning,
            }
            added_s += 1

    # Pattern sweep for swell directions
    swell_pattern_added = 0
    swell_re = re.compile(r"^(LARGE\s+)?(LONG\s+)?(HEAVY\s+)?SWELL\s+FROM\s+\w+$", re.IGNORECASE)
    large_swell_re = re.compile(r"^LARGE\s+", re.IGNORECASE)
    heavy_swell_re = re.compile(r"^HEAVY\s+", re.IGNORECASE)
    for term, info in sea_map.items():
        if info["douglas_scale"] is None:
            if swell_re.match(term):
                if large_swell_re.match(term) or heavy_swell_re.match(term):
                    info["douglas_scale"] = 5
                else:
                    info["douglas_scale"] = 3
                info["confidence"] = "medium"
                info["method"] = "pattern_ext"
                info["reasoning"] = f"Swell direction pattern: {term}"
                swell_pattern_added += 1
    print(f"  Added/updated {added_s} sea state terms")
    print(f"  Pattern-matched {swell_pattern_added} additional swell terms")

    # ── Save updated JSON files ──
    print("\nSaving updated JSON files ...")
    with open(WEATHER_JSON, "w") as f:
        json.dump(weather_map, f, indent=2, ensure_ascii=False)
    with open(SEA_STATE_JSON, "w") as f:
        json.dump(sea_map, f, indent=2, ensure_ascii=False)

    # ── Re-apply to database (same efficient approach as 04b) ──
    print("\n── Re-applying to database ──")

    weather_pairs = [(term, info["category"])
                     for term, info in weather_map.items()
                     if info.get("category")]
    sea_pairs = [(term, info["douglas_scale"])
                 for term, info in sea_map.items()
                 if info.get("douglas_scale") is not None]

    print(f"  Weather: {len(weather_pairs):,} classified terms")
    print(f"  Sea state: {len(sea_pairs):,} classified terms")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Clear and re-apply
    cur.execute("UPDATE observations SET weather_category = NULL, sea_state = NULL")
    conn.commit()

    # Weather via temp table
    print("\n  Applying weather ...")
    cur.execute("CREATE TEMP TABLE weather_map (term TEXT PRIMARY KEY, category TEXT)")
    for i in range(0, len(weather_pairs), 500):
        cur.executemany("INSERT OR IGNORE INTO weather_map VALUES (?, ?)",
                        weather_pairs[i:i+500])
    conn.commit()

    cur.execute("""
        UPDATE observations
        SET weather_category = (
            SELECT category FROM weather_map WHERE weather_map.term = observations.Weather
        )
        WHERE Weather IN (SELECT term FROM weather_map)
    """)
    w_updated = cur.rowcount
    conn.commit()
    print(f"    Updated {w_updated:,} records")

    # Sea state via temp table
    print("  Applying sea state ...")
    cur.execute("CREATE TEMP TABLE sea_map (term TEXT PRIMARY KEY, scale INTEGER)")
    for i in range(0, len(sea_pairs), 500):
        cur.executemany("INSERT OR IGNORE INTO sea_map VALUES (?, ?)",
                        sea_pairs[i:i+500])
    conn.commit()

    cur.execute("""
        UPDATE observations
        SET sea_state = (
            SELECT scale FROM sea_map WHERE sea_map.term = observations.StateSea
        )
        WHERE StateSea IN (SELECT term FROM sea_map)
    """)
    s_updated = cur.rowcount
    conn.commit()
    print(f"    Updated {s_updated:,} records")

    # ── Verification ──
    print("\n── Verification ──")
    total = cur.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    w_text = cur.execute("SELECT COUNT(*) FROM observations WHERE Weather IS NOT NULL AND Weather != ''").fetchone()[0]
    s_text = cur.execute("SELECT COUNT(*) FROM observations WHERE StateSea IS NOT NULL AND StateSea != ''").fetchone()[0]
    w_done = cur.execute("SELECT COUNT(*) FROM observations WHERE weather_category IS NOT NULL").fetchone()[0]
    s_done = cur.execute("SELECT COUNT(*) FROM observations WHERE sea_state IS NOT NULL").fetchone()[0]

    print(f"  weather_category: {w_done:,} / {w_text:,} with text ({w_done/w_text*100:.1f}%)")
    print(f"  sea_state:        {s_done:,} / {s_text:,} with text ({s_done/s_text*100:.1f}%)")
    print(f"  Unmatched weather: {w_text - w_done:,} ({(w_text-w_done)/w_text*100:.1f}%)")
    print(f"  Unmatched sea state: {s_text - s_done:,} ({(s_text-s_done)/s_text*100:.1f}%)")

    print("\n  Weather category distribution:")
    for cat, cnt in cur.execute("""
        SELECT weather_category, COUNT(*) FROM observations
        WHERE weather_category IS NOT NULL
        GROUP BY weather_category ORDER BY COUNT(*) DESC
    """).fetchall():
        print(f"    {cat:12s}: {cnt:,}")

    douglas_labels = {
        0: "Calm (glassy)", 1: "Calm (rippled)", 2: "Smooth",
        3: "Slight", 4: "Moderate", 5: "Rough",
        6: "Very rough", 7: "High", 8: "Very high", 9: "Phenomenal",
    }
    print("\n  Sea state distribution:")
    for scale, cnt in cur.execute("""
        SELECT sea_state, COUNT(*) FROM observations
        WHERE sea_state IS NOT NULL
        GROUP BY sea_state ORDER BY sea_state
    """).fetchall():
        print(f"    {scale} ({douglas_labels.get(scale,'?'):17s}): {cnt:,}")

    # Remaining top unmatched
    print("\n  Top 15 remaining unmatched weather:")
    for term, cnt in cur.execute("""
        SELECT Weather, COUNT(*) FROM observations
        WHERE Weather IS NOT NULL AND Weather != '' AND weather_category IS NULL
        GROUP BY Weather ORDER BY COUNT(*) DESC LIMIT 15
    """).fetchall():
        print(f"    {cnt:5d}x  \"{term}\"")

    print("\n  Top 15 remaining unmatched sea state:")
    for term, cnt in cur.execute("""
        SELECT StateSea, COUNT(*) FROM observations
        WHERE StateSea IS NOT NULL AND StateSea != '' AND sea_state IS NULL
        GROUP BY StateSea ORDER BY COUNT(*) DESC LIMIT 15
    """).fetchall():
        print(f"    {cnt:5d}x  \"{term}\"")

    conn.close()
    print(f"\nPhase 4c complete. Database: {DB_PATH}")


if __name__ == "__main__":
    main()
