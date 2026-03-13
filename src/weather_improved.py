from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests
from pyproj import Transformer

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

OSD_URL = "https://api.os.uk/search/names/v1/find"
MET_URL = "https://data.hub.api.metoffice.gov.uk/sitespecific/v0/point/daily"
REQUEST_TIMEOUT_SECONDS = 10
BNG_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


class WeatherError(Exception):
    """Raised for expected weather lookup failures."""


def load_environment() -> None:
    """Load variables from .env, with fallback if python-dotenv is unavailable."""
    if load_dotenv is not None:
        load_dotenv()
        return

    env_path = Path(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_postcode_coordinates(
    session: requests.Session, api_key: str, postcode: str
) -> dict[str, Any]:
    params = {
        "query": postcode,
        "fq": "LOCAL_TYPE:Postcode",
        "key": api_key,
        "maxresults": 1,
    }

    try:
        response = session.get(OSD_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise WeatherError(f"Location lookup failed (HTTP {status}).") from exc
    except requests.RequestException as exc:
        raise WeatherError("Location lookup failed.") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise WeatherError("Location service returned invalid data.") from exc

    results = data.get("results", [])
    if not results:
        raise WeatherError("Postcode not found.")

    entry = results[0].get("GAZETTEER_ENTRY", {})
    required_keys = ["NAME1", "GEOMETRY_X", "GEOMETRY_Y"]
    if any(key not in entry for key in required_keys):
        raise WeatherError("Location data is incomplete.")

    return {
        "postcode": entry["NAME1"],
        "geometry_x": entry["GEOMETRY_X"],
        "geometry_y": entry["GEOMETRY_Y"],
        "populated_place": entry.get("POPULATED_PLACE"),
        "region": entry.get("REGION"),
        "country": entry.get("COUNTRY"),
    }


def get_lat_long(x_coord: str | float, y_coord: str | float) -> dict[str, float]:
    try:
        x_val = float(x_coord)
        y_val = float(y_coord)
    except (TypeError, ValueError) as exc:
        raise WeatherError("Invalid location coordinates.") from exc

    longitude, latitude = BNG_TO_WGS84.transform(x_val, y_val)
    return {"latitude": latitude, "longitude": longitude}


def get_daily_forecast(
    session: requests.Session,
    api_key: str,
    latitude: float,
    longitude: float,
    field: str = "dayProbabilityOfRain",
) -> list[dict[str, Any]]:
    headers = {
        "apikey": api_key,
        "accept": "application/json",
    }
    params = {
        "latitude": latitude,
        "longitude": longitude,
    }

    try:
        response = session.get(
            MET_URL,
            headers=headers,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise WeatherError(f"Forecast lookup failed (HTTP {status}).") from exc
    except requests.RequestException as exc:
        raise WeatherError("Forecast lookup failed.") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise WeatherError("Forecast service returned invalid data.") from exc

    features = data.get("features", [])
    if not features:
        raise WeatherError("Forecast data unavailable.")

    properties = features[0].get("properties", {})
    time_series = properties.get("timeSeries", [])
    if not time_series:
        raise WeatherError("Forecast data unavailable.")

    forecast = []
    for entry in time_series[:7]:
        if "time" not in entry:
            continue
        forecast.append(
            {
                "time": entry["time"],
                "rain_probability": entry.get(field),
            }
        )

    if not forecast:
        raise WeatherError("Forecast data unavailable.")
    return forecast


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: python weather_improved.py "<POSTCODE>"', file=sys.stderr)
        return 1

    postcode = sys.argv[1].strip()
    if not postcode:
        print("Error: postcode cannot be empty.", file=sys.stderr)
        return 1

    load_environment()
    api_key_met = os.getenv("METOFFICE_API_KEY")
    api_key_osd = os.getenv("OSD_API_KEY")
    if not api_key_met:
        print("Error: METOFFICE_API_KEY is not set.", file=sys.stderr)
        return 1
    if not api_key_osd:
        print("Error: OSD_API_KEY is not set.", file=sys.stderr)
        return 1

    try:
        with requests.Session() as session:
            result = get_postcode_coordinates(session, api_key_osd, postcode)
            result_geography = get_lat_long(result["geometry_x"], result["geometry_y"])
            forecast = get_daily_forecast(
                session=session,
                api_key=api_key_met,
                latitude=result_geography["latitude"],
                longitude=result_geography["longitude"],
            )
    except WeatherError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130

    print(
        f"Weather forecast for {postcode} "
        f"({result['populated_place']}, {result['region']}, {result['country']}):"
    )
    for row in forecast:
        date = row["time"][:10]
        rain = row.get("rain_probability")
        rain_text = "N/A" if rain is None else f"{rain}%"
        print(f"{date} - Rain probability: {rain_text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
