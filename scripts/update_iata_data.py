"""Regenerate data/iata_to_icao.json from the Aviation Weather Center station list.

Usage: uv run scripts/update_iata_data.py

The weather API only understands ICAO codes (KJFK), so the app uses this
mapping to accept 3-letter IATA codes (JFK) as well.
"""

import gzip
import io
import json
from pathlib import Path

import requests

STATIONS_URL = "https://aviationweather.gov/data/cache/stations.cache.json.gz"
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "iata_to_icao.json"


def build_mapping(stations: list[dict]) -> dict[str, str]:
    """Map IATA code -> ICAO code, from the station records."""
    mapping: dict[str, str] = {}
    # A few IATA codes appear on more than one station. Process stations that
    # actually publish METARs first so they win over inactive duplicates.
    for station in sorted(stations, key=lambda s: "METAR" not in (s.get("siteType") or [])):
        iata, icao = station.get("iataId"), station.get("icaoId")
        if iata and icao:
            mapping.setdefault(iata, icao)
    return dict(sorted(mapping.items()))


def main() -> None:
    resp = requests.get(STATIONS_URL, timeout=60)
    resp.raise_for_status()
    stations = json.load(gzip.GzipFile(fileobj=io.BytesIO(resp.content)))
    mapping = build_mapping(stations)
    OUTPUT.write_text(json.dumps(mapping, separators=(",", ":")) + "\n")
    print(f"Wrote {len(mapping)} airports to {OUTPUT}")


if __name__ == "__main__":
    main()
