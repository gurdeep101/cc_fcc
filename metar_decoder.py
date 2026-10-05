"""Decode a raw METAR string into plain-English weather information.

A METAR is a standardized, terse aviation weather report, for example::

    METAR VABB 050430Z 05005KT 4000 HZ NSC 32/18 Q1014 NOSIG

The report is a sequence of space-separated groups (wind, visibility, cloud
layers, temperature, ...).  :func:`decode_metar` walks those groups, converts
each one into friendly units and wording, and returns a dictionary that the
web templates can render directly.

This module has no web or network dependencies, so it can be reused and
tested on its own.  It handles the common groups found in METAR reports;
runway visual range, remarks (everything after ``RMK``) and forecast trends
(``TEMPO``/``BECMG``) are deliberately not decoded.
"""

import math
import re
from typing import Any, Optional

# --------------------------------------------------------------------------
# Lookup tables: METAR abbreviations -> English
# --------------------------------------------------------------------------

# The 16-point compass rose; each point covers 22.5 degrees.
COMPASS = [
    "north", "north-northeast", "northeast", "east-northeast",
    "east", "east-southeast", "southeast", "south-southeast",
    "south", "south-southwest", "southwest", "west-southwest",
    "west", "west-northwest", "northwest", "north-northwest",
]

# Weather "descriptors" qualify a phenomenon, e.g. TS + RA = thunderstorm with rain.
DESCRIPTORS = {
    "MI": "shallow", "BC": "patches of", "PR": "partial", "DR": "low drifting",
    "BL": "blowing", "SH": "showers of", "TS": "thunderstorm with",
    "FZ": "freezing",
}

# Weather phenomena: precipitation, obscuration (visibility reducers), and other.
PHENOMENA = {
    "DZ": "drizzle", "RA": "rain", "SN": "snow", "SG": "snow grains",
    "IC": "ice crystals", "PL": "ice pellets", "GR": "hail",
    "GS": "small hail", "UP": "unknown precipitation", "BR": "mist",
    "FG": "fog", "FU": "smoke", "VA": "volcanic ash", "DU": "dust",
    "SA": "sand", "HZ": "haze", "PY": "spray", "PO": "dust whirls",
    "SQ": "squalls", "FC": "funnel cloud", "SS": "sandstorm",
    "DS": "duststorm",
}

# Short adjectives used in the one-line headline ("Hazy, 90°F, ...").
HEADLINE_WORDS = {
    "TS": "Thunderstorms", "FG": "Foggy", "FZFG": "Freezing fog",
    "BR": "Misty", "HZ": "Hazy", "FU": "Smoky", "DU": "Dusty",
    "SA": "Sandy", "VA": "Volcanic ash", "SQ": "Squalls", "FC": "Funnel cloud",
    "SS": "Sandstorm", "DS": "Duststorm", "RA": "Rainy", "DZ": "Drizzly",
    "SN": "Snowy", "SG": "Snowy", "GR": "Hail", "GS": "Hail", "PL": "Sleet",
    "IC": "Ice crystals", "UP": "Precipitation",
}

# Cloud cover amounts, as shown in the detailed "Sky" line.
CLOUD_COVER = {
    "FEW": "a few clouds", "SCT": "scattered clouds",
    "BKN": "broken clouds (mostly cloudy)", "OVC": "overcast",
}

# Sky wording for the headline, keyed by the most cloudy layer reported.
SKY_HEADLINE = {
    "CLR": "Clear skies", "SKC": "Clear skies", "NSC": "Clear skies",
    "NCD": "Clear skies", "CAVOK": "Clear skies", "FEW": "Mostly clear",
    "SCT": "Partly cloudy", "BKN": "Mostly cloudy", "OVC": "Overcast",
    "VV": "Sky obscured",
}

# Sky codes ordered from least to most cloudy, used to pick the "worst" layer.
SKY_ORDER = ["CLR", "SKC", "NSC", "NCD", "CAVOK", "FEW", "SCT", "BKN", "OVC", "VV"]

# What each flight category means, in non-pilot terms.
FLIGHT_CAT_TEXT = {
    "VFR": "Good visibility and high clouds, easy flying conditions.",
    "MVFR": "Marginal: somewhat reduced visibility or low clouds.",
    "IFR": "Poor visibility or low clouds; pilots need instrument rules.",
    "LIFR": "Very poor visibility or very low clouds.",
}

# --------------------------------------------------------------------------
# Patterns for individual METAR groups
# --------------------------------------------------------------------------

_DESCRIPTOR_CODES = "MI|BC|PR|DR|BL|SH|TS|FZ"
_PHENOMENON_CODES = "DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS"

# Present weather: optional intensity (- light, + heavy, VC vicinity),
# then any descriptors, then any phenomena, e.g. "-TSRA" or "BR".
WX_RE = re.compile(
    rf"^(?P<int>[-+]|VC)?(?P<desc>(?:{_DESCRIPTOR_CODES})*)(?P<phen>(?:{_PHENOMENON_CODES})*)$"
)
# Wind: direction (or VRB), speed, optional gust, unit.  e.g. "18015G25KT".
WIND_RE = re.compile(r"^(\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?(KT|MPS|KMH)$")
# Visibility in statute miles, used in the US/Canada.  e.g. "10SM", "M1/4SM", "1/2SM".
VIS_SM_RE = re.compile(r"^(M|P)?(\d+(?:/\d+)?)SM$")
# Cloud layer: amount + height in hundreds of feet + optional type.  e.g. "BKN008", "FEW040CB".
CLOUD_RE = re.compile(r"^(FEW|SCT|BKN|OVC|VV)(\d{3}|///)(CB|TCU)?$")
# Temperature / dew point in whole °C; "M" means minus.  e.g. "32/18", "M02/M05".
TEMP_RE = re.compile(r"^(M?\d{2})/(M?\d{2})?$")
# Altimeter: Q = hectopascals (most of the world), A = hundredths of inHg (US).
ALTIM_RE = re.compile(r"^([QA])(\d{4})$")
# Observation time: day of month, hour, minute (UTC).  e.g. "050430Z".
TIME_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})Z$")

# --------------------------------------------------------------------------
# Unit conversions and small helpers
# --------------------------------------------------------------------------

METERS_PER_MILE = 1609.34
MPH_PER_KNOT = 1.15078
INHG_PER_HPA = 0.02953


def c_to_f(c: float) -> float:
    """Convert degrees Celsius to degrees Fahrenheit."""
    return c * 9 / 5 + 32


def knots_to_mph(kt: float) -> float:
    """Convert knots to miles per hour."""
    return kt * MPH_PER_KNOT


def compass(deg: float) -> str:
    """Name the compass direction for a bearing in degrees (e.g. 50 -> 'northeast')."""
    return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def _temp(token: str) -> int:
    """Parse a METAR temperature value, where a leading 'M' means minus."""
    return -int(token[1:]) if token.startswith("M") else int(token)


def humidity(temp_c: float, dew_c: float) -> int:
    """Estimate relative humidity (percent) from temperature and dew point.

    Uses the Magnus approximation, which is accurate to within a percent or
    two for everyday temperatures.
    """
    a, b = 17.625, 243.04
    return round(100 * math.exp(a * dew_c / (b + dew_c) - a * temp_c / (b + temp_c)))


def describe_visibility_m(meters: int) -> str:
    """Describe a visibility given in meters (the format used outside the US)."""
    miles = meters / METERS_PER_MILE
    if meters >= 9999:
        # METAR caps metric visibility at 9999, meaning "10 km or more".
        return "10 km or more (excellent)"
    if miles >= 1:
        return f"about {miles:.1f} miles ({meters / 1000:.1f} km)".replace(".0 miles", " miles")
    return f"under a mile ({meters} m)"


def flight_category(visibility_m: Optional[float], ceiling_ft: Optional[int]) -> str:
    """Return the flight category: VFR, MVFR, IFR or LIFR.

    Uses the standard US thresholds on visibility and cloud ceiling (the
    height of the lowest broken/overcast layer).  Missing values are treated
    as unrestricted.
    """
    sm = visibility_m / METERS_PER_MILE if visibility_m is not None else 99
    ft = ceiling_ft if ceiling_ft is not None else 99999
    if sm < 1 or ft < 500:
        return "LIFR"
    if sm < 3 or ft < 1000:
        return "IFR"
    if sm <= 5 or ft <= 3000:
        return "MVFR"
    return "VFR"


# --------------------------------------------------------------------------
# Present weather (rain, fog, haze, ...)
# --------------------------------------------------------------------------

def describe_weather(token: str) -> Optional[str]:
    """Turn a present-weather group such as '-TSRA' or 'BR' into English.

    Returns None if the token is not a weather group.
    """
    m = WX_RE.match(token)
    # The regex allows an empty match, so also reject bare '-', '+' and 'VC'.
    if not m or not (m.group("desc") or m.group("phen")):
        return None
    desc = re.findall(_DESCRIPTOR_CODES, m.group("desc"))
    phen = re.findall(_PHENOMENON_CODES, m.group("phen"))
    text = " ".join([DESCRIPTORS[d] for d in desc] + [PHENOMENA[p] for p in phen])
    # A descriptor with no phenomenon ("TS" alone) would end in a dangling
    # preposition ("thunderstorm with"), so drop it.
    if text.endswith(" with") or text.endswith(" of"):
        text = text.rsplit(" ", 1)[0]
    intensity = m.group("int")
    if intensity == "-":
        text = "light " + text
    elif intensity == "+":
        text = "heavy " + text
    elif intensity == "VC":
        text += " in the vicinity"
    return text


def _headline_word(token: str) -> Optional[str]:
    """Pick a one-word adjective for a weather group, for the headline.

    Returns None for groups that have no phenomenon to name.
    """
    m = WX_RE.match(token)
    if not m:
        return None
    desc = m.group("desc")
    phen = m.group("phen")
    if "TS" in desc:
        word = HEADLINE_WORDS["TS"]
    elif desc.startswith("FZ") and phen == "FG":
        word = HEADLINE_WORDS["FZFG"]
    else:
        phenomena = re.findall(_PHENOMENON_CODES, phen)
        if not phenomena:
            return None
        word = HEADLINE_WORDS[phenomena[0]]
        if "SH" in desc and phenomena[0] == "RA":
            word = "Showery"
    if m.group("int") == "-":
        word = "Light " + word.lower()
    elif m.group("int") == "+":
        word = "Heavy " + word.lower()
    return word


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------

def decode_metar(raw: str) -> dict[str, Any]:
    """Decode a raw METAR string.

    Args:
        raw: The METAR text, e.g. ``"METAR VABB 050430Z 05005KT 4000 HZ ..."``.

    Returns:
        A dictionary with these keys (values are None or empty when the
        report does not contain that information):

        ``raw``, ``station``, ``day``/``hour``/``minute`` (UTC), ``auto``,
        ``wind`` (dict with ``calm``, ``variable``, ``direction_text``,
        ``speed_mph``, ``speed_kt``, ``gust_mph``, ``variable_range``),
        ``visibility`` (text), ``weather`` (list of text), ``clouds`` (list of
        text), ``temp_c``/``temp_f``, ``dew_c``/``dew_f``, ``humidity``,
        ``pressure`` (dict with ``hpa`` and ``inhg``), ``ceiling_ft``,
        ``flight_category``, ``flight_category_text``, ``notes`` (list of
        text) and ``headline`` (a one-line summary).

    Unrecognised groups are ignored rather than raising, because real-world
    reports often contain regional or unusual groups.
    """
    tokens = raw.strip().split()
    out: dict[str, Any] = {
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
    vis_m: Optional[float] = None       # visibility in meters, for flight category
    ceiling_ft: Optional[int] = None    # lowest broken/overcast layer
    sky_codes: list[str] = []           # every sky code seen, for the headline
    headline_wx: list[str] = []         # weather adjectives, for the headline

    # Optional report type, then the 4-character station identifier.
    i = 0
    if tokens and tokens[0] in ("METAR", "SPECI"):
        if tokens[0] == "SPECI":
            out["notes"].append("This is a special (unscheduled) report issued because conditions changed.")
        i = 1
    if i < len(tokens) and re.fullmatch(r"[A-Z][A-Z0-9]{3}", tokens[i]):
        out["station"] = tokens[i]
        i += 1

    # Each remaining group is tried against the known formats in turn.
    for idx in range(i, len(tokens)):
        tok = tokens[idx]

        if tok == "RMK":
            break  # remarks are free-form and not decoded
        if tok == "NOSIG":
            out["notes"].append("No significant change expected in the next two hours.")
            continue
        if tok in ("TEMPO", "BECMG"):
            out["notes"].append("A forecast change is attached to this report (see the raw METAR).")
            break  # trend groups use the same formats as the body; stop here

        if (m := TIME_RE.match(tok)):
            out["day"], out["hour"], out["minute"] = (int(g) for g in m.groups())
        elif tok == "AUTO":
            out["auto"] = True
            out["notes"].append("Automated report (no human observer).")
        elif tok == "COR":
            out["notes"].append("Corrected report.")
        elif (m := WIND_RE.match(tok)):
            direction, speed, gust, unit = m.groups()
            # Normalize everything to knots first; the report may use m/s or km/h.
            to_knots = {"KT": 1, "MPS": 1.94384, "KMH": 0.539957}[unit]
            kt = int(speed) * to_knots
            gust_kt = int(gust) * to_knots if gust else None
            degrees = None if direction == "VRB" else int(direction)
            out["wind"] = {
                "calm": kt == 0,
                "variable": direction == "VRB",
                "direction_deg": degrees,
                "direction_text": compass(degrees) if degrees is not None and kt else None,
                "speed_mph": round(knots_to_mph(kt)),
                "speed_kt": round(kt),
                "gust_mph": round(knots_to_mph(gust_kt)) if gust_kt else None,
                "variable_range": None,
            }
        elif re.fullmatch(r"\d{3}V\d{3}", tok) and out["wind"]:
            # Direction swing, e.g. "180V240"; always follows the wind group.
            start, end = tok.split("V")
            out["wind"]["variable_range"] = f"{compass(int(start))} to {compass(int(end))}"
        elif tok == "CAVOK":
            # "Ceiling And Visibility OK": 10 km+, no significant cloud, no weather.
            vis_m = 10000
            out["visibility"] = "10 km or more (excellent)"
            out["clouds"].append("no clouds below 5,000 ft")
            sky_codes.append("CAVOK")
        elif re.fullmatch(r"\d{4}", tok) and out["visibility"] is None:
            # Metric visibility. Checked only until visibility is set, so that
            # later four-digit groups are not misread as visibility.
            vis_m = int(tok)
            out["visibility"] = describe_visibility_m(vis_m)
        elif (m := VIS_SM_RE.match(tok)):
            prefix, value = m.groups()
            if "/" in value:
                numerator, denominator = value.split("/")
                miles = int(numerator) / int(denominator)
                # Mixed numbers are split across tokens: "1 1/2SM" is 1.5 miles.
                if idx > 0 and re.fullmatch(r"\d", tokens[idx - 1]):
                    miles += int(tokens[idx - 1])
            else:
                miles = float(value)
            vis_m = miles * METERS_PER_MILE
            shown = f"{miles:g}"
            if prefix == "P":      # "P6SM": greater than 6 miles
                out["visibility"] = f"more than {shown} miles (excellent)"
            elif prefix == "M":    # "M1/4SM": less than 1/4 mile
                out["visibility"] = f"less than {shown} miles"
            else:
                out["visibility"] = f"{shown} mile{'' if miles == 1 else 's'}"
        elif tok.startswith("R") and "/" in tok:
            continue  # runway visual range (e.g. "R12/1000"): too technical here
        elif (m := CLOUD_RE.match(tok)):
            kind, height, cloud_type = m.groups()
            sky_codes.append(kind)
            feet = int(height) * 100 if height != "///" else None
            if kind == "VV":
                # Vertical visibility: the sky is hidden (e.g. by fog) and this
                # is how far up one can see. It counts as a ceiling.
                detail = f"{feet:,} ft" if feet is not None else "unknown"
                out["clouds"].append(f"sky obscured (vertical visibility {detail})")
                if feet is not None:
                    ceiling_ft = min(ceiling_ft or 99999, feet)
            else:
                text = CLOUD_COVER[kind]
                if feet is not None:
                    text += f" at {feet:,} ft"
                if cloud_type == "CB":
                    text += " (thunderstorm clouds)"
                elif cloud_type == "TCU":
                    text += " (towering cumulus)"
                out["clouds"].append(text)
                # Only broken or overcast layers count as a "ceiling".
                if kind in ("BKN", "OVC") and feet is not None:
                    ceiling_ft = min(ceiling_ft or 99999, feet)
        elif tok in ("CLR", "SKC", "NSC", "NCD"):
            sky_codes.append(tok)
            out["clouds"].append("clear skies" if tok in ("CLR", "SKC") else "no significant clouds")
        elif (m := TEMP_RE.match(tok)):
            out["temp_c"] = _temp(m.group(1))
            if m.group(2):  # dew point can be missing
                out["dew_c"] = _temp(m.group(2))
        elif (m := ALTIM_RE.match(tok)):
            unit, value = m.groups()
            if unit == "Q":
                hpa = int(value)
                inhg = hpa * INHG_PER_HPA
            else:
                inhg = int(value) / 100
                hpa = inhg / INHG_PER_HPA
            out["pressure"] = {"hpa": round(hpa), "inhg": round(inhg, 2)}
        elif (text := describe_weather(tok)):
            out["weather"].append(text)
            word = _headline_word(tok)
            if word:
                headline_wx.append(word)

    # Values derived from what was decoded above.
    if out["temp_c"] is not None:
        out["temp_f"] = round(c_to_f(out["temp_c"]))
        if out["dew_c"] is not None:
            out["dew_f"] = round(c_to_f(out["dew_c"]))
            out["humidity"] = humidity(out["temp_c"], out["dew_c"])
    out["ceiling_ft"] = ceiling_ft

    category = flight_category(vis_m, ceiling_ft)
    out["flight_category"] = category
    out["flight_category_text"] = FLIGHT_CAT_TEXT[category]

    out["headline"] = _build_headline(out, sky_codes, headline_wx)
    return out


def _build_headline(decoded: dict[str, Any], sky_codes: list[str], headline_wx: list[str]) -> str:
    """Compose the one-line summary, e.g. 'Hazy, 90°F (32°C), wind 6 mph from the northeast'."""
    parts = []

    # Describe the sky by its most cloudy layer.
    sky = max(sky_codes, key=SKY_ORDER.index) if sky_codes else None
    sky_text = SKY_HEADLINE.get(sky)
    weather = list(dict.fromkeys(headline_wx))  # de-duplicate, keep order
    if weather:
        # A weather phenomenon takes priority over the sky ("Hazy" beats "Clear skies").
        parts.append(weather[0] if len(weather) == 1 else f"{weather[0]} and {weather[1].lower()}")
        if sky_text and sky in ("OVC", "BKN"):
            parts[0] += f", {sky_text.lower()}"
    elif sky_text:
        parts.append(sky_text)

    if decoded.get("temp_f") is not None:
        parts.append(f"{decoded['temp_f']}°F ({decoded['temp_c']}°C)")

    wind = decoded["wind"]
    if wind:
        if wind["calm"]:
            parts.append("calm winds")
        elif wind["variable"]:
            parts.append(f"light, variable winds around {wind['speed_mph']} mph")
        else:
            text = f"wind {wind['speed_mph']} mph from the {wind['direction_text']}"
            if wind["gust_mph"]:
                text += f", gusting to {wind['gust_mph']} mph"
            parts.append(text)
    return ", ".join(parts) if parts else "Weather report unavailable"
