# METAR Reader

Type in an airport code and get its current weather in plain English.

```
Hazy, 90°F (32°C), wind 6 mph from the northeast
```

## Background

A **METAR** is the standardized weather report that airports around the world
publish roughly every hour. Pilots read them fluently, but to everyone else
they look like this:

```
METAR VABB 050430Z 05005KT 4000 HZ NSC 32/18 Q1014 NOSIG
```

METAR Reader fetches the latest report for an airport and translates it into
something anyone can understand: a one-line summary, followed by details such
as temperature, humidity, wind, visibility, clouds, pressure and a simple
rating of flying conditions. The original METAR is always available under
"Raw METAR" so you can compare.

Weather data comes from the [Aviation Weather Center](https://aviationweather.gov/)
(a US National Weather Service service) through its free
[data API](https://aviationweather.gov/data/api/). No API key is needed.

This project began as a learning exercise from the freeCodeCamp Claude Code course.

## Features

- Works for airports worldwide, using ICAO codes (`KJFK`, `EGLL`, `VABB`).
  US airports also work with the 3-letter code (`JFK`).
- Temperatures in °F and °C; wind in mph and knots; visibility in miles and km.
- Decodes wind gusts and variable wind, visibility, rain, snow, fog, haze,
  thunderstorms and other present weather, cloud layers and ceilings, and
  pressure in either hPa or inHg.
- Shows the flight category (VFR / MVFR / IFR / LIFR) with a plain explanation.
- Friendly errors for invalid codes, unknown airports and service outages.
- Responsive layout with automatic dark mode.

## Installation

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), a
fast Python package manager. It installs the right Python version and the
dependencies for you, so there is nothing else to set up.

```bash
git clone https://github.com/gurdeep101/cc_fcc.git
cd cc_fcc
uv run app.py
```

Then open <http://127.0.0.1:5000> in your browser and enter an airport code.

The first run creates a virtual environment and installs Flask and requests
automatically. An internet connection is required to fetch weather.

## Running the tests

```bash
uv run pytest
```

The tests cover the decoder and the web routes. The weather API is mocked, so
they run offline.

## Project layout

| Path | Purpose |
| --- | --- |
| `app.py` | Flask app: input validation, fetching from the API, rendering |
| `metar_decoder.py` | Pure-Python METAR parser and plain-English converter (no web dependencies, reusable on its own) |
| `templates/index.html` | The single page template |
| `static/style.css` | Styling |
| `tests/` | pytest suite |

To use the decoder in your own code:

```python
from metar_decoder import decode_metar

report = decode_metar("METAR VABB 050430Z 05005KT 4000 HZ NSC 32/18 Q1014 NOSIG")
print(report["headline"])  # Hazy, 90°F (32°C), wind 6 mph from the northeast
```

## Limitations

- Runway visual range, remarks (the part after `RMK`) and forecast trends
  (`TEMPO` / `BECMG`) are not decoded; the raw METAR is still shown.
- Wind direction is where the wind blows **from**, which is the METAR convention.
- This is an informational tool and **must not be used for flight planning or
  any safety-critical decision.** Always consult official aviation sources.

## Deploying

`python app.py` starts Flask's development server with debug mode on, which is
meant for local use only. To host the app publicly, run it behind a production
WSGI server instead, for example:

```bash
uv run --with gunicorn gunicorn app:app
```

## Acknowledgements

Weather data courtesy of the
[NOAA Aviation Weather Center](https://aviationweather.gov/).

## License

Released under the [MIT License](LICENSE).
