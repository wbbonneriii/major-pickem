#!/usr/bin/env python3
"""Fetch the four men's golf majors fields from DataGolf and write per-major JSON files.

Output files: data/{year}/{majorId}.json where majorId in {masters,pga,usopen,theopen}.

Run locally: python3 scripts/fetch-fields.py
Run in CI: see .github/workflows/update-fields.yml

The DataGolf /major-fields page embeds a complete field JSON inline. We parse it,
flip "Last, First" → "First Last", convert wins/starts into our app's schema, and
write a normalized file the app can fetch from same origin (no CORS, no API key).
"""
import json, re, sys, urllib.request, pathlib, os, datetime

URL = "https://datagolf.com/major-fields"
# DataGolf major numeric ID → our app's tournament id
MAJOR_ID = {
    "14": "masters",
    "33": "pga",
    "26": "usopen",
    "100": "theopen",
}
# Map DataGolf event_name (in wins[].event_name) to our tournament id, so we can
# build a player's majorsWon array.
WIN_EVENT_MAP = {
    "The Masters": "masters",
    "Masters Tournament": "masters",
    "PGA Championship": "pga",
    "U.S. Open": "usopen",
    "US Open": "usopen",
    "The Open Championship": "theopen",
    "Open Championship": "theopen",
}

def flip_name(s: str) -> str:
    if "," in s:
        last, first = [p.strip() for p in s.split(",", 1)]
        return f"{first} {last}"
    return s.strip()

def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (major-pickem field updater)",
        "Accept": "text/html",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")

def extract_payload(html: str) -> dict:
    m = re.search(r"var data = JSON\.parse\('(.*?)'\)\s*;", html, re.DOTALL)
    if not m:
        raise RuntimeError("Could not locate JSON.parse payload on DataGolf major-fields page")
    raw = m.group(1).replace("\\'", "'").replace("\\\\", "\\")
    return json.loads(raw)

def derive_year(payload: dict) -> int:
    iso = payload.get("iso")
    if iso:
        try:
            return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).year
        except Exception:
            pass
    return datetime.datetime.utcnow().year

def build_player(p: dict, my_major_id: str) -> dict:
    name = flip_name(p.get("player_name", ""))
    norm = re.sub(r"[^a-z]+", "_", name.lower()).strip("_")
    starts = p.get("starts", 0)
    wins = p.get("wins") or []
    majors_won = sorted({
        WIN_EVENT_MAP[w["event_name"]] for w in wins
        if w.get("event_name") in WIN_EVENT_MAP
    })
    return {
        "id": f"dg_{p.get('dg_id') or norm}",
        "name": name,
        "country": p.get("flag", ""),
        "owgr": p.get("rank") or p.get("dg_rank") or 999,
        "majorsWon": majors_won,
        "firstTimerAt": [my_major_id] if starts == 0 else [],
        "amateur": bool(p.get("am")),
    }

def main(out_root: pathlib.Path) -> int:
    html = fetch_html(URL)
    payload = extract_payload(html)
    year = derive_year(payload)
    out_dir = out_root / "data" / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    for dg_id, tour_id in MAJOR_ID.items():
        block = payload.get(dg_id)
        if not block or "field" not in block:
            print(f"  skip {tour_id}: no field block")
            continue
        info = block.get("info") or {}
        field = [build_player(p, tour_id) for p in block["field"]]
        first_timers = sum(1 for p in field if tour_id in p["firstTimerAt"])
        record = {
            "year": year,
            "tournamentId": tour_id,
            "event_name": info.get("name"),
            "course": info.get("course"),
            "fetched_at": payload.get("iso") or datetime.datetime.utcnow().isoformat() + "Z",
            "source": "datagolf.com/major-fields",
            "playerCount": len(field),
            "firstTimerCount": first_timers,
            "field": field,
        }
        path = out_dir / f"{tour_id}.json"
        prev = None
        if path.exists():
            try: prev = json.loads(path.read_text())
            except Exception: pass
        # Strip fetched_at when comparing so we don't churn every run.
        def stable(r): return {k: v for k, v in r.items() if k != "fetched_at"}
        if prev is not None and stable(prev) == stable(record):
            print(f"  unchanged {tour_id}: {len(field)} players")
            continue
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        summary.append(f"{tour_id}: {len(field)} players ({first_timers} first-timers)")
        print(f"  wrote {path.relative_to(out_root)}: {len(field)} players, {first_timers} first-timers")

    if summary:
        print("\nUpdated:")
        for s in summary: print(f"  - {s}")
    else:
        print("\nNo changes.")
    return 0

if __name__ == "__main__":
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    sys.exit(main(repo_root))
