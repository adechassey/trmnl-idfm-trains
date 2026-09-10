# Île-de-France Next Trains

A [TRMNL](https://trmnl.com) e-ink plugin showing the next trains at any Île-de-France station: Transilien, RER, metro or tram. Real-time data comes from the free **PRIM** API of Île-de-France Mobilités. Nothing to host: TRMNL polls the API with your key and a small Serverless function trims the response.

For each train: departure time, line, destination, mission code (SNCF), platform, train length (long or short) and status (on time, delay, cancelled, at platform). Times are shown rather than a countdown, because the screen stays frozen between two refreshes and only the time stays right.

All four TRMNL screen formats are supported (full, both halves, quadrant for mashups). On-screen labels are available in English and French, auto-detected from the TRMNL account language or forced in the settings.

## Prerequisites

- A TRMNL account with the **Developer Edition** (required for private plugins).
- A **PRIM API key**: free account on [prim.iledefrance-mobilites.fr](https://prim.iledefrance-mobilites.fr), then "Mes clés d'API". New accounts get 1,000 requests per day, which is plenty: a refresh every 15 minutes uses about a hundred.
- Your **station id** (IDFM stop area, "ZdAId"): look it up in the [stop areas dataset](https://data.iledefrance-mobilites.fr/explore/dataset/zones-d-arrets/table/?refine.zdatype=railStation). Example: Massy - Palaiseau = `58774`.

## Installing on TRMNL

Push the plugin from this repository with [trmnlp](https://github.com/usetrmnl/trmnlp):

```sh
gem install trmnl_preview     # or Docker, see bin/trmnlp
bin/trmnlp login              # TRMNL API key (Account page)
bin/trmnlp push               # creates the private plugin on your account
```

Then open the plugin on trmnl.com and fill in the fields:

| Field | Purpose |
|---|---|
| PRIM API key | Your Île-de-France Mobilités key |
| Station id | ZdAId, e.g. `58774` |
| Display name | Screen title (empty = name returned by the API) |
| Lines | E.g. `L,U` to keep only those lines (empty = all) |
| Destinations | E.g. `Paris, Aéroport` to keep one direction (empty = all) |
| Number of trains | 1 to 12, for the full screen |
| Language | On-screen labels: Auto (TRMNL account language), English or Français |

The plugin icon is in `assets/` (`icon.svg`, or `icon.png` at 512×512): upload it from the plugin's settings page.

After the first `push`, `src/settings.yml` gains an `id`: later pushes update that same plugin instead of creating a new one. With TRMNL's GitHub sync enabled on the plugin, saving on trmnl.com also commits the export to this repository (`Updated from TRMNL` commits).

## Local development

```sh
bin/dev fixture               # preview at http://localhost:4567 with sample data, no key needed
echo 'PRIM_API_KEY=xxx' > .env
bin/dev                       # preview with live PRIM data (.env is git-ignored)
bin/trmnlp lint               # TRMNL best practices
python3 dev/smoke.py          # renders every view in several configurations and checks the output
```

`fixture` mode uses `dev/fixture/.trmnlp.yml`, a sample SIRI response for Massy - Palaiseau with a clock frozen at 18:00. Regenerate it with `python3 dev/make_fixture.py` after editing that script.

Keep the PRIM key in `.env`, never in `.trmnlp.yml`: that file is committed by TRMNL's GitHub sync with empty custom fields. To use your own local values without ever committing them:

```sh
git update-index --skip-worktree .trmnlp.yml
```

The template for local values is `dev/trmnlp.example.yml`. A real PRIM response for Massy - Palaiseau is kept in `dev/samples/` as a reference for the returned fields.

## Repository layout

| Path | Role |
|---|---|
| `src/settings.yml` | Plugin config: PRIM polling URL and header, form fields, Serverless language |
| `src/transform.py` | Serverless function: SIRI parsing, sorting, line/destination filters |
| `src/shared.liquid` | Prepended to every view: keeps upcoming trains, formats rows, EN/FR labels |
| `src/full.liquid` | Full screen, 800×480 |
| `src/half_horizontal.liquid`, `src/half_vertical.liquid`, `src/quadrant.liquid` | Mashup formats |
| `assets/` | Plugin icon (SVG and 512×512 PNG) |
| `dev/` | Local tooling: fixture, smoke test, API probe, real sample |
| `docs/research.md` | Research notes: available APIs, TRMNL constraints, IDFM identifiers |

## How it works

On every refresh (every 15 minutes, and right before each display), TRMNL polls PRIM with your key:

```
GET https://prim.iledefrance-mobilites.fr/marketplace/stop-monitoring?MonitoringRef=STIF:StopArea:SP:<ZdAId>:
apikey: <key>
```

It then runs `src/transform.py` in the Serverless tab (Python). The function parses the SIRI Lite response, drops trains terminating at the station (arrivals), applies the line and destination filters, sorts by time and returns a compact list (`trains`, about 130 bytes per train). It makes no network call itself: TRMNL fetches the polling URL before running it.

Finally the Liquid views are rendered. `shared.liquid` drops trains that already left and serialises each train into a string (`epoch|wait|time|line|destination|mission|platform|delay|status|length`), because Liquid cannot build arrays of objects.

Why the Serverless step: PRIM returns 3 hours of departures at 1.4 KB each, over 100 KB for a two-line station, while TRMNL caps a plugin's merge data at 100 KB. The cap applies to what the function returns, not to the polled response. PRIM refuses the SIRI parameters that would limit the response, and its Navitia endpoint weighs 400 KB because of disruptions. Details in `docs/research.md`.

## Known limits

- The Serverless function gets 5 seconds and 128 MB; parsing 80 departures takes a few milliseconds.
- PRIM's horizon shrinks late in the evening: around 22:30 it may only announce the next ten minutes, so the board can show one or two trains.
- The mission code (4 letters) is read from `JourneyNote`, a field PRIM only documents as "additional text". It is filled for SNCF trains, not for RATP.
- Line id to short name mappings are hard-coded in `src/transform.py` (RER, Transilien, metro, tram). An unknown line shows its IDFM code (`C0xxxx`).
