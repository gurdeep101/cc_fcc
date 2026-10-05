"""METAR Reader: look up an airport's current weather in plain English.

A small Flask app.  The user enters an airport code, the latest METAR is
fetched from the Aviation Weather Center API, and :mod:`metar_decoder`
turns it into a readable report.

Run it with ``uv run app.py`` and open http://127.0.0.1:5000.
"""

import re
from datetime import datetime, timezone
from typing import Optional

import requests
from flask import Flask, render_template, request

from airports import candidate_icao_codes
from metar_decoder import decode_metar

# Public, key-less API from the US National Weather Service.
# Docs: https://aviationweather.gov/data/api/
API_URL = "https://aviationweather.gov/api/data/metar"

# Airport identifiers are 3-4 letters/digits (IATA like "JFK", ICAO like "KJFK").
# Validating up front keeps arbitrary user input out of the upstream request.
CODE_RE = re.compile(r"^[A-Z0-9]{3,4}$")

app = Flask(__name__)


class WeatherServiceError(Exception):
    """The weather service could not be reached; the message is safe to show users."""


def fetch_metar(code: str) -> Optional[dict]:
    """Fetch the latest METAR record for one airport identifier.

    Returns the API's JSON record (a dict), or None if the service has no
    report for that identifier.

    Raises:
        WeatherServiceError: if the service is unreachable or returns an error.
    """
    try:
        resp = requests.get(
            API_URL,
            params={"ids": code, "format": "json"},
            timeout=10,  # never let a slow upstream hang the page
            headers={"User-Agent": "metar-reader-flask-app"},
        )
        resp.raise_for_status()
    except requests.RequestException:
        raise WeatherServiceError(
            "Couldn't reach the aviation weather service. Please try again in a moment."
        )
    # An unknown station yields an empty body rather than an error status.
    if not resp.content.strip():
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data[0] if data else None


def lookup(code: str) -> Optional[dict]:
    """Find the latest METAR for a user-supplied IATA or ICAO code, or None if there isn't one."""
    # The API only understands ICAO codes (KJFK), but people usually know the
    # 3-letter IATA code (JFK), so translate before querying.
    candidates = candidate_icao_codes(code)
    for candidate in candidates:
        record = fetch_metar(candidate)
        if record:
            return record
    return None


def age_text(obs_epoch: float) -> str:
    """Describe how long ago an observation was made, e.g. '12 minutes ago'."""
    minutes = int((datetime.now(timezone.utc).timestamp() - obs_epoch) / 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'' if minutes == 1 else 's'} ago"
    hours = minutes // 60
    return f"{hours} hour{'' if hours == 1 else 's'} ago"


@app.route("/")
def index():
    """Render the search page, plus the decoded report when a code is given (?code=KJFK)."""
    code = request.args.get("code", "").strip().upper()
    ctx = {"code": code, "report": None, "error": None}
    if not code:
        return render_template("index.html", **ctx)

    if not CODE_RE.match(code):
        ctx["error"] = "Airport codes are 3 or 4 letters/numbers, like JFK, LHR, BOM or KJFK."
        return render_template("index.html", **ctx), 400

    try:
        record = lookup(code)
    except WeatherServiceError as e:
        ctx["error"] = str(e)
        return render_template("index.html", **ctx), 502

    if not record:
        ctx["error"] = f"No current weather report found for “{code}”. Check the code, or try a nearby larger airport."
        return render_template("index.html", **ctx), 404

    report = decode_metar(record["rawOb"])
    # Station name and observation time come from the API record, not the METAR text.
    report["name"] = record.get("name") or record.get("icaoId")
    report["icao"] = record.get("icaoId")
    report["observed"] = datetime.fromtimestamp(record["obsTime"], timezone.utc).strftime("%b %d, %H:%M UTC")
    report["age"] = age_text(record["obsTime"])
    ctx["report"] = report
    return render_template("index.html", **ctx)


if __name__ == "__main__":
    # debug=True enables auto-reload and the interactive debugger. It is for
    # local development only: never expose it to the internet.
    app.run(debug=True)
