"""Decode a raw METAR string into plain-English weather information."""

import math
import re

COMPASS = [
    "north", "north-northeast", "northeast", "east-northeast",
    "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest",
    "west", "west-northwest", "northwest", "north-northwest",
]

DESCRIPTORS = {
    "MI": "shallow", "BC": "patches of", "PR": "partial", "DR": "low drifting",
    "BL": "blowing", "SH": "showers of", "TS": "thunderstorm with",
    "FZ": "freezing",
}

PHENOMENA = {
    "DZ": "drizzle", "RA": "rain", "SN": "snow", "SG": "snow grains",
    "IC": "ice crystals", "PL": "ice pellets", "GR": "hail",
    "GS": "small hail", "UP": "unknown precipitation", "BR": "mist",
    "FG": "fog", "FU": "smoke", "VA": "volcanic ash", "DU": "dust",
    "SA": "sand", "HZ": "haze", "PY": "spray", "PO": "dust whirls",
    "SQ": "squalls", "FC": "funnel cloud", "SS": "sandstorm",
    "DS": "duststorm",
}

# Short words used in the one-line headline.
HEADLINE_WORDS = {
    "TS": "Thunderstorms", "FG": "Foggy", "FZFG": "Freezing fog",
    "BR": "Misty", "HZ": "Hazy", "FU": "Smoky", "DU": "Dusty",
    "SA": "Sandy", "VA": "Volcanic ash", "SQ": "Squalls", "FC": "Funnel cloud",
    "SS": "Sandstorm", "DS": "Duststorm", "RA": "Rainy", "DZ": "Drizzly",
    "SN": "Snowy", "SG": "Snowy", "GR": "Hail", "GS": "Hail", "PL": "Sleet",
    "IC": "Ice crystals", "UP": "Precipitation",
}

CLOUD_COVER = {
    "FEW": "a few clouds", "SCT": "scattered clouds",
    "BKN": "broken clouds (mostly cloudy)", "OVC": "overcast",
}

SKY_HEADLINE = {
    "CLR": "Clear skies", "SKC": "Clear skies", "NSC": "Clear skies",
    "NCD": "Clear skies", "CAVOK": "Clear skies", "FEW": "Mostly clear",
    "SCT": "Partly cloudy", "BKN": "Mostly cloudy", "OVC": "Overcast",
    "VV": "Sky obscured",
}

WX_FULL_RE = re.compile(
    r"^(?P<int>[-+]|VC)?(?P<desc>(?:MI|BC|PR|DR|BL|SH|TS|FZ)*)"
    r"(?P<phen>(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*)$"
)
WIND_RE = re.compile(r"^(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS|KMH)$")
VIS_SM_RE = re.compile(r"^(M|P)?(\d+(?:/\d+)?)SM$")
CLOUD_RE = re.compile(r"^(FEW|SCT|BKN|OVC|VV)(\d{3}|///)(CB|TCU)?$")
TEMP_RE = re.compile(r"^(M?\d{2})/(M?\d{2})?$")
ALTIM_RE = re.compile(r"^([QA])(\d{4})$")
TIME_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})Z$")


def c_to_f(c):
    return c * 9 / 5 + 32


def knots_to_mph(kt):
    return kt * 1.15078


def compass(deg):
    return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def _temp(token):
    return -int(token[1:]) if token.startswith("M") else int(token)


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def describe_weather(token):
    """Turn a present-weather group like '-TSRA' or 'BR' into English, or None."""
    m = WX_FULL_RE.match(token)
    if not m or not token or token in ("-", "+", "VC"):
        return None
    if not m.group("desc") and not m.group("phen"):
        return None
    intensity = m.group("int")
    desc = re.findall(r"MI|BC|PR|DR|BL|SH|TS|FZ", m.group("desc") or "")
    phen = re.findall(r"DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS",
                      m.group("phen") or "")
    words = [DESCRIPTORS[d] for d in desc] + [PHENOMENA[p] for p in phen]
    # "thunderstorm with" alone reads oddly; drop the dangling preposition.
    text = " ".join(words)
    if text.endswith(" with") or text.endswith(" of"):
        text = text.rsplit(" ", 1)[0]
    if intensity == "-":
        text = "light " + text
    elif intensity == "+":
        text = "heavy " + text
    elif intensity == "VC":
        text += " in the vicinity"
    return text


def _headline_word(token):
    m = WX_FULL_RE.match(token)
    if not m:
        return None
    desc = m.group("desc") or ""
    phen = m.group("phen") or ""
    if "TS" in desc:
        word = HEADLINE_WORDS["TS"]
    elif desc.startswith("FZ") and phen == "FG":
        word = HEADLINE_WORDS["FZFG"]
    else:
        first = re.findall(r"DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS", phen)
        if not first:
            return None
        word = HEADLINE_WORDS[first[0]]
        if "SH" in desc and first[0] == "RA":
            word = "Showery"
    if m.group("int") == "-":
        word = "Light " + word.lower()
    elif m.group("int") == "+":
        word = "Heavy " + word.lower()
    return word


def flight_category(visibility_m, ceiling_ft):
    """Return VFR / MVFR / IFR / LIFR using the standard thresholds."""
    sm = visibility_m / 1609.34 if visibility_m is not None else 99
    ft = ceiling_ft if ceiling_ft is not None else 99999
    if sm < 1 or ft < 500:
        return "LIFR"
    if sm < 3 or ft < 1000:
        return "IFR"
    if sm <= 5 or ft <= 3000:
        return "MVFR"
    return "VFR"


FLIGHT_CAT_TEXT = {
    "VFR": "Good visibility and high clouds, easy flying conditions.",
    "MVFR": "Marginal: somewhat reduced visibility or low clouds.",
    "IFR": "Poor visibility or low clouds; pilots need instrument rules.",
    "LIFR": "Very poor visibility or very low clouds.",
}


def humidity(temp_c, dew_c):
    """Relative humidity in percent (Magnus approximation)."""
    a, b = 17.625, 243.04
    return round(100 * math.exp(a * dew_c / (b + dew_c) - a * temp_c / (b + temp_c)))


def describe_visibility_m(meters):
    miles = meters / 1609.34
    if meters >= 9999:
        return "10 km or more (excellent)"
    if miles >= 1:
        return f"about {miles:.1f} miles ({meters / 1000:.1f} km)".replace(".0 miles", " miles")
    return f"under a mile ({meters} m)"


def decode_metar(raw):
    """Decode a raw METAR string. Returns a dict ready for the template."""
    tokens = raw.strip().split()
    out = {
        "raw": raw.strip(),
        "station": None,
        "day": None, "hour": None, "minute": None,
        "auto": False,
        "wind": None,
        "visibility": None,
        "weather": [],
        "clouds": [],
        "temp_c": None, "dew_c": None,
        "pressure": None,
        "notes": [],
    }
    vis_m = None
    ceiling_ft = None
    cavok = False
    sky_codes = []
    headline_wx = []
    wind_dir = None
    wind_kt = 0

    i = 0
    if tokens and tokens[0] in ("METAR", "SPECI"):
        if tokens[0] == "SPECI":
            out["notes"].append("This is a special (unscheduled) report issued because conditions changed.")
        i = 1
    if i < len(tokens) and re.fullmatch(r"[A-Z][A-Z0-9]{3}", tokens[i]):
        out["station"] = tokens[i]
        i += 1

    for idx in range(i, len(tokens)):
        tok = tokens[idx]
        if tok == "RMK":
            break
        if tok in ("TEMPO", "BECMG", "NOSIG"):
            if tok == "NOSIG":
                out["notes"].append("No significant change expected in the next two hours.")
            else:
                out["notes"].append("A forecast change is attached to this report (see the raw METAR).")
            if tok != "NOSIG":
                break
            continue

        if (m := TIME_RE.match(tok)):
            out["day"], out["hour"], out["minute"] = (int(g) for g in m.groups())
        elif tok == "AUTO":
            out["auto"] = True
            out["notes"].append("Automated report (no human observer).")
        elif tok == "COR":
            out["notes"].append("Corrected report.")
        elif (m := WIND_RE.match(tok)):
            d, spd, gust, unit = m.groups()
            factor = {"KT": 1, "MPS": 1.94384, "KMH": 0.539957}[unit]
            kt = int(spd) * factor
            gust_kt = int(gust) * factor if gust else None
            wind_kt = kt
            if d == "VRB":
                wind_dir = None
            else:
                wind_dir = int(d)
            out["wind"] = {
                "calm": kt == 0,
                "variable": d == "VRB",
                "direction_deg": wind_dir,
                "direction_text": compass(wind_dir) if wind_dir is not None and kt else None,
                "speed_mph": round(knots_to_mph(kt)),
                "speed_kt": round(kt),
                "gust_mph": round(knots_to_mph(gust_kt)) if gust_kt else None,
                "variable_range": None,
            }
        elif re.fullmatch(r"\d{3}V\d{3}", tok) and out["wind"]:
            a, b = tok.split("V")
            out["wind"]["variable_range"] = f"{compass(int(a))} to {compass(int(b))}"
        elif tok == "CAVOK":
            cavok = True
            vis_m = 10000
            out["visibility"] = "10 km or more (excellent)"
            out["clouds"].append("no clouds below 5,000 ft")
            sky_codes.append("CAVOK")
        elif re.fullmatch(r"\d{4}", tok) and out["visibility"] is None:
            vis_m = int(tok)
            out["visibility"] = describe_visibility_m(vis_m)
        elif (m := VIS_SM_RE.match(tok)) or (
            re.fullmatch(r"\d", tok) and idx + 1 < len(tokens) and tokens[idx + 1].endswith("SM")
        ):
            if m:
                prefix, val = m.groups()
                if "/" in val:
                    n, d = val.split("/")
                    miles = int(n) / int(d)
                else:
                    miles = float(val)
                # Whole miles in a previous token (e.g. "1 1/2SM").
                if idx > 0 and re.fullmatch(r"\d", tokens[idx - 1]) and "/" in val:
                    miles += int(tokens[idx - 1])
                vis_m = miles * 1609.34
                shown = f"{miles:g}"
                if prefix == "P":
                    out["visibility"] = f"more than {shown} miles (excellent)"
                elif prefix == "M":
                    out["visibility"] = f"less than {shown} miles"
                else:
                    out["visibility"] = f"{shown} mile{'' if miles == 1 else 's'}"
        elif tok.startswith("R") and "/" in tok:
            continue  # runway visual range: too technical for this report
        elif (m := CLOUD_RE.match(tok)):
            kind, height, extra = m.groups()
            sky_codes.append(kind)
            if kind == "VV":
                out["clouds"].append("sky obscured (vertical visibility "
                                     + (f"{int(height) * 100:,} ft)" if height != "///" else "unknown)"))
                if height != "///":
                    ceiling_ft = min(ceiling_ft or 99999, int(height) * 100)
            else:
                ft = int(height) * 100 if height != "///" else None
                text = CLOUD_COVER[kind]
                if ft is not None:
                    text += f" at {ft:,} ft"
                if extra == "CB":
                    text += " (thunderstorm clouds)"
                elif extra == "TCU":
                    text += " (towering cumulus)"
                out["clouds"].append(text)
                if kind in ("BKN", "OVC") and ft is not None:
                    ceiling_ft = min(ceiling_ft or 99999, ft)
        elif tok in ("CLR", "SKC", "NSC", "NCD"):
            sky_codes.append(tok)
            out["clouds"].append("clear skies" if tok in ("CLR", "SKC") else "no significant clouds")
        elif (m := TEMP_RE.match(tok)):
            out["temp_c"] = _temp(m.group(1))
            if m.group(2):
                out["dew_c"] = _temp(m.group(2))
        elif (m := ALTIM_RE.match(tok)):
            unit, val = m.groups()
            if unit == "Q":
                hpa = int(val)
                inhg = hpa * 0.02953
            else:
                inhg = int(val) / 100
                hpa = inhg / 0.02953
            out["pressure"] = {"hpa": round(hpa), "inhg": round(inhg, 2)}
        elif (text := describe_weather(tok)):
            out["weather"].append(text)
            word = _headline_word(tok)
            if word:
                headline_wx.append(word)

    # Derived values
    if out["temp_c"] is not None:
        out["temp_f"] = round(c_to_f(out["temp_c"]))
        if out["dew_c"] is not None:
            out["dew_f"] = round(c_to_f(out["dew_c"]))
            out["humidity"] = humidity(out["temp_c"], out["dew_c"])
    out["ceiling_ft"] = ceiling_ft

    cat = flight_category(vis_m, ceiling_ft)
    out["flight_category"] = cat
    out["flight_category_text"] = FLIGHT_CAT_TEXT[cat]

    out["headline"] = _build_headline(out, sky_codes, headline_wx, wind_dir, wind_kt)
    return out


def _build_headline(d, sky_codes, headline_wx, wind_dir, wind_kt):
    parts = []
    # Sky: use the most cloudy layer reported.
    order = ["CLR", "SKC", "NSC", "NCD", "CAVOK", "FEW", "SCT", "BKN", "OVC", "VV"]
    sky = max(sky_codes, key=order.index) if sky_codes else None
    sky_text = SKY_HEADLINE.get(sky)
    wx = list(dict.fromkeys(headline_wx))
    if wx:
        # Weather phenomenon trumps the sky description (e.g. "Hazy" over "Clear skies").
        parts.append(wx[0] if len(wx) == 1 else f"{wx[0]} and {wx[1].lower()}")
        if sky_text and sky in ("OVC", "BKN"):
            parts[0] += f", {sky_text.lower()}"
    elif sky_text:
        parts.append(sky_text)

    if d.get("temp_f") is not None:
        parts.append(f"{d['temp_f']}°F ({d['temp_c']}°C)")

    w = d["wind"]
    if w:
        if w["calm"]:
            parts.append("calm winds")
        elif w["variable"]:
            parts.append(f"light, variable winds around {w['speed_mph']} mph")
        else:
            s = f"wind {w['speed_mph']} mph from the {w['direction_text']}"
            if w["gust_mph"]:
                s += f", gusting to {w['gust_mph']} mph"
            parts.append(s)
    return ", ".join(parts) if parts else "Weather report unavailable"
