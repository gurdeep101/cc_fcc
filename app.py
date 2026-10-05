"""METAR Reader: look up an airport's current weather in plain English."""

import re
from datetime import datetime, timezone

import requests
from flask import Flask, render_template, request

from metar_decoder import decode_metar

API_URL = "https://aviationweather.gov/api/data/metar"
CODE_RE = re.compile(r"^[A-Z0-9]{3,4}$")

app = Flask(__name__)


class LookupError_(Exception):
    """A problem we can explain to the user."""


def fetch_metar(code):
    """Return the latest METAR record (dict) for an airport code, or raise."""
    try:
        resp = requests.get(
            API_URL, params={"ids": code, "format": "json"}, timeout=10,
            headers={"User-Agent": "metar-reader-flask-app"},
        )
        resp.raise_for_status()
    except requests.RequestException:
        raise LookupError_("Couldn't reach the aviation weather service. Please try again in a moment.")
    if not resp.content.strip():
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    return data[0] if data else None


def lookup(code):
    # US airports are often typed as 3 letters (JFK); their ICAO code is K + that.
    candidates = [code] if len(code) == 4 else [code, "K" + code]
    for candidate in candidates:
        record = fetch_metar(candidate)
        if record:
            return record
    return None


def age_text(obs_epoch):
    minutes = int((datetime.now(timezone.utc).timestamp() - obs_epoch) / 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'' if minutes == 1 else 's'} ago"
    hours = minutes // 60
    return f"{hours} hour{'' if hours == 1 else 's'} ago"


@app.route("/")
def index():
    code = request.args.get("code", "").strip().upper()
    ctx = {"code": code, "report": None, "error": None}
    if not code:
        return render_template("index.html", **ctx)

    if not CODE_RE.match(code):
        ctx["error"] = "Airport codes are 3 or 4 letters/numbers, like KJFK, EGLL or VABB."
        return render_template("index.html", **ctx), 400

    try:
        record = lookup(code)
    except LookupError_ as e:
        ctx["error"] = str(e)
        return render_template("index.html", **ctx), 502

    if not record:
        ctx["error"] = f"No current weather report found for “{code}”. Check the code, or try a nearby larger airport."
        return render_template("index.html", **ctx), 404

    report = decode_metar(record["rawOb"])
    report["name"] = record.get("name") or record.get("icaoId")
    report["icao"] = record.get("icaoId")
    report["observed"] = datetime.fromtimestamp(record["obsTime"], timezone.utc).strftime("%b %d, %H:%M UTC")
    report["age"] = age_text(record["obsTime"])
    ctx["report"] = report
    return render_template("index.html", **ctx)


if __name__ == "__main__":
    app.run(debug=True)
