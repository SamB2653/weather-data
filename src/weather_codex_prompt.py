#!/usr/bin/env python3
"""Fetch a 7-day weather forecast for a UK postcode.

Usage:
    python weather_codex_prompt.py "SW1A 1AA"

The script:
1. Resolves a UK postcode with the OS Places API.
2. Converts British National Grid easting/northing to WGS84 latitude/longitude.
3. Retrieves the Met Office daily point forecast.
4. Prints the daily chance of rain for the next week.

API keys are read from environment variables or a local .env file and are never
hard-coded.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

OS_NAMES_API_URL = "https://api.os.uk/search/names/v1/find"
MET_OFFICE_DAILY_API_URL = (
    "https://data.hub.api.metoffice.gov.uk/sitespecific/v0/point/daily"
)
HTTP_TIMEOUT_SECONDS = 30

OS_API_KEY_NAMES = (
    "OSD_API_KEY",
)
MET_OFFICE_API_KEY_NAMES = (
    "METOFFICE_API_KEY",
)

SIGNIFICANT_WEATHER_CODES = {
    0: "Clear night",
    1: "Sunny day",
    2: "Partly cloudy (night)",
    3: "Partly cloudy (day)",
    4: "Not used",
    5: "Mist",
    6: "Fog",
    7: "Cloudy",
    8: "Overcast",
    9: "Light rain shower (night)",
    10: "Light rain shower (day)",
    11: "Drizzle",
    12: "Light rain",
    13: "Heavy rain shower (night)",
    14: "Heavy rain shower (day)",
    15: "Heavy rain",
    16: "Sleet shower (night)",
    17: "Sleet shower (day)",
    18: "Sleet",
    19: "Hail shower (night)",
    20: "Hail shower (day)",
    21: "Hail",
    22: "Light snow shower (night)",
    23: "Light snow shower (day)",
    24: "Light snow",
    25: "Heavy snow shower (night)",
    26: "Heavy snow shower (day)",
    27: "Heavy snow",
    28: "Thunder shower (night)",
    29: "Thunder shower (day)",
    30: "Thunder",
}


class WeatherForecastError(RuntimeError):
    """Raised when forecast retrieval fails."""


@dataclass(frozen=True)
class Coordinates:
    """WGS84 latitude/longitude coordinates."""

    latitude: float
    longitude: float


@dataclass(frozen=True)
class PostcodeLocation:
    """Location details resolved from the postcode lookup."""

    postcode: str
    easting: float
    northing: float
    latitude: float
    longitude: float
    address: str | None = None


@dataclass(frozen=True)
class DailyForecast:
    """A single daily forecast entry."""

    date: str
    rain_probability: int | None
    weather_summary: str | None



def load_dotenv(dotenv_path: str | Path = ".env") -> None:
    """Load environment variables from a local .env file if present."""
    candidate_paths = [
        Path(dotenv_path),
        Path.cwd() / ".env",
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]

    seen: set[Path] = set()
    for path in candidate_paths:
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)

        for raw_line in resolved.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)



def get_required_env(var_names: tuple[str, ...]) -> str:
    """Return the first available environment variable from a list of names."""
    for name in var_names:
        value = os.getenv(name)
        if value:
            return value

    joined = ", ".join(var_names)
    raise WeatherForecastError(
        f"Missing API key. Expected one of these environment variables: {joined}."
    )



def normalise_postcode(postcode: str) -> str:
    """Validate and normalise a UK postcode string for API use."""
    cleaned = " ".join(postcode.upper().split())
    if not cleaned:
        raise WeatherForecastError("A postcode must be provided.")
    return cleaned



def http_get_json(url: str, *, headers: dict[str, str], params: dict[str, Any]) -> dict[str, Any]:
    """Execute an HTTP GET request and return parsed JSON."""
    query_string = urlencode({key: value for key, value in params.items() if value is not None})
    request = Request(f"{url}?{query_string}", headers=headers, method="GET")

    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise WeatherForecastError(
            f"HTTP {exc.code} returned by {url}: {detail or exc.reason}"
        ) from exc
    except URLError as exc:
        raise WeatherForecastError(f"Unable to reach {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise WeatherForecastError(f"Invalid JSON returned by {url}.") from exc



def lookup_postcode(postcode: str, os_api_key: str) -> PostcodeLocation:
    """Resolve a postcode to British National Grid and WGS84 coordinates."""
    payload = http_get_json(
        OS_NAMES_API_URL,
        headers={"Accept": "application/json"},
        params={
            "query": postcode,
            "fq": "LOCAL_TYPE:Postcode",
            "key": os_api_key,
            "maxresults": 1,
        },
    )

    results = payload.get("results") or []
    if not results:
        raise WeatherForecastError(f"No location data returned for postcode '{postcode}'.")

    gazetteer = results[0].get("GAZETTEER_ENTRY") or {}
    easting = gazetteer.get("GEOMETRY_X")
    northing = gazetteer.get("GEOMETRY_Y")

    if easting is None or northing is None:
        raise WeatherForecastError("OS Names API response did not contain grid coordinates.")

    latitude, longitude = bng_to_wgs84(float(easting), float(northing))

    address_parts = [
        gazetteer.get("NAME1"),
        gazetteer.get("POPULATED_PLACE"),
        gazetteer.get("REGION"),
        gazetteer.get("COUNTRY"),
    ]
    address = ", ".join(str(part) for part in address_parts if part not in (None, "")) or None

    return PostcodeLocation(
        postcode=str(gazetteer.get("NAME1", postcode)),
        easting=float(easting),
        northing=float(northing),
        latitude=latitude,
        longitude=longitude,
        address=address,
    )



def bng_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Convert British National Grid coordinates to WGS84 latitude/longitude.

    This uses the standard OSGB36 inverse Transverse Mercator transform,
    followed by a Helmert transform into WGS84.
    """
    lat_osgb36, lon_osgb36 = en_to_lat_lon_osgb36(easting, northing)
    return osgb36_to_wgs84(lat_osgb36, lon_osgb36)



def en_to_lat_lon_osgb36(easting: float, northing: float) -> tuple[float, float]:
    """Convert BNG easting/northing to OSGB36 latitude/longitude in degrees."""
    a = 6377563.396
    b = 6356256.909
    f0 = 0.9996012717
    lat0 = math.radians(49.0)
    lon0 = math.radians(-2.0)
    n0 = -100000.0
    e0 = 400000.0
    e2 = 1 - (b * b) / (a * a)
    n = (a - b) / (a + b)

    lat = lat0
    m = 0.0
    while northing - n0 - m >= 0.00001:
        lat = (northing - n0 - m) / (a * f0) + lat
        ma = (1 + n + (5 / 4) * n**2 + (5 / 4) * n**3) * (lat - lat0)
        mb = (3 * n + 3 * n**2 + (21 / 8) * n**3) * math.sin(lat - lat0) * math.cos(lat + lat0)
        mc = ((15 / 8) * n**2 + (15 / 8) * n**3) * math.sin(2 * (lat - lat0)) * math.cos(2 * (lat + lat0))
        md = (35 / 24) * n**3 * math.sin(3 * (lat - lat0)) * math.cos(3 * (lat + lat0))
        m = b * f0 * (ma - mb + mc - md)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    tan_lat = math.tan(lat)

    nu = a * f0 / math.sqrt(1 - e2 * sin_lat**2)
    rho = a * f0 * (1 - e2) / (1 - e2 * sin_lat**2) ** 1.5
    eta2 = nu / rho - 1

    de = easting - e0
    vii = tan_lat / (2 * rho * nu)
    viii = tan_lat / (24 * rho * nu**3) * (5 + 3 * tan_lat**2 + eta2 - 9 * tan_lat**2 * eta2)
    ix = tan_lat / (720 * rho * nu**5) * (61 + 90 * tan_lat**2 + 45 * tan_lat**4)
    x = 1 / (cos_lat * nu)
    xi = 1 / (6 * cos_lat * nu**3) * (nu / rho + 2 * tan_lat**2)
    xii = 1 / (120 * cos_lat * nu**5) * (5 + 28 * tan_lat**2 + 24 * tan_lat**4)
    xiia = 1 / (5040 * cos_lat * nu**7) * (
        61 + 662 * tan_lat**2 + 1320 * tan_lat**4 + 720 * tan_lat**6
    )

    latitude = lat - vii * de**2 + viii * de**4 - ix * de**6
    longitude = lon0 + x * de - xi * de**3 + xii * de**5 - xiia * de**7

    return math.degrees(latitude), math.degrees(longitude)



def osgb36_to_wgs84(latitude: float, longitude: float) -> tuple[float, float]:
    """Convert OSGB36 latitude/longitude to WGS84 latitude/longitude."""
    lat = math.radians(latitude)
    lon = math.radians(longitude)

    a1 = 6377563.396
    b1 = 6356256.909
    e2_1 = 1 - (b1 * b1) / (a1 * a1)

    nu1 = a1 / math.sqrt(1 - e2_1 * math.sin(lat) ** 2)
    x1 = nu1 * math.cos(lat) * math.cos(lon)
    y1 = nu1 * math.cos(lat) * math.sin(lon)
    z1 = (nu1 * (1 - e2_1)) * math.sin(lat)

    tx = 446.448
    ty = -125.157
    tz = 542.06
    rx = math.radians(0.1502 / 3600)
    ry = math.radians(0.2470 / 3600)
    rz = math.radians(0.8421 / 3600)
    s = 20.4894 * 1e-6

    x2 = tx + (1 + s) * x1 + (-rz) * y1 + ry * z1
    y2 = ty + rz * x1 + (1 + s) * y1 + (-rx) * z1
    z2 = tz + (-ry) * x1 + rx * y1 + (1 + s) * z1

    a2 = 6378137.0
    b2 = 6356752.3141
    e2_2 = 1 - (b2 * b2) / (a2 * a2)

    lon2 = math.atan2(y2, x2)
    p = math.sqrt(x2 * x2 + y2 * y2)
    lat2 = math.atan2(z2, p * (1 - e2_2))

    for _ in range(10):
        nu2 = a2 / math.sqrt(1 - e2_2 * math.sin(lat2) ** 2)
        lat2 = math.atan2(z2 + e2_2 * nu2 * math.sin(lat2), p)

    return round(math.degrees(lat2), 6), round(math.degrees(lon2), 6)



def fetch_daily_forecast(coordinates: Coordinates, met_office_api_key: str) -> list[DailyForecast]:
    """Fetch the Met Office daily forecast for a WGS84 point."""
    payload = http_get_json(
        MET_OFFICE_DAILY_API_URL,
        headers={"apikey": met_office_api_key, "Accept": "application/json"},
        params={
            "datasource": "BD1",
            "latitude": coordinates.latitude,
            "longitude": coordinates.longitude,
            "includeLocationName": "true",
            "excludeParameterMetadata": "true",
        },
    )

    try:
        time_series = payload["features"][0]["properties"]["timeSeries"]
    except (KeyError, IndexError, TypeError) as exc:
        raise WeatherForecastError(
            "Unexpected Met Office response structure."
        ) from exc

    forecasts: list[DailyForecast] = []
    for entry in time_series:
        if not isinstance(entry, dict):
            continue

        date = extract_date(entry)
        rain_probability = extract_rain_probability(entry)
        weather_summary = extract_weather_summary(entry)
        forecasts.append(
            DailyForecast(
                date=date,
                rain_probability=rain_probability,
                weather_summary=weather_summary,
            )
        )

    if not forecasts:
        raise WeatherForecastError("No daily forecast data was returned by the Met Office API.")

    return forecasts[:7]



def extract_date(entry: dict[str, Any]) -> str:
    """Extract an ISO date from a forecast entry."""
    for key in ("time", "forecastTime", "validTime"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value.split("T", 1)[0]
    raise WeatherForecastError("A forecast entry did not include a date/time field.")



def extract_rain_probability(entry: dict[str, Any]) -> int | None:
    """Extract the daily rain probability from a forecast entry."""
    preferred_keys = (
        "probOfPrecipitationDay",
        "probOfRainDay",
        "probOfPrecipitation",
        "probOfRain",
    )
    for key in preferred_keys:
        value = entry.get(key)
        if value is not None:
            return safe_int(value)

    for key, value in entry.items():
        lowered = key.lower()
        if "prob" in lowered and ("precip" in lowered or "rain" in lowered):
            return safe_int(value)

    return None



def extract_weather_summary(entry: dict[str, Any]) -> str | None:
    """Extract a readable weather summary from a forecast entry."""
    for key in (
        "weatherType",
        "significantWeatherCode",
        "daySignificantWeatherCode",
        "nightSignificantWeatherCode",
    ):
        if key not in entry:
            continue
        code = safe_int(entry[key])
        if code is not None:
            return SIGNIFICANT_WEATHER_CODES.get(code, f"Weather code {code}")

    for key in ("weatherDescription", "summary", "screenTemperatureText"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None



def safe_int(value: Any) -> int | None:
    """Convert a value to int where possible."""
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None



def format_forecast(postcode_location: PostcodeLocation, forecasts: list[DailyForecast]) -> str:
    """Build the console output."""
    lines = [
        f"7-day forecast for {postcode_location.postcode}",
        f"Latitude/Longitude: {postcode_location.latitude:.6f}, {postcode_location.longitude:.6f}",
    ]
    if postcode_location.address:
        lines.append(f"Resolved location: {postcode_location.address}")

    lines.append("")
    lines.append("Date         | Forecast                     | Chance of rain")
    lines.append("-------------+------------------------------+---------------")

    for forecast in forecasts:
        summary = (forecast.weather_summary or "Unavailable")[:28]
        rain = (
            f"{forecast.rain_probability}%"
            if forecast.rain_probability is not None
            else "Unavailable"
        )
        lines.append(f"{forecast.date:<12} | {summary:<28} | {rain}")

    return "\n".join(lines)



def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Get a 7-day Met Office forecast for a UK postcode."
    )
    parser.add_argument("postcode", help='UK postcode, for example "SW1A 1AA"')
    return parser.parse_args(argv)



def main(argv: list[str] | None = None) -> int:
    """Program entry point."""
    load_dotenv()
    args = parse_args(argv or sys.argv[1:])

    try:
        postcode = normalise_postcode(args.postcode)
        os_api_key = get_required_env(OS_API_KEY_NAMES)
        met_office_api_key = get_required_env(MET_OFFICE_API_KEY_NAMES)

        postcode_location = lookup_postcode(postcode, os_api_key)
        forecasts = fetch_daily_forecast(
            Coordinates(
                latitude=postcode_location.latitude,
                longitude=postcode_location.longitude,
            ),
            met_office_api_key,
        )

        print(format_forecast(postcode_location, forecasts))
        return 0
    except WeatherForecastError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
