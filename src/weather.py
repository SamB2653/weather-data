import os
import sys
import requests

from dotenv import load_dotenv
from pyproj import Transformer
  
  
def get_postcode_coordinates(api_key: str, postcode: str) -> dict:
    url = "https://api.os.uk/search/names/v1/find"

    params = {
        "query": postcode,
        "fq": "LOCAL_TYPE:Postcode",
        "key": api_key,
        "maxresults": 1
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()
    entry = data["results"][0]["GAZETTEER_ENTRY"]

    return {
        "postcode": entry["NAME1"],
        "geometry_x": entry["GEOMETRY_X"],
        "geometry_y": entry["GEOMETRY_Y"],
        "populated_place": entry["POPULATED_PLACE"],
        "region": entry["REGION"],
        "country": entry["COUNTRY"]
    }
    

def get_lat_long(lat: str, long: str) -> dict:
    transformer = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(float(lat), float(long))
    
    return {"latitude": lat,
            "longitude": lon
    }



def get_daily_forecast(api_key: str, latitude: float, longitude: float, field: str = "dayProbabilityOfRain") -> dict:
    url = "https://data.hub.api.metoffice.gov.uk/sitespecific/v0/point/daily"

    headers = {
        "apikey": api_key,
        "accept": "application/json"
    }

    params = {
        "latitude": latitude,
        "longitude": longitude
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30
    )
    
    response.raise_for_status()
    data = response.json()
    
    time_series = data["features"][0]["properties"]["timeSeries"]
    
    return [
        {
            "time": entry["time"],
            field: entry.get(field)
        }
        for entry in time_series
    ]


if __name__ == "__main__":
    postcode = sys.argv[1]
    
    # Secrets
    load_dotenv()
    api_key_met = os.getenv("METOFFICE_API_KEY")            
    api_key_osd = os.getenv("OSD_API_KEY")            

    # OSD API
    result = get_postcode_coordinates(api_key_osd, postcode)

    # Convert OSD coordinates to lat long
    result_geography = get_lat_long(result["geometry_x"], result["geometry_y"])

    # MET office API
    forecast = get_daily_forecast(
        api_key=api_key_met,
        latitude=result_geography["latitude"],
        longitude=result_geography["longitude"]
    )

    # Output
    print(f"Weather forecast for {postcode} ({result['populated_place']}, {result['region']}, {result['country']}):")
    for row in forecast:
        date = row["time"][:10]
        rain = row["dayProbabilityOfRain"]
        print(f"{date} - Rain probability: {rain}%")
        
        # https://osdatahub.os.uk/
        # https://datahub.metoffice.gov.uk/
