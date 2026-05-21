# MCP tools reference

Detailed contract for each of the five tools exposed by the server. Every tool
is `async`, returns Czech-language Markdown, and never raises on upstream
errors — failures come back as a Czech sentence.

The MCP registration with descriptions/types lives in
[server.py](../src/farma_tools_mcp/server.py).

---

## `ares_lookup`

Source: [tools/ares.py](../src/farma_tools_mcp/tools/ares.py)

Look up a Czech company in **ARES** (Administrativní registr ekonomických subjektů) by IČO.

| Parameter | Type  | Default | Notes                                                                                            |
| --------- | ----- | ------- | ------------------------------------------------------------------------------------------------ |
| `ico`     | `str` | —       | 8-digit IČO. Non-digits are stripped, leading zeros are zero-padded to 8 chars.                  |

**Upstream call:**

```
GET https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}
Accept: application/json
```

One request per invocation. Returns the [official OpenAPI](https://ares.gov.cz/swagger-ui/)
`EkonomickySubjekt` JSON schema.

**Behavior:**

- Input `ico` shorter than 8 digits after cleaning → `"Chyba: IČO musí mít 8 číslic. …"`
- HTTP 404 → `"Subjekt s IČO … nebyl v ARES nalezen."` (this is the normal "not found" path — ARES uses 404, not a 200 with an error envelope).
- Other 4xx/5xx → `"ARES vrátil HTTP {code}."`
- httpx transport error → `"Chyba při dotazu na ARES: {e}"`
- Otherwise: Markdown with name, IČO, DIČ, právní forma, sídlo, kraj, datum aktualizace, NACE, FÚ, active/ceased registrations, doručovací adresa, link to `https://ares.gov.cz/ekonomicke-subjekty/?ico={ico}`.

---

## `cuzk_parcela`

Source: [tools/cuzk_parcela.py](../src/farma_tools_mcp/tools/cuzk_parcela.py)

Identify the cadastral parcel at given WGS84 coordinates.

| Parameter   | Type    | Default | Notes                          |
| ----------- | ------- | ------- | ------------------------------ |
| `latitude`  | `float` | —       | WGS84 latitude, 48.0–51.5      |
| `longitude` | `float` | —       | WGS84 longitude, 12.0–19.0     |

**Upstream calls** (up to 3, against the ČÚZK ArcGIS REST endpoint
`https://ags.cuzk.cz/arcgis/rest/services/RUIAN/MapServer`):

1. `MapServer/5/query` — parcel intersecting the point (layer 5 = parcely KN)
2. `MapServer/7/query?where=kod=<ku>` — katastrální území name + obec code (layer 7)
3. `MapServer/12/query?where=kod=<obec>` — obec name (layer 12)

All three are made on the same `httpx.AsyncClient` so they share a connection.
Steps 2 and 3 are best-effort; if either fails the response still includes the
parcel info plus a `nahlizenidokn.cuzk.cz` link.

**Behavior:**

- Coords outside the ČR bounding box → `"Souřadnice (…) leží mimo ČR."` (no upstream call)
- No parcel found at the point → `"Na souřadnicích … nebyla v katastru nalezena žádná parcela."` + manual link
- Otherwise: parcel number, katastrální území + kód, obec, druh pozemku (translated via [DRUH_POZEMKU](../src/farma_tools_mcp/tools/cuzk_parcela.py)), výměra in m² and ha, optional způsob využití, `nahlizenidokn.cuzk.cz` link.

---

## `cuzk_areas`

Source: [tools/cuzk_areas.py](../src/farma_tools_mcp/tools/cuzk_areas.py)

Check whether coordinates lie in any large-area or Natura 2000 protected zone.

| Parameter   | Type    | Default | Notes                          |
| ----------- | ------- | ------- | ------------------------------ |
| `latitude`  | `float` | —       | WGS84 latitude, 48.0–51.5      |
| `longitude` | `float` | —       | WGS84 longitude, 12.0–19.0     |

**Upstream calls — 8 concurrent** (`asyncio.gather`) against
`MapServer/{30,40,44,48,52,56,60,62}/query`:

| Layer | Meaning                                                  |
| ----- | -------------------------------------------------------- |
| 30    | Národní park (NP)                                        |
| 40    | CHKO                                                     |
| 44    | Národní přírodní rezervace (NPR)                         |
| 48    | Národní přírodní památka (NPP)                           |
| 52    | Přírodní rezervace (PR)                                  |
| 56    | Přírodní památka (PP)                                    |
| 60    | Natura 2000 – Evropsky významná lokalita (EVL)           |
| 62    | Natura 2000 – Ptačí oblast (PO)                          |

**Behavior:**

- Coords outside the ČR bounding box → friendly Czech message, no upstream call
- No hits across all 8 layers → `"✅ … neleží v žádném velkoplošném ani Natura 2000 chráněném území."` plus a reminder that VKP / OP vodního zdroje / záplavové území / územní plán are **not** checked
- Any hit → list with layer name, `nazev`, `cislo`, optional `odkaz`, plus a Czech caveat about consequences and a recommendation to consult AOPK ČR
- Failed layers are reported at the end but don't fail the call

**Does not cover:** VKP (významný krajinný prvek), OP vodního zdroje,
záplavové území, územní plán obce. Those require different sources.

---

## `open_meteo`

Source: [tools/open_meteo.py](../src/farma_tools_mcp/tools/open_meteo.py)

Two modes against the Open-Meteo APIs: short-term forecast or 10-year ERA5 climate average.

| Parameter   | Type                            | Default      | Notes                                              |
| ----------- | ------------------------------- | ------------ | -------------------------------------------------- |
| `latitude`  | `float`                         | —            | WGS84 latitude                                     |
| `longitude` | `float`                         | —            | WGS84 longitude                                    |
| `mode`      | `Literal["forecast","climate"]` | `"forecast"` | `"climate"` switches to ERA5 archive               |
| `days`      | `int`                           | `7`          | Forecast horizon, clamped to 1–14. Ignored in climate mode. |

**Forecast mode**

```
GET https://api.open-meteo.com/v1/forecast
    ?latitude=…&longitude=…
    &daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max,weathercode
    &timezone=Europe/Prague
    &forecast_days=<1..14>
```

Returns a Markdown table: `Datum | Tmin | Tmax | Srážky | Vítr`.

**Climate mode**

```
GET https://archive-api.open-meteo.com/v1/era5
    ?latitude=…&longitude=…
    &start_date=<last-completed-year - 9>-01-01
    &end_date=<last-completed-year>-12-31
    &daily=temperature_2m_max,temperature_2m_min,precipitation_sum
    &timezone=Europe/Prague
```

Pulls 10 calendar years (current year is excluded), aggregates daily values
into monthly averages and counts frost days locally. Output: monthly Tmax avg /
Tmin avg / total precipitation, plus annual precipitation total and average
frost-day count. Climate mode uses a longer 60s read timeout (the archive
endpoint is slower).

**Behavior:**

- Invalid coords → `"Chyba: neplatné souřadnice (lat=…, lon=…)."`
- Open-Meteo returns 4xx/5xx → `"Open-Meteo vrátil HTTP {code}."` (and `Open-Meteo archive vrátil HTTP …` for climate mode)
- Transport / parse error → Czech error sentence

No API key needed; Open-Meteo enforces soft quotas.

---

## `osm_nearby`

Source: [tools/osm_nearby.py](../src/farma_tools_mcp/tools/osm_nearby.py)

Find OpenStreetMap features in a radius around a point, via Overpass API with mirror fallback.

| Parameter   | Type    | Default  | Notes                                                                             |
| ----------- | ------- | -------- | --------------------------------------------------------------------------------- |
| `latitude`  | `float` | —        | WGS84 latitude                                                                    |
| `longitude` | `float` | —        | WGS84 longitude                                                                   |
| `radius_m`  | `int`   | `2000`   | Search radius in meters, clamped to 100–20 000.                                   |
| `category`  | `str`   | `"farm"` | A predefined category (see below) or a raw OSM tag in the form `key=value`.       |

**Categories** (defined in `CATEGORY_MAP`):

| Category        | OSM filters used                                                                                                                                                  |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `farm`          | `landuse=farmyard`, `place=farm`, `building=farm`, `building=barn`                                                                                                 |
| `restaurant`    | `amenity=restaurant`, `amenity=cafe`, `amenity=pub`, `amenity=fast_food`                                                                                          |
| `accommodation` | `tourism=hotel`, `tourism=guest_house`, `tourism=hostel`, `tourism=apartment`, `tourism=camp_site`, `tourism=chalet`                                              |
| `tourism`       | `tourism~attraction|museum|viewpoint|theme_park|zoo|picnic_site`                                                                                                  |
| `shop`          | any `shop=*`                                                                                                                                                       |
| `water`         | `natural=water`, `waterway=river`, `waterway=stream`, `natural=spring`                                                                                            |
| `road`          | `highway~motorway|trunk|primary|secondary|tertiary`                                                                                                                |
| `school`        | `amenity~school|kindergarten`                                                                                                                                      |
| `zoo`           | `tourism=zoo`, `amenity=animal_shelter`, `leisure=park`                                                                                                            |

For custom tags, pass `"category=key=value"`, e.g. `"category=craft=brewery"`.

**Upstream call** — Overpass POST `data=<query>` with mirror fallback in order:

1. `https://overpass.openstreetmap.fr/api/interpreter` (most reliable lately)
2. `https://overpass-api.de/api/interpreter`
3. `https://overpass.kumi.systems/api/interpreter`

The first mirror returning a success status wins. If all three fail, the tool
returns `"Všechny Overpass mirrors selhaly. Poslední: {…}"`.

**Overpass QL template:**

```overpassql
[out:json][timeout:25];
(
  node["key"="value"](around:<radius>,<lat>,<lon>);
  way["key"="value"](around:<radius>,<lat>,<lon>);
  relation["key"="value"](around:<radius>,<lat>,<lon>);
  …repeated for every filter in the category…
);
out center tags 80;
```

**Behavior:**

- Unknown category and no `=` separator → `"Neznámá kategorie '…'. Použij: <list>"`
- No results → `"V okolí Xm od (lat, lon) nebylo nic z kategorie '…' nalezeno."`
- Otherwise: up to 30 results sorted by haversine distance, each line `- {dist}m | {name} [{tag pairs}] ({lat}, {lon})`

---

## Adding a new tool

1. Drop an `async def` returning `str` into [src/farma_tools_mcp/tools/](../src/farma_tools_mcp/tools/).
2. Register it in [server.py](../src/farma_tools_mcp/server.py) with `@mcp.tool(name=…, description=…)` — Czech description, the LLM uses it to pick the tool.
3. Use `Field(description=…)` for every argument so the JSON schema is informative.
4. Add a test file with a real captured fixture under `tests/fixtures/`. Refresh instructions go into [tests/fixtures/README.md](../tests/fixtures/README.md).
