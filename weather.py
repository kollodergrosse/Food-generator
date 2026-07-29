"""Weather data module: provides temperatures for a location.

Uses the free Open-Meteo API (no API key needed).
"""
from datetime import date
from typing import Optional

import requests

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
REVERSE_GEOCODING_URL = "https://api.bigdatacloud.net/data/reverse-geocode-client"
IP_LOCATION_URL = "http://ip-api.com/json/"

WEEKDAYS_DE = {
    0: "Montag",
    1: "Dienstag",
    2: "Mittwoch",
    3: "Donnerstag",
    4: "Freitag",
    5: "Samstag",
    6: "Sonntag",
}


def _geocode(location: str) -> tuple[float, float]:
    """Converts a place name into coordinates (lat, lon)."""
    resp = requests.get(GEOCODING_URL, params={"name": location, "count": 1, "language": "de"}, timeout=10)
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        raise ValueError(f"Ort nicht gefunden: {location}")
    return results[0]["latitude"], results[0]["longitude"]


def _fetch_daily_data(location: str) -> tuple[list[str], list[float]]:
    """Geocodes the location and fetches the 7-day daily max-temperature forecast for it, returning
    the raw ISO date strings and temperatures as parallel lists (Open-Meteo's response shape)."""
    lat, lon = _geocode(location)
    resp = requests.get(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max",
            "forecast_days": 7,
            "timezone": "auto",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()["daily"]
    return data["time"], data["temperature_2m_max"]


def get_daily_temperatures(location: str) -> dict[str, float]:
    """Returns the daily max temperature (°C) per weekday for the coming 7 days.

    The mapping is based on the actual calendar date, e.g. {"Dienstag": 24.0, "Mittwoch": 2.0, ...}.
    """
    dates_iso, values = _fetch_daily_data(location)
    result: dict[str, float] = {}
    for date_str, temp in zip(dates_iso, values):
        weekday = WEEKDAYS_DE[date.fromisoformat(date_str).weekday()]
        result[weekday] = temp
    return result


def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """Determines the city name for a GPS coordinate pair (reverse geocoding).

    Primary location-detection method: the coordinates come from the browser's Geolocation API on
    the requesting device, so the result reflects the device's real position instead of the
    server's network route - unlike IP geolocation, this keeps working when a VPN is active.
    """
    try:
        resp = requests.get(
            REVERSE_GEOCODING_URL,
            params={"latitude": lat, "longitude": lon, "localityLanguage": "de"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None
    return data.get("city") or data.get("locality") or None


def detect_location() -> Optional[str]:
    """Automatically determines the city from the server's internet connection (IP geolocation).

    Fallback for when browser geolocation isn't available (permission denied, older browser, or the
    app accessed over plain HTTP on a non-localhost address, which browsers treat as an insecure
    context for the Geolocation API). Less reliable than reverse_geocode() since it's based on the
    server machine's public IP and therefore wrong whenever that machine routes traffic through a VPN.
    """
    try:
        resp = requests.get(IP_LOCATION_URL, params={"lang": "de"}, timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None
    if data.get("status") != "success" or not data.get("city"):
        return None
    return data["city"]
