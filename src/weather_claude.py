"""
weather_claude.py
-----------------
UK postcode weather forecast using Open-Meteo (free, no API key required).
Geocoding via postcodes.io (free, no API key required).

Usage:
    python3 weather_claude.py
    python3 weather_claude.py SW1A1AA
"""

from __future__ import annotations

import sys
import json
import urllib.request
import urllib.error
from datetime import date, timedelta
from typing import NamedTuple


# ── Data structures ────────────────────────────────────────────────────────────

class Location(NamedTuple):
    postcode: str
    latitude: float
    longitude: float
    region: str
    country: str


class DayForecast(NamedTuple):
    date: date
    max_temp_c: float
    min_temp_c: float
    precipitation_mm: float
    rain_chance_pct: float
    description: str


# ── Helpers ────────────────────────────────────────────────────────────────────

def _fetch_json(url: str) -> dict:
    """Fetch a URL and return parsed JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": "weather_claude/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def geocode_postcode(postcode: str) -> Location:
    """Resolve a UK postcode to lat/lon via postcodes.io."""
    clean = postcode.replace(" ", "").upper()
    url = f"https://api.postcodes.io/postcodes/{clean}"
    try:
        data = _fetch_json(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(f"Postcode '{postcode}' not found.") from exc
        raise

    result = data["result"]
    return Location(
        postcode=result["postcode"],
        latitude=result["latitude"],
        longitude=result["longitude"],
        region=result.get("region") or result.get("nuts", "Unknown"),
        country=result.get("country", "UK"),
    )


def _wmo_description(code: int) -> str:
    """Map WMO weather interpretation code to a human-readable string."""
    wmo: dict[int, str] = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Icy fog",
        51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
        61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
        71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
        80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
        85: "Slight snow showers", 86: "Heavy snow showers",
        95: "Thunderstorm", 96: "Thunderstorm + hail", 99: "Thunderstorm + heavy hail",
    }
    return wmo.get(code, f"Code {code}")


def fetch_forecast(location: Location) -> list[DayForecast]:
    """Fetch 7-day forecast from Open-Meteo for the given location."""
    base = "https://api.open-meteo.com/v1/forecast"
    params = (
        f"latitude={location.latitude}&longitude={location.longitude}"
        "&daily=temperature_2m_max,temperature_2m_min,"
        "precipitation_sum,precipitation_probability_max,weathercode"
        "&timezone=Europe%2FLondon"
        "&forecast_days=7"
    )
    url = f"{base}?{params}"
    data = _fetch_json(url)
    daily = data["daily"]

    forecasts: list[DayForecast] = []
    for i, iso_date in enumerate(daily["time"]):
        forecasts.append(
            DayForecast(
                date=date.fromisoformat(iso_date),
                max_temp_c=daily["temperature_2m_max"][i],
                min_temp_c=daily["temperature_2m_min"][i],
                precipitation_mm=daily["precipitation_sum"][i] or 0.0,
                rain_chance_pct=daily["precipitation_probability_max"][i] or 0.0,
                description=_wmo_description(daily["weathercode"][i]),
            )
        )
    return forecasts


# ── Display ─────────────────────────────────────────────────────────────────────

def _rain_bar(pct: float, width: int = 20) -> str:
    """Return a simple ASCII bar representing rain probability."""
    filled = round(pct / 100 * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {pct:3.0f}%"


def print_forecast(location: Location, forecasts: list[DayForecast]) -> None:
    """Pretty-print the 7-day forecast."""
    today = date.today()
    header = f"📍 Weather Forecast — {location.postcode}  ({location.region}, {location.country})"
    print()
    print(header)
    print("─" * len(header))
    print()

    for fc in forecasts:
        day_label = (
            "Today    " if fc.date == today
            else "Tomorrow " if fc.date == today + timedelta(days=1)
            else fc.date.strftime("%A  ")
        )
        print(f"  {day_label}  {fc.date.strftime('%d %b')}  │  "
              f"{fc.description:<22}  "
              f"↑{fc.max_temp_c:4.1f}°C  ↓{fc.min_temp_c:4.1f}°C  "
              f"💧{fc.precipitation_mm:4.1f}mm")
        print(f"{'':35}  🌧 Rain chance  {_rain_bar(fc.rain_chance_pct)}")
        print()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) > 1:
        postcode_input = sys.argv[1]
    else:
        postcode_input = input("Enter UK postcode: ").strip()

    if not postcode_input:
        print("Error: no postcode provided.", file=sys.stderr)
        sys.exit(1)

    try:
        location = geocode_postcode(postcode_input)
        forecasts = fetch_forecast(location)
        print_forecast(location, forecasts)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
