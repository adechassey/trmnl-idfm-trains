#!/usr/bin/env python3
"""Probes the PRIM API with the key from .env: size and content of the responses depending
on the parameters. Used to find how to stay under TRMNL's 100 KB cap.

Usage: python3 dev/probe_api.py [ZdAId] [ZdCId]     (default: Massy - Palaiseau 58774 / 63244)
Each run uses about 7 requests of the PRIM quota (1,000 per day).
"""
import gzip
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://prim.iledefrance-mobilites.fr/marketplace/"


def load_key():
    key = os.environ.get("PRIM_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("PRIM_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        sys.exit("PRIM_API_KEY missing (environment variable or .env)")
    return key


def call(key, path, params):
    url = BASE + path + "?" + urllib.parse.urlencode(params, safe=":")
    req = urllib.request.Request(url, headers={"apikey": key, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            gz = len(raw) if r.headers.get("Content-Encoding") == "gzip" else None
            body = gzip.decompress(raw) if gz else raw
            return r.status, body, gz
    except urllib.error.HTTPError as e:
        return e.code, e.read(), None


def siri_summary(body):
    d = json.loads(body)
    visits = d["Siri"]["ServiceDelivery"]["StopMonitoringDelivery"][0].get("MonitoredStopVisit", [])
    times = [v["MonitoredVehicleJourney"]["MonitoredCall"].get("ExpectedDepartureTime", "?")[11:16] for v in visits]
    return f"{len(visits)} visits, from {min(times) if times else '-'} to {max(times) if times else '-'} UTC"


def navitia_summary(body):
    d = json.loads(body)
    deps = d.get("departures", [])
    if not deps:
        return f"no departures; keys={list(d)[:6]}; message={d.get('message') or d.get('error')}"
    out = []
    for dep in deps[:4]:
        di = dep.get("display_informations", {})
        st = dep.get("stop_date_time", {})
        out.append(f"{di.get('code')}/{di.get('headsign')}→{di.get('direction','')[:28]} "
                   f"{st.get('departure_date_time','')[9:13]} base={st.get('base_departure_date_time','')[9:13]} "
                   f"{st.get('data_freshness')} modes={di.get('physical_mode')}")
    return f"{len(deps)} departures; " + " | ".join(out)


def main():
    key = load_key()
    zda = sys.argv[1] if len(sys.argv) > 1 else "58774"
    zdc = sys.argv[2] if len(sys.argv) > 2 else "63244"
    mref = f"STIF:StopArea:SP:{zda}:"
    tests = [
        ("SIRI baseline", "stop-monitoring", {"MonitoringRef": mref}, siri_summary),
        ("SIRI MaximumStopVisits=10", "stop-monitoring", {"MonitoringRef": mref, "MaximumStopVisits": "10"}, siri_summary),
        ("SIRI PreviewInterval=PT1H", "stop-monitoring", {"MonitoringRef": mref, "PreviewInterval": "PT1H"}, siri_summary),
        ("SIRI LineRef RER B only", "stop-monitoring", {"MonitoringRef": mref, "LineRef": "STIF:Line::C01743:"}, siri_summary),
        ("Navitia ZdC count=10", f"v2/navitia/stop_areas/stop_area:IDFM:{zdc}/departures",
         {"count": "10", "data_freshness": "realtime", "disable_geojson": "true"}, navitia_summary),
        ("Navitia ZdA count=10", f"v2/navitia/stop_areas/stop_area:IDFM:{zda}/departures",
         {"count": "10", "data_freshness": "realtime", "disable_geojson": "true"}, navitia_summary),
        ("Navitia monomodal count=10", f"v2/navitia/stop_areas/stop_area:IDFM:monomodalStopPlace:{zda}/departures",
         {"count": "10", "data_freshness": "realtime", "disable_geojson": "true"}, navitia_summary),
    ]
    for name, path, params, summarize in tests:
        status, body, gz = call(key, path, params)
        size = f"{len(body)/1024:6.1f} KB" + (f" (gzip {gz/1024:.1f} KB)" if gz else "")
        try:
            info = summarize(body) if status == 200 else body[:200].decode(errors="replace")
        except Exception as e:  # noqa: BLE001
            info = f"unexpected response: {e}; {body[:200]!r}"
        print(f"{name:30} HTTP {status} {size} | {info}")


if __name__ == "__main__":
    main()
