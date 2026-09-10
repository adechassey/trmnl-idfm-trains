"""TRMNL Serverless function: turns the PRIM "next departures" response into the compact list
the Liquid templates need.

Why: PRIM returns 3 hours of departures at ~1.4 KB each (over 100 KB for a two-line station), far more than
the templates need and above TRMNL's 100 KB limit on merge variables. The function keeps
~130 bytes per train. (Verified on trmnl.com on 2026-09-10: the polled 109 KB payload reaches
the function, the limit applies to what the function returns.)

Run by TRMNL (Serverless tab, Python) on every refresh, and by trmnlp locally.

Input `input`: the plugin variables, including
  - `Siri`: the PRIM response fetched by the polling URL (TRMNL polls before running the
    function); in trmnlp fixture mode it is injected from dev/fixture/.trmnlp.yml
  - trmnl.plugin_settings.custom_fields_values: api_key, stop_area_id, lines, destinations...
  - trmnl.user.utc_offset: the user's time zone offset in seconds
The function makes no network call itself: TRMNL polls PRIM before running it (a fetch inside
the function would count against its 5 s limit).

Output: {"station": str, "trains": [...], "error": str, "fetched_at": epoch}
  each train: {"t": UTC epoch, "hhmm": local time, "line": "L", "dest": "..." (never contains
               "|" or ";", the separators shared.liquid uses to serialise rows),
               "dest_short": destination without its parenthesised suffix, for small layouts,
               "mission": "PEBU", "platform": "2", "delay": minutes, "status": ..., "length": ...}
  status: ontime | delayed | cancelled | atstop
Trains terminating at the station (destination = the station) are dropped: they are arrivals.
Trains are not filtered by time here (Liquid does it with the render clock), which lets
frozen-clock fixtures work.
"""
import re
import time
from datetime import datetime, timezone

MAX_TRAINS = 100  # safety bound on the returned size

# IDFM line id -> short name (RER, Transilien, metro, tram)
LINE_NAMES = {
    "C01742": "A", "C01743": "B", "C01727": "C", "C01728": "D", "C01729": "E",
    "C01737": "H", "C01739": "J", "C01738": "K", "C01740": "L", "C01736": "N",
    "C01730": "P", "C01731": "R", "C01741": "U", "C02711": "V",
    "C01371": "1", "C01372": "2", "C01373": "3", "C01386": "3b", "C01374": "4",
    "C01375": "5", "C01376": "6", "C01377": "7", "C01387": "7b", "C01378": "8",
    "C01379": "9", "C01380": "10", "C01381": "11", "C01382": "12", "C01383": "13",
    "C01384": "14",
    "C01389": "T1", "C01390": "T2", "C01391": "T3a", "C01679": "T3b", "C01684": "T5",
    "C01794": "T6", "C01774": "T7", "C01795": "T8",
}


def run(input):
    if isinstance(input, dict) and "trains" in input:
        return input  # already transformed data (test fixtures)

    cf = _custom_fields(input)
    utc_offset = _to_int(_dig(input, "trmnl", "user", "utc_offset"), 0)
    result = {"station": "", "trains": [], "error": "", "fetched_at": int(time.time())}

    siri = _find_siri(input)
    if siri is None:
        polled_error = str(_dig(input, "message") or "").strip()
        result["error"] = ("No PRIM data received: check the PRIM API key and the station id."
                           + (" (PRIM says: %s)" % polled_error if polled_error else ""))
        return result

    try:
        delivery = siri["ServiceDelivery"]["StopMonitoringDelivery"][0]
    except (KeyError, IndexError, TypeError):
        result["error"] = "Unexpected PRIM response (no StopMonitoringDelivery)."
        return result

    visits = delivery.get("MonitoredStopVisit") or []
    if not visits and str(delivery.get("Status", "true")).lower() == "false":
        result["error"] = _error_text(delivery) or "PRIM returned no departures for this stop."
        return result

    line_filter = _split_list(cf.get("lines"), upper=True)
    dest_filter = _split_list(cf.get("destinations"), lower=True)

    station = _station_name(visits, input)
    trains = []
    for visit in visits:
        if _terminates_here(visit, station):
            continue  # arrival of a train ending its run here: not a departure
        train = _parse_visit(visit, utc_offset)
        if train is None:
            continue
        if line_filter and train["line"].upper() not in line_filter:
            continue
        if dest_filter and not any(d in train["dest"].lower() for d in dest_filter):
            continue
        trains.append(train)

    trains.sort(key=lambda tr: tr["t"])
    result["trains"] = trains[:MAX_TRAINS]
    result["station"] = station
    return result


# --- SIRI Lite parsing ----------------------------------------------------------------------

def _parse_visit(visit, utc_offset):
    mvj = visit.get("MonitoredVehicleJourney") or {}
    call = mvj.get("MonitoredCall") or {}

    t_iso = (call.get("ExpectedDepartureTime") or call.get("AimedDepartureTime")
             or call.get("ExpectedArrivalTime") or call.get("AimedArrivalTime"))
    t = _epoch(t_iso)
    if t is None:
        return None

    delay = 0
    aimed = _epoch(call.get("AimedDepartureTime"))
    if call.get("ExpectedDepartureTime") and aimed is not None:
        delay = int((t - aimed + 30) // 60)

    if call.get("DepartureStatus") == "cancelled" or call.get("ArrivalStatus") == "cancelled":
        status = "cancelled"
    elif call.get("VehicleAtStop") is True:
        status = "atstop"
    elif delay >= 1:
        status = "delayed"
    else:
        status = "ontime"

    line_code = (_value(mvj.get("LineRef")) or "").split("::")[-1].rstrip(":")
    note = (_first(mvj.get("JourneyNote")) or "").strip()
    features = mvj.get("VehicleFeatureRef") or []
    length = "long" if "longTrain" in features else "short" if "shortTrain" in features else ""

    dest = (_first(mvj.get("DestinationName")) or _first(call.get("DestinationDisplay"))
            or _first(mvj.get("DirectionName")) or "").strip().replace("|", "/").replace(";", ",")
    local = datetime.fromtimestamp(t + utc_offset, timezone.utc)
    return {
        "t": t,
        "hhmm": local.strftime("%H:%M"),
        "line": LINE_NAMES.get(line_code, line_code),
        "dest": dest,
        # small layouts: without the parenthesised suffix, e.g. "Aéroport Charles de Gaulle 2 (Terminal 2)"
        "dest_short": re.sub(r"\s*\([^)]*\)", "", dest).strip() or dest,
        "mission": note.upper() if len(note) == 4 else "",
        "platform": (_value(call.get("DeparturePlatformName")) or _value(call.get("ArrivalPlatformName")) or "").strip(),
        "delay": delay,
        "status": status,
        "length": length,
    }


def _terminates_here(visit, station):
    """True when the train's destination is the monitored station itself (PRIM lists these
    arrivals alongside departures)."""
    mvj = visit.get("MonitoredVehicleJourney") or {}
    dest_ref = _value(mvj.get("DestinationRef")) or ""
    mon_ref = _value(visit.get("MonitoringRef")) or ""
    if dest_ref and mon_ref and dest_ref == mon_ref:
        return True
    dest = (_first(mvj.get("DestinationName")) or "").strip().lower()
    return bool(dest) and bool(station) and dest == station.strip().lower()


def _station_name(visits, input):
    for visit in visits:
        name = _first(_dig(visit, "MonitoredVehicleJourney", "MonitoredCall", "StopPointName"))
        if name:
            return name.strip()
    return ""


def _error_text(delivery):
    cond = delivery.get("ErrorCondition") or {}
    for key in ("Description", "ErrorText"):
        text = cond.get(key)
        if isinstance(text, dict):
            text = text.get("value")
        if text:
            return str(text)
    return ""


# --- helpers -----------------------------------------------------------------------------------

def _find_siri(input):
    """The polled PRIM response: top level for a single polling URL, under IDX_n with several."""
    if not isinstance(input, dict):
        return None
    if isinstance(input.get("Siri"), dict):
        return input["Siri"]
    for key, value in input.items():
        if key.startswith("IDX_") and isinstance(value, dict) and isinstance(value.get("Siri"), dict):
            return value["Siri"]
    return None


def _custom_fields(input):
    cf = _dig(input, "trmnl", "plugin_settings", "custom_fields_values")
    if isinstance(cf, dict) and cf:
        return cf
    # some environments expose the fields at the top level
    keys = ("api_key", "stop_area_id", "station_name", "lines", "destinations", "max_trains")
    return {k: input.get(k) for k in keys if isinstance(input, dict) and k in input}


def _split_list(raw, upper=False, lower=False):
    items = [s.strip() for s in str(raw or "").split(",")]
    items = [s for s in items if s]
    if upper:
        items = [s.upper() for s in items]
    if lower:
        items = [s.lower() for s in items]
    return items


def _epoch(iso):
    if not iso:
        return None
    try:
        text = str(iso).replace("Z", "+00:00")
        if "." in text:  # milliseconds: fromisoformat does not accept them everywhere
            head, tail = text.split(".", 1)
            text = head + tail[tail.index("+"):] if "+" in tail else head + "+00:00"
        return int(datetime.fromisoformat(text).timestamp())
    except (ValueError, TypeError):
        return None


def _value(obj):
    if isinstance(obj, dict):
        return obj.get("value")
    return obj if isinstance(obj, str) else None


def _first(items):
    if isinstance(items, list) and items:
        return _value(items[0])
    return _value(items)


def _dig(obj, *keys):
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
