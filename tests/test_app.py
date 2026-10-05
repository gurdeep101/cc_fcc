"""Tests for the METAR decoder and the Flask routes (network calls are mocked)."""

import time
from unittest import mock

import pytest

import app as app_module
from metar_decoder import decode_metar


def test_vabb_hazy():
    d = decode_metar("METAR VABB 050430Z 05005KT 4000 HZ NSC 32/18 Q1014 NOSIG")
    assert d["temp_f"] == 90
    assert d["wind"]["speed_mph"] == 6
    assert d["wind"]["direction_text"] == "northeast"
    assert d["weather"] == ["haze"]
    assert d["flight_category"] == "IFR"
    assert d["headline"].startswith("Hazy, 90°F")
    assert "northeast" in d["headline"]


def test_us_metar_with_gusts_and_fractions():
    d = decode_metar("KJFK 051251Z 18015G25KT 1 1/2SM -RA BKN008 OVC015 M02/M05 A2992 RMK AO2 SLP132")
    assert d["wind"]["gust_mph"] == 29
    assert d["wind"]["direction_text"] == "south"
    assert d["visibility"] == "1.5 miles"
    assert d["weather"] == ["light rain"]
    assert d["temp_c"] == -2 and d["dew_c"] == -5
    assert d["pressure"]["inhg"] == 29.92
    assert d["ceiling_ft"] == 800
    assert d["flight_category"] == "IFR"


def test_clear_calm_cavok():
    d = decode_metar("EGLL 051250Z 00000KT CAVOK 20/10 Q1020")
    assert d["wind"]["calm"]
    assert d["headline"] == "Clear skies, 68°F (20°C), calm winds"
    assert d["flight_category"] == "VFR"


def test_thunderstorm_and_variable_wind():
    d = decode_metar("KDFW 051253Z VRB04KT 3SM +TSRA FEW040CB 25/23 A2985")
    assert d["weather"] == ["heavy thunderstorm with rain"]
    assert d["wind"]["variable"]
    assert "thunderstorm clouds" in d["clouds"][0]


@pytest.fixture
def client():
    return app_module.app.test_client()


def test_invalid_code(client):
    assert client.get("/?code=!!").status_code == 400


def test_unknown_code(client):
    with mock.patch.object(app_module, "fetch_metar", return_value=None):
        assert client.get("/?code=ZZZZ").status_code == 404


def test_success_page(client):
    rec = {"rawOb": "METAR VABB 050430Z 05005KT 4000 HZ NSC 32/18 Q1014 NOSIG",
           "icaoId": "VABB", "name": "Mumbai/Shivaji Intl, MM, IN", "obsTime": int(time.time()) - 600}
    with mock.patch.object(app_module, "fetch_metar", return_value=rec):
        r = client.get("/?code=vabb")
    assert r.status_code == 200
    assert b"Mumbai" in r.data and b"wind 6 mph from the northeast" in r.data
