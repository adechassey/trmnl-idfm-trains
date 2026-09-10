#!/usr/bin/env python3
"""Generates dev/fixture/.trmnlp.yml: a sample SIRI Lite response for the Massy - Palaiseau
station (RER B and RER C), injected through `variables:` with a frozen clock, to preview the
plugin without a PRIM API key.

Mission codes and times are illustrative. Field layout follows the PRIM documentation
"Prise en main des API temps réel" (stop-monitoring example) and a real response (dev/samples/).

Usage: python3 dev/make_fixture.py   (then bin/dev fixture)
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime(2026, 9, 10, 16, 0, 0, tzinfo=timezone.utc)  # 18:00 in Paris (CEST)
STOP_AREA = "58774"
STOP_NAME = "Massy-Palaiseau"

LINES = {"B": "C01743", "C": "C01727"}

# (minutes from NOW, line, destination, mission, platform, status, delay in minutes, length)
TRAINS = [
    (-3, "B", "Aéroport Charles de Gaulle 2 (Terminal 2)", "ETOU", "2", "departed", 0, "longTrain"),  # already left: filtered out
    (1, "B", "Aéroport Charles de Gaulle 2 (Terminal 2)", "ETOU", "2", "atstop", 0, "longTrain"),
    (2, "B", STOP_NAME, "TERM", "A", "ontime", 0, "longTrain"),  # terminates here: filtered out
    (5, "C", "Pontoise", "NORA", "B", "ontime", 0, "longTrain"),
    (8, "B", "Saint-Rémy-lès-Chevreuse", "KASE", "1", "delayed", 3, "shortTrain"),
    (11, "B", "Mitry - Claye", "MICK", "2", "ontime", 0, "longTrain"),
    (14, "B", "Aéroport Charles de Gaulle 2 (Terminal 2)", "ENNE", "2", "cancelled", 0, ""),
    (17, "C", "Dourdan - La Forêt", "DEBA", "A", "ontime", 0, "longTrain"),
    (20, "B", "Saint-Rémy-lès-Chevreuse", "KANE", "1", "ontime", 0, "longTrain"),
    (23, "B", "Orsay-Ville", "POIN", "1", "ontime", 0, "shortTrain"),
    (29, "B", "Aéroport Charles de Gaulle 2 (Terminal 2)", "ETOU", "2", "delayed", 6, "longTrain"),
    (32, "C", "Pontoise", "NORA", "B", "ontime", 0, "longTrain"),
    (38, "B", "Mitry - Claye", "MICK", "2", "ontime", 0, "longTrain"),
    (41, "B", "Saint-Rémy-lès-Chevreuse", "KASE", "1", "ontime", 0, "longTrain"),
    (47, "C", "Dourdan - La Forêt", "DEBA", "A", "ontime", 0, "longTrain"),
    (50, "B", "Orsay-Ville", "PIED", "1", "ontime", 0, "shortTrain"),
]


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def visit(minutes, line, dest, mission, platform, status, delay, length):
    expected = NOW + timedelta(minutes=minutes)
    aimed = expected - timedelta(minutes=delay)
    call = {
        "StopPointName": [{"value": STOP_NAME}],
        "VehicleAtStop": status == "atstop",
        "DestinationDisplay": [{"value": dest}],
        "AimedArrivalTime": iso(aimed - timedelta(minutes=1)),
        "AimedDepartureTime": iso(aimed),
        "DepartureStatus": "cancelled" if status == "cancelled" else "onTime",
        "ArrivalStatus": "cancelled" if status == "cancelled" else "onTime",
        "ArrivalPlatformName": {"value": platform},
        "DeparturePlatformName": {"value": platform},
        "Order": 14,
    }
    if status != "cancelled":
        call["ExpectedArrivalTime"] = iso(expected - timedelta(minutes=1))
        call["ExpectedDepartureTime"] = iso(expected)
    return {
        "RecordedAtTime": iso(NOW - timedelta(seconds=40)),
        "ItemIdentifier": f"SNCF_ACCES_CLOUD:Item::{mission}{minutes:+d}:LOC",
        "MonitoringRef": {"value": f"STIF:StopArea:SP:{STOP_AREA}:"},
        "MonitoredVehicleJourney": {
            "LineRef": {"value": f"STIF:Line::{LINES[line]}:"},
            "OperatorRef": {"value": "SNCF_ACCES_CLOUD:Operator::SNCF:"},
            "FramedVehicleJourneyRef": {
                "DataFrameRef": {"value": "any"},
                "DatedVehicleJourneyRef": f"SNCF_ACCES_CLOUD:VehicleJourney::{mission}{minutes:+d}:LOC",
            },
            "DirectionName": [],
            "DirectionRef": {"value": "Aller"},
            "DestinationRef": {"value": "STIF:StopArea:SP:00000:"},
            "DestinationName": [{"value": dest}],
            "VehicleJourneyName": [{"value": f"1346{minutes:02d}"}],
            "TrainNumbers": {"TrainNumberRef": [{"value": f"1346{minutes:02d}"}]},
            "VehicleFeatureRef": [length] if length else [],
            "JourneyNote": [{"value": mission}],
            "MonitoredCall": call,
        },
    }


def build_visits():
    """Visits grouped by line, not globally sorted, as PRIM returns them."""
    return [visit(*t) for t in TRAINS if t[1] == "C"] + [visit(*t) for t in TRAINS if t[1] == "B"]


def build_siri(visits):
    return {
        "Siri": {
            "ServiceDelivery": {
                "ResponseTimestamp": iso(NOW),
                "ProducerRef": "IVTR_HET",
                "ResponseMessageIdentifier": "IVTR_HET:ResponseMessage::fixture:LOC",
                "StopMonitoringDelivery": [
                    {
                        "ResponseTimestamp": iso(NOW),
                        "Version": "2.0",
                        "Status": "true",
                        "MonitoredStopVisit": visits,
                    }
                ],
            }
        }
    }


FROZEN_CLOCK = {"trmnl": {"system": {"timestamp_utc": int(NOW.timestamp())}}}

DEFAULT_FIELDS = {
    "api_key": "fixture",
    "stop_area_id": STOP_AREA,
    "station_name": "",
    "lines": "",
    "destinations": "",
    "max_trains": "8",
    "language": "auto",
}


def render_config(custom_fields, variables, watch=("../../src", ".trmnlp.yml"), comment=""):
    """A .trmnlp.yml file: YAML accepts JSON, so the variables block is written as-is."""
    lines = [comment.rstrip("\n"), "---", "watch:"] if comment else ["---", "watch:"]
    lines += [f"  - {w}" for w in watch]
    lines += ["time_zone: Europe/Paris", "custom_fields:"]
    lines += [f"  {k}: {json.dumps(str(v), ensure_ascii=False)}" for k, v in custom_fields.items()]
    lines += ["# YAML accepts JSON: the block below is merged on top of the plugin data.",
              "variables: " + json.dumps(variables, ensure_ascii=False, indent=2)]
    return "\n".join(lines) + "\n"


def main():
    visits = build_visits()
    variables = {**FROZEN_CLOCK, **build_siri(visits)}
    comment = (f"# Preview WITHOUT an API key: sample SIRI response ({STOP_NAME}, RER B and C), frozen clock.\n"
               "# Generated by dev/make_fixture.py, do not edit by hand. Run: bin/dev fixture")
    out = Path(__file__).resolve().parent / "fixture" / ".trmnlp.yml"
    out.write_text(render_config(DEFAULT_FIELDS, variables, comment=comment), encoding="utf-8")
    print(f"wrote {out} ({len(visits)} visits)")


if __name__ == "__main__":
    main()
