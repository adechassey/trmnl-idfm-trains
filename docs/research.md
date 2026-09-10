# Research: TRMNL plugin "Île-de-France Next Trains"

Date: 2026-09-10. Primary sources verified (official docs + live calls) unless marked "not verified".
The example station used throughout is Massy - Palaiseau (RER B, RER C, Transilien V); the live
measurements below were made on a two-line Transilien station and are representative of any
suburban station.

## 1. Decisions

- **Plugin type**: TRMNL *Private Plugin*, **Polling** strategy plus a **Serverless** function
  (TRMNL calls the API, no server to host).
- **Data source**: Île-de-France Mobilités **PRIM** API, SIRI Lite `stop-monitoring` endpoint,
  polled by TRMNL and parsed by the Serverless function (see §8 for why).
- **Local dev**: `trmnlp` (Ruby gem `trmnl_preview`, Ruby >= 4.0, or Docker image `trmnl/trmnlp`).
- **Prerequisites**: TRMNL Developer Edition, free PRIM account + API key.

## 2. IDFM identifiers (verified 2026-09-10 on data.iledefrance-mobilites.fr)

| Object | Value |
|---|---|
| Massy - Palaiseau rail stop area (ZdA) | `58774` (railStation, parent ZdC `63244`) |
| SIRI `MonitoringRef` to use | `STIF:StopArea:SP:58774:` |
| RER B | `C01743` → `LineRef=STIF:Line::C01743:` |
| RER C | `C01727` → `LineRef=STIF:Line::C01727:` |
| GTFS stop_id | `IDFM:monomodalStopPlace:58774` |

Datasets: `zones-d-arrets` (stop areas, column `ZdAId`), `referentiel-des-lignes` (line ids),
`arrets-lignes` (which lines serve a stop). Since 2025-03-13, SNCF next departures are only
available by ZdA (`STIF:StopArea:SP:xxxxx:`), no longer by stop point.

## 3. PRIM API (Île-de-France Mobilités)

- Portal: https://prim.iledefrance-mobilites.fr (free account, self-service key under "Mes clés d'API").
- Auth header: `apikey: <key>` (verified live: 401 `No API key found in request` without it; CORS allows `apikey`).
- Endpoint:
  ```
  GET https://prim.iledefrance-mobilites.fr/marketplace/stop-monitoring?MonitoringRef=STIF:StopArea:SP:58774:
  GET https://prim.iledefrance-mobilites.fr/marketplace/stop-monitoring?MonitoringRef=STIF:StopArea:SP:58774:&LineRef=STIF:Line::C01743:
  ```
- Quota for new accounts (since 2024-03-13): **1,000 requests/day, 5 req/s** on stop-monitoring.
  Free increase on request ("Ma consommation API").
- Response: `Siri.ServiceDelivery.StopMonitoringDelivery[0].MonitoredStopVisit[]`, each visit has
  `MonitoredVehicleJourney` with:
  - `LineRef.value`, `DestinationName[0].value`, `DirectionName[0].value`
  - `JourneyNote[0].value`: 4-letter SNCF mission code — corroborated by 3 open-source clients
    and by the live tests, not officially documented
  - `MonitoredCall.AimedDepartureTime` / `ExpectedDepartureTime` (UTC), `DepartureStatus`
    (`onTime` / `cancelled`...), `DeparturePlatformName`, `VehicleAtStop`
- Docs:
  - https://prim.iledefrance-mobilites.fr/en/apis/idfm-ivtr-requete_unitaire
  - https://prim.iledefrance-mobilites.fr/en/aide-et-contact/documentation/prise-en-main-des-api/prise-en-main-des-api-prochains-passages/identification-des-objets
  - https://prim.iledefrance-mobilites.fr/en/aide-et-contact/documentation/prise-en-main-des-api/prise-en-main-des-api-prochains-passages/structure-des-requetes-parametres-dappel
  - https://prim.iledefrance-mobilites.fr/en/notre-offre (quotas)

## 4. Rejected alternatives

| API | Verdict | Reason |
|---|---|---|
| SNCF `api.sncf.com` | Theoretical fallback only | Official FAQ: Transilien in **scheduled times only**; real time = TGV/IC/TER/Lyria/Eurostar. 5,000 req/day. |
| Old Transilien real-time API | Dead | Decommissioned end of March 2023, replaced by PRIM. |
| RATP API (dev.ratp.fr) | Dead | RATP moved to PRIM; DNS no longer resolves. |
| api-ratp.pierre-grimaud.fr v4 | Dead | No longer answers; timetables unavailable since 2021. |
| navitia.io | Too small | 5,000 free requests/**month** (~166/day), not enough for 5–15 min polling. |
| IDFM GTFS-RT | Does not exist | IDFM only publishes static GTFS, NeTEx and SIRI Lite. |

## 5. TRMNL constraints to keep in mind

- Polling: one or more URLs (one per line → `IDX_0`, `IDX_1`). Headers as `apikey={{ api_key }}`
  with `api_key` defined as a form field (`custom_fields` in `settings.yml`).
- **Merge data is capped at 100 KB** ("Endpoints that respond with a larger payload will be
  rejected"). With a Serverless function the cap applies to the function's output, see §8.
- `refresh_interval`: 15 / 60 / 360 / 720 / 1440 min (5 min with TRMNL+). Since May 2026 the
  plugin is also refreshed right before being displayed.
- Liquid (Shopify) + TRMNL filters: `l_date`, `l_word`, `number_with_delimiter`, `find_by`,
  `group_by`, `where_exp`, `parse_json`, `pluralize`...
- Local time: `{{ "now" | date: "%s" | plus: trmnl.user.utc_offset | date: "%H:%M" }}`;
  `trmnl.user.time_zone_iana` for JS.
- Layouts: `full`, `half_horizontal`, `half_vertical`, `quadrant`. TRMNL OG = 800×480, 1-bit;
  TRMNL X = 1040×780 CSS px (1872×1404 physical, scale 1.8), 4-bit.
- CSS framework: https://trmnl.com/framework (classes `layout`, `title_bar`, `columns`, `item`,
  `value`, `label`, `table`...). Responsive prefixes such as `portrait:hidden` exist.
- Docs: https://help.trmnl.com/en/articles/9510536-private-plugins,
  https://help.trmnl.com/en/articles/10347358-custom-plugin-filters,
  https://help.trmnl.com/en/articles/10693981-advanced-liquid, https://github.com/usetrmnl/trmnlp

## 6. Code references

- Existing recipe "Prochain Metro RER Paris" (PRIM, 21 installs): https://trmnl.com/recipes/38247 — code not readable without forking.
- BVG Berlin plugin, fully open source (settings.yml + 4 Liquid layouts): https://github.com/danmunoz/trmnl-bvg-transit
- Python PRIM client (SIRI parsing, JourneyNote = mission code): https://github.com/droso-hass/idfm-api
- SIRI → GTFS-RT bridge (regex `^[A-Z]{4}$` on JourneyNote): https://github.com/Jouca/IDFM_GTFS-RT

## 7. Live tests on 2026-09-10 (real PRIM key, through `bin/dev` and `dev/probe_api.py`)

A real response for Massy - Palaiseau is kept in `dev/samples/` as a reference for the fields.

- Suburban SNCF stations are covered in real time: a two-line Transilien station returned
  78 visits over a 3 h horizon at the evening peak.
- **Size: about 1.4 KB per visit, so 100 to 110 KB for a two-line station at peak.** Above the
  100 KB cap when polled straight into the templates. One line alone is 75 to 85 KB.
- Confirmed fields: `JourneyNote[0].value` = mission code; `DeparturePlatformName` /
  `ArrivalPlatformName` = platform (numbers or letters); `VehicleFeatureRef` = `["longTrain"]` or
  `["shortTrain"]`; `VehicleJourneyName` and `TrainNumbers.TrainNumberRef` = train number;
  `DirectionRef` = Aller/Retour; `DirectionName` empty; `OperatorRef` empty; `MonitoringRef` = the
  requested ZdA; `ArrivalStatus` may be `arrived`; trains terminating at the station appear with
  the station itself as destination.

## 8. Getting under 100 KB: test results (`dev/probe_api.py`)

| Option | Result |
|---|---|
| SIRI `MaximumStopVisits=10` or `PreviewInterval=PT1H` | **HTTP 400**, PRIM rejects undocumented parameters |
| SIRI `LineRef` (one line only) | 75–85 KB: passes, but fragile at peak hours and useless for multi-line stations |
| Navitia `stop_area:IDFM:<ZdC>/departures?count=10&depth=0` | 383 KB, of which **311 KB of `disruptions`** that cannot be excluded; real time OK, `headsign` = mission, but includes buses |
| Navitia `stop_area:IDFM:<ZdA>` / `monomodalStopPlace:<ZdA>` | HTTP 404 |
| gzip transfer of SIRI | only 7 KB, but nothing says TRMNL measures the compressed size |
| **TRMNL Serverless** | **Chosen**: TRMNL polls PRIM, `src/transform.py` returns ~13 KB for 78 trains |

Option details:

1. Standard SIRI parameters on stop-monitoring, undocumented by PRIM: `MaximumStopVisits=20`,
   `PreviewInterval=PT1H`, `MinimumStopVisitsPerLine`. Rejected with HTTP 400.
2. PRIM Navitia endpoint: `GET /marketplace/v2/navitia/stop_areas/stop_area:IDFM:<ZdC>/departures?count=10&data_freshness=realtime&disable_geojson=true`
   (ZdC = multimodal, includes buses). Bounded by `count` but dominated by disruptions.
   Provides `display_informations.code` (line name) and `headsign` (mission) directly.
3. One polling URL per line with `LineRef` (responses `IDX_0`, `IDX_1`): fragile, and it is
   unknown whether the cap is per URL or global.
4. TRMNL Serverless (successor of "Transformer" since August 2026, help article 14130649):
   `run(input)` function in Python/Ruby/Node/PHP, 128 MB / 5 s. "Private plugins with either the
   'Polling' or 'Webhook' strategy have access to the Serverless function."

**Verified on the published plugin**: TRMNL polls PRIM (URL + `apikey` header), hands the full
payload (over 100 KB) to the function, and the 100 KB cap applies to what the function returns.
The function therefore makes no network call of its own: TRMNL's publishing checker ("Chef")
flags HTTP calls inside the function, since they run within its 5 s limit.

trmnlp quirk: `{{ env.X }}` is only interpolated in polling URL/headers/body, not in the field
values passed to the transform; with PRIM polled by trmnlp itself this no longer matters.

Chef's other hints: inline `style` attributes and `<style>` blocks are both flagged, so the
layouts use framework classes only and long destination names simply wrap; the title bar is a
shared `{% template %}` rendered with `{% render 'title_bar' %}` (its closing tag must be written
exactly `{% endtemplate %}`, no whitespace-control dashes); the `layout` element is the outermost
node of every view; in portrait the full and half-horizontal views hide the mission and
train-length columns and the vertical half hides its Info column (`portrait:hidden`), the time
cell then carrying delays and cancellations as in the quadrant. Verified on TRMNL X and OG in
both orientations; narrow columns (line badge, platform) get fixed `w--` widths so their headers
never collide.

## 9. TRMNL framework: destination truncation

`data-clamp="1"` (the framework's JS truncation engine) systematically cut ~13% of the text on the
TRMNL X profile (4-bit, 1.8 scale) even when the column had room: it measures the `<span>` width
before scaling and then compares it with the scaled font. On the TRMNL OG (1-bit) the result was
correct. A CSS ellipsis fixed it but custom CSS is flagged by Chef, so destinations are left to
wrap. Do not give the destination cell `width:100%`: the other columns lose all their spacing
(the table's surplus width is what separates them, the framework puts no padding on cells).
