#!/usr/bin/env python3
"""Smoke test: renders the 4 views in several configurations (filters, API error, no trains)
with `trmnlp build` and checks the produced text.

Usage: python3 dev/smoke.py          (exit 1 if a check fails)
"""
import html
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_fixture as fx  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "dev" / ".smoke" / "cases"

visits = fx.build_visits()
SIRI = fx.build_siri(visits)
EMPTY = fx.build_siri([])

# name -> (custom_fields, variables, expected in full, absent from full, expected row count or None)
# `Siri` variables are parsed by src/transform.py (which skips the PRIM call when Siri is present);
# `trains`/`error` variables are passed through untouched.
CASES = {
    "default": (
        {}, {**fx.FROZEN_CLOCK, **SIRI},
        ["Massy-Palaiseau", "At platform", "+3 min", "Cancelled", "Updated 18:00", "KASE", "Pontoise", "18:05", "long", "short"],
        ["17:57", "Next trains", "5 min 18:05", "TERM"], 8),
    "lines_c": (
        {"lines": "c"}, {**fx.FROZEN_CLOCK, **SIRI},
        ["Pontoise", "Dourdan"], ["Aéroport", "Saint-Rémy"], 4),
    "dest_airport": (
        {"destinations": "Aéroport, mitry"}, {**fx.FROZEN_CLOCK, **SIRI},
        ["Aéroport Charles de Gaulle", "Mitry"], ["Saint-Rémy", "Pontoise"], 5),
    "station_name": (
        {"station_name": "Gare de Massy"}, {**fx.FROZEN_CLOCK, **SIRI},
        ["Gare de Massy"], [], 8),
    "lang_fr": (
        {"language": "fr"}, {**fx.FROZEN_CLOCK, **SIRI},
        ["Heure", "Ligne", "Voie", "Statut", "À quai", "Supprimé", "À l'heure", "court", "Mis à jour 18:00"],
        ["Time", "Cancelled", "On time", "short", "Updated"], 8),
    "lang_auto_fr_locale": (
        {"language": "auto"}, {**fx.FROZEN_CLOCK, **SIRI, "trmnl": {**fx.FROZEN_CLOCK["trmnl"], "user": {"locale": "fr-FR"}}},
        ["Heure", "À quai"], ["Time"], 8),
    "max_trains_3": (
        {"max_trains": "3"}, {**fx.FROZEN_CLOCK, **SIRI},
        ["At platform"], [], 3),
    "api_error": (
        {}, {**fx.FROZEN_CLOCK, "trains": [], "error": "PRIM HTTP 401: invalid PRIM API key", "station": ""},
        ["Data unavailable", "PRIM HTTP 401"], ["Time"], 0),
    "no_polled_data": (
        {}, {**fx.FROZEN_CLOCK, "message": "Unauthorized"},
        ["Data unavailable", "No PRIM data received", "Unauthorized"], ["Time"], 0),
    "no_transform_output": (
        {}, {**fx.FROZEN_CLOCK, "trains": None},
        ["Data unavailable", "Serverless"], ["Time"], 0),
    "no_trains": (
        {}, {**fx.FROZEN_CLOCK, **EMPTY},
        ["No upcoming trains"], ["Time"], 0),
}

VIEWS = ["full", "half_horizontal", "half_vertical", "quadrant"]


def trmnlp_cmd():
    gem_bin = subprocess.run(["gem", "environment", "gemdir"], capture_output=True, text=True).stdout.strip()
    os.environ["PATH"] = f"{gem_bin}/bin:{os.environ['PATH']}"
    return [str(ROOT / "bin" / "trmnlp")]


def text_of(path: Path) -> str:
    raw = path.read_text(encoding="utf-8")
    i = raw.find('class="layout')
    seg = raw[i:] if i >= 0 else raw
    seg = seg.split("</body>")[0]
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seg)))


def rows_of(path: Path) -> int:
    raw = path.read_text(encoding="utf-8")
    m = re.search(r"<tbody>(.*?)</tbody>", raw, flags=re.S)
    return len(re.findall(r"<tr", m.group(1))) if m else 0


def main() -> int:
    cmd = trmnlp_cmd()
    shutil.rmtree(WORK, ignore_errors=True)
    failures = 0
    for name, (fields, variables, expected, absent, nrows) in CASES.items():
        case_dir = WORK / name
        case_dir.mkdir(parents=True)
        (case_dir / "src").symlink_to(ROOT / "src")
        cfg = fx.render_config({**fx.DEFAULT_FIELDS, **fields}, variables, watch=())
        (case_dir / ".trmnlp.yml").write_text(cfg, encoding="utf-8")
        rel = case_dir.relative_to(ROOT)
        run = subprocess.run(cmd + ["build", "--quiet", "--dir", str(rel)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode != 0:
            print(f"✗ {name}: trmnlp build failed\n{run.stdout}{run.stderr}")
            failures += 1
            continue
        problems = []
        for view in VIEWS:
            out = case_dir / "_build" / f"{view}.html"
            if not out.exists():
                problems.append(f"{view}: missing file")
                continue
            raw = out.read_text(encoding="utf-8")
            if re.search(r"Liquid (error|syntax error)", raw):
                problems.append(f"{view}: Liquid error")
        full = case_dir / "_build" / "full.html"
        if full.exists():
            t = text_of(full)
            problems += [f"expected text missing: {e!r}" for e in expected if e not in t]
            problems += [f"unexpected text present: {a!r}" for a in absent if a in t]
            if nrows is not None and rows_of(full) != nrows:
                problems.append(f"{rows_of(full)} rows instead of {nrows}")
        status = "✓" if not problems else "✗"
        print(f"{status} {name}")
        for p in problems:
            print(f"    - {p}")
        failures += bool(problems)
    print(f"\n{len(CASES) - failures}/{len(CASES)} cases OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
