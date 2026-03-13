#!/usr/bin/env python3
"""Fetch a 7-day weather forecast for a UK postcode."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

POSTCODE_RE = re.compile(
    r"^(GIR ?0AA|[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2})$",
    re.IGNORECASE,
)


class WeatherLookupError(Exception):
    """Raised when postcode lookup or forecast retrieval fails."""


@dataclass(frozen=True, slots=True)
class Location:
    postcode: str
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class DailyForecast:
    day: date
    rain_chance_percent: int | None
    temp_max_c: float | None
    temp_min_c: float | None


def _fetch_json(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=15) as response:
            if response.status != 200:
                raise WeatherLookupError(f"API request failed with HTTP {response.status}")
            data = response.read().decode("utf-8")
            return json.loads(data)
    except HTTPError as exc:
        raise WeatherLookupError(f"HTTP error while calling API: {exc.code}") from exc
    except URLError as exc:
        raise WeatherLookupError(f"Network error while calling API: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise WeatherLookupError("Invalid JSON response from API") from exc


def normalise_postcode(postcode: str) -> str:
    cleaned = " ".join(postcode.strip().upper().split())
    if not POSTCODE_RE.fullmatch(cleaned):
        raise WeatherLookupError("Invalid UK postcode format.")
    return cleaned


def get_location_from_postcode(postcode: str) -> Location:
    encoded = quote(postcode)
    url = f"https://api.postcodes.io/postcodes/{encoded}"
    payload = _fetch_json(url)

    if payload.get("status") != 200 or not payload.get("result"):
        raise WeatherLookupError(f"Postcode lookup failed for '{postcode}'.")

    result = payload["result"]
    return Location(
        postcode=postcode,
        latitude=float(result["latitude"]),
        longitude=float(result["longitude"]),
    )


def get_weekly_forecast(location: Location) -> list[DailyForecast]:
    today = date.today()
    end_day = today + timedelta(days=6)
    params = (
        "daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=Europe%2FLondon"
        f"&start_date={today.isoformat()}"
        f"&end_date={end_day.isoformat()}"
    )
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={location.latitude}&longitude={location.longitude}&{params}"
    )
    payload = _fetch_json(url)
    daily = payload.get("daily")
    if not daily:
        raise WeatherLookupError("Forecast data missing from weather API response.")

    days = daily.get("time", [])
    rain_probs = daily.get("precipitation_probability_max", [])
    temp_max = daily.get("temperature_2m_max", [])
    temp_min = daily.get("temperature_2m_min", [])

    if not (len(days) == len(rain_probs) == len(temp_max) == len(temp_min)):
        raise WeatherLookupError("Forecast data is incomplete.")

    forecasts: list[DailyForecast] = []
    for idx, day_str in enumerate(days):
        forecasts.append(
            DailyForecast(
                day=date.fromisoformat(day_str),
                rain_chance_percent=_to_int_or_none(rain_probs[idx]),
                temp_max_c=_to_float_or_none(temp_max[idx]),
                temp_min_c=_to_float_or_none(temp_min[idx]),
            )
        )
    return forecasts


def _to_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def print_forecast(postcode: str, forecasts: list[DailyForecast]) -> None:
    print(f"\n7-day forecast for {postcode}")
    print("-" * 44)
    for item in forecasts:
        day_label = item.day.strftime("%a %d %b %Y")
        rain = (
            f"{item.rain_chance_percent}%"
            if item.rain_chance_percent is not None
            else "N/A"
        )
        tmax = f"{item.temp_max_c:.1f}C" if item.temp_max_c is not None else "N/A"
        tmin = f"{item.temp_min_c:.1f}C" if item.temp_min_c is not None else "N/A"
        print(f"{day_label}: Rain chance {rain} | High {tmax} | Low {tmin}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Get a 7-day weather forecast and daily rain chance for a UK postcode.",
    )
    parser.add_argument(
        "postcode",
        nargs="?",
        help="UK postcode, e.g. SW1A 1AA",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    raw_postcode = args.postcode or input("Enter a UK postcode: ").strip()

    try:
        postcode = normalise_postcode(raw_postcode)
        location = get_location_from_postcode(postcode)
        forecast = get_weekly_forecast(location)
        print_forecast(postcode, forecast)
    except WeatherLookupError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
