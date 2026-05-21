# Test fixtures

Each `*.json` here is a real response captured from the live upstream API.
They make the unit tests stable (no network) **and** verifiable — when an
upstream schema changes, a single curl re-fetch refreshes them and the test
suite re-confirms the parsing still works.

## How to refresh

| Fixture                                | curl command                                                                                                                                                                                                                                                                          |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ares_company.json`                    | `curl -sS 'https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/45274649' -H 'Accept: application/json'` (ČEZ, a. s.)                                                                                                                                                  |
| `cuzk_parcela.json`                    | `GEOM=$(python3 -c "import json,urllib.parse; print(urllib.parse.quote(json.dumps({'x':14.4214,'y':50.0875,'spatialReference':{'wkid':4326}})))"); curl -sS "https://ags.cuzk.cz/arcgis/rest/services/RUIAN/MapServer/5/query?f=json&geometry=${GEOM}&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=false"` (Staré Město, Praha) |
| `cuzk_ku.json`                         | `curl -sS 'https://ags.cuzk.cz/arcgis/rest/services/RUIAN/MapServer/7/query?f=json&where=kod%3D727024&outFields=nazev,obec&returnGeometry=false'` (k.ú. kód 727024 = Staré Město)                                                                                                       |
| `cuzk_obec.json`                       | `curl -sS 'https://ags.cuzk.cz/arcgis/rest/services/RUIAN/MapServer/12/query?f=json&where=kod%3D554782&outFields=nazev&returnGeometry=false'` (obec kód 554782 = Praha)                                                                                                                  |
| `cuzk_area_layer{30,40,…,62}.json`     | One curl per layer at the same point in Křivoklátsko CHKO: `GEOM=$(python3 -c "import json,urllib.parse; print(urllib.parse.quote(json.dumps({'x':13.9869,'y':49.9684,'spatialReference':{'wkid':4326}})))"); for l in 30 40 44 48 52 56 60 62; do curl -sS "https://ags.cuzk.cz/arcgis/rest/services/RUIAN/MapServer/$l/query?f=json&geometry=$GEOM&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects&outFields=nazev,kod,cislo,odkaz&returnGeometry=false" > cuzk_area_layer$l.json; done` |
| `openmeteo_forecast.json`              | `curl -sS 'https://api.open-meteo.com/v1/forecast?latitude=50.0875&longitude=14.4214&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weathercode&timezone=Europe/Prague&forecast_days=3'` (Prague, 3 days)                                              |
| `openmeteo_climate.json`               | `curl -sS 'https://archive-api.open-meteo.com/v1/era5?latitude=50.0875&longitude=14.4214&start_date=2023-01-01&end_date=2024-12-31&daily=temperature_2m_max,temperature_2m_min,precipitation_sum&timezone=Europe/Prague'` (Prague, ERA5 2 years)                                          |
| `overpass_restaurants.json`            | `curl -sS --data-urlencode 'data=[out:json][timeout:25];(node["amenity"="restaurant"](around:500,50.0875,14.4214););out center tags 5;' 'https://overpass.openstreetmap.fr/api/interpreter'` (Prague centre)                                                                            |

Captured: **2026-05-21** (real values may drift over time — that's fine,
refresh the fixtures and re-run the suite).
