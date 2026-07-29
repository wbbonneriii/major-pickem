#!/usr/bin/env python3
"""Fetch a team-match Cup (Ryder Cup / Presidents Cup) from ESPN and write a flat JSON feed.

Output files: data/{year}/{cupType}.json where cupType in {ryder, presidents}.

Run locally:
    python3 scripts/fetch-cup.py                 # all configured cups, current + upcoming years
    python3 scripts/fetch-cup.py --year 2025 --cup ryder
    python3 scripts/fetch-cup.py --year 2026 --cup presidents --event 401XXXXXX

Run in CI: see .github/workflows/update-cups.yml

WHY this exists: ESPN's core API models a Cup event as one `competition` PER MATCH
(28 for a Ryder Cup, 30 for a Presidents Cup), each deeply $ref-nested. Flattening one
event is ~140 requests — far too heavy for the browser to poll. So we pre-flatten here,
server-side, into a small same-origin JSON the app reads (no CORS, no key), exactly like
scripts/fetch-fields.py does for the majors. The app merges this feed into a cup game,
never overwriting the host's manually pinned pairings/results, and never touching picks.

Validated against the completed 2025 Ryder Cup (event 401734110): reproduces Europe 15-13,
including all 6 halved Sunday singles, with correct sessions / pairings / margins.
"""
import argparse, json, re, sys, urllib.request, pathlib, datetime

CORE = "https://sports.core.api.espn.com/v2/sports/golf/leagues/pga"

# Which cups we know about and how to recognize their ESPN event names. Auto-discovery
# scans the year's PGA events for a "Cup" scoring system whose name matches; --event overrides.
CUPS = {
    "ryder":      {"needle": "ryder cup",      "teamB": "Europe"},
    "presidents": {"needle": "presidents cup", "teamB": "International"},
}
# ESPN "type.text" for a match -> our session/match type.
TYPE_MAP = {"foursome": "foursomes", "fourball": "fourballs", "singles": "singles"}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (major-pickem cup updater)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def norm_id(name: str) -> str:
    return "espn_" + re.sub(r"[^a-z]+", "_", (name or "").lower()).strip("_")


def discover_event(year: int, needle: str):
    """Return (eventId, eventName) for the Cup in `year`, or (None, None)."""
    try:
        lst = get(f"{CORE}/events?limit=100&dates={year}")
    except Exception as e:
        print(f"  discover: events list failed ({e})")
        return None, None
    for item in lst.get("items", []):
        ref = item.get("$ref", "")
        m = re.search(r"/events/(\d+)", ref)
        if not m:
            continue
        try:
            ev = get(ref)
        except Exception:
            continue
        name = (ev.get("name") or "")
        comps = ev.get("competitions") or []
        scoring = (comps[0].get("scoringSystem", {}).get("name", "") if comps else "")
        if needle in name.lower() and scoring.lower() == "cup":
            return m.group(1), name
    return None, None


def team_side(team_ref_cache, ref: str) -> str:
    """Resolve a team $ref to 'usa' or 'intl'. Cached to avoid refetching."""
    if ref not in team_ref_cache:
        try:
            t = get(ref)
            nm = (t.get("displayName") or t.get("name") or t.get("abbreviation") or "").lower()
        except Exception:
            nm = ""
        team_ref_cache[ref] = "usa" if ("united states" in nm or nm in ("usa", "us")) else "intl"
    return team_ref_cache[ref]


def athlete_names(cp: dict):
    """Player display names for a competitor, handling both foursome/fourball rosters
    and the flatter singles shape."""
    names = []
    roster = cp.get("roster")
    if isinstance(roster, dict) and "$ref" in roster:
        try:
            r = get(roster["$ref"])
            for e in r.get("entries", []):
                a = e.get("athlete", {})
                nm = a.get("displayName") or (get(a["$ref"]).get("displayName") if "$ref" in a else None)
                if nm:
                    names.append(nm)
        except Exception:
            pass
    if not names:
        # Singles: the athlete may hang directly off the resolved competitor.
        try:
            full = get(cp["$ref"]) if "$ref" in cp else cp
            a = full.get("athlete", {})
            nm = a.get("displayName") or (get(a["$ref"]).get("displayName") if "$ref" in a else None)
            if nm:
                names.append(nm)
        except Exception:
            pass
    return names


def score_display(cp: dict):
    """(displayValue, numericValue) for a competitor's match score, resolving the $ref."""
    sc = cp.get("score")
    if isinstance(sc, dict) and "$ref" in sc:
        try:
            sc = get(sc["$ref"])
        except Exception:
            return None, None
    if isinstance(sc, dict):
        return sc.get("displayValue"), sc.get("value")
    return None, None


def match_status(cp_comp: dict) -> str:
    st = cp_comp.get("status")
    if isinstance(st, dict) and "$ref" in st:
        try:
            st = get(st["$ref"])
        except Exception:
            st = {}
    state = ((st or {}).get("type") or {}).get("state")
    return {"pre": "scheduled", "in": "inprogress", "post": "final"}.get(state, "scheduled")


def is_win(disp, val) -> bool:
    if val is not None:
        try:
            return float(val) >= 1
        except Exception:
            pass
    if not disp:
        return False
    d = disp.strip().lower()
    return ("&" in d) or ("up" in d)


def is_half(disp, val) -> bool:
    if disp and disp.strip().lower() in ("halved", "as", "a/s", "tied"):
        return True
    try:
        return val is not None and abs(float(val) - 0.5) < 1e-6
    except Exception:
        return False


def flatten(event_id: str, cup_type: str, team_b_default: str):
    ev = get(f"{CORE}/events/{event_id}?lang=en&region=us")
    event_name = ev.get("name")
    team_cache = {}
    matches = []
    team_names = {"usa": "United States", "intl": team_b_default}

    for c in ev.get("competitions", []):
        t = (c.get("type") or {}).get("text")
        if t == "tournament" or t not in TYPE_MAP:
            continue
        m = get(c["$ref"]) if "$ref" in c else c
        comps = m.get("competitors", [])
        if len(comps) != 2:
            continue
        by_side = {}
        for cp in comps:
            side = team_side(team_cache, cp.get("team", {}).get("$ref", ""))
            disp, val = score_display(cp)
            by_side[side] = {
                "players": athlete_names(cp),
                "disp": disp, "val": val,
            }
        # Guard against both resolving to the same side (shouldn't happen, but be safe).
        if "usa" not in by_side or "intl" not in by_side:
            sides = list(by_side.keys())
            continue
        usa, intl = by_side["usa"], by_side["intl"]
        status = match_status(m)
        winner, margin = None, None
        if is_half(usa["disp"], usa["val"]) or is_half(intl["disp"], intl["val"]):
            winner, margin = "tie", "Halved"
        elif is_win(usa["disp"], usa["val"]):
            winner, margin = "usa", usa["disp"]
        elif is_win(intl["disp"], intl["val"]):
            winner, margin = "intl", intl["disp"]
        matches.append({
            "espnId": str(m.get("id")),
            "type": TYPE_MAP[t],
            "date": m.get("date"),
            "sessionName": m.get("description") or "",
            "teamA": usa["players"],   # USA
            "teamB": intl["players"],  # opponent
            "result": {"winner": winner, "margin": margin},
            "status": status,
        })

    # Group matches into sessions by description; order by earliest match date.
    sessions = {}
    for mt in matches:
        key = mt["sessionName"] or f'{mt["type"]}'
        s = sessions.setdefault(key, {"name": key, "type": mt["type"], "date": mt["date"], "matches": []})
        s["matches"].append(mt)
        if mt["date"] and (not s["date"] or mt["date"] < s["date"]):
            s["date"] = mt["date"]
    ordered = sorted(sessions.values(), key=lambda s: s["date"] or "")

    # Derive a day number from calendar date; compute session status from its matches.
    day_dates = sorted({(s["date"] or "")[:10] for s in ordered if s["date"]})
    day_index = {d: i + 1 for i, d in enumerate(day_dates)}
    out_sessions = []
    usa_pts = intl_pts = 0.0
    for order, s in enumerate(ordered, 1):
        statuses = {mm["status"] for mm in s["matches"]}
        sess_status = ("final" if statuses == {"final"}
                       else "inprogress" if ("inprogress" in statuses or "final" in statuses)
                       else "scheduled")
        for mm in s["matches"]:
            r = mm["result"]
            if mm["status"] == "final":
                if r["winner"] == "usa":
                    usa_pts += 1
                elif r["winner"] == "intl":
                    intl_pts += 1
                elif r["winner"] == "tie":
                    usa_pts += 0.5
                    intl_pts += 0.5
        out_sessions.append({
            "espnId": None,
            "name": s["name"],
            "day": day_index.get((s["date"] or "")[:10], order),
            "order": order,
            "type": s["type"],
            "status": sess_status,
            "matches": [{
                "espnId": mm["espnId"],
                "teamA": mm["teamA"],
                "teamB": mm["teamB"],
                "result": mm["result"],
                "status": mm["status"],
            } for mm in s["matches"]],
        })

    return {
        "cupType": cup_type,
        "eventId": str(event_id),
        "event_name": event_name,
        "teams": {
            "usa": {"name": team_names["usa"]},
            "intl": {"name": team_names["intl"]},
        },
        "sessions": out_sessions,
        "cupScore": {"usa": usa_pts, "intl": intl_pts},
        "source": "espn-core",
    }


def write_feed(out_root: pathlib.Path, year: int, record: dict) -> bool:
    out_dir = out_root / "data" / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'{record["cupType"]}.json'
    record = dict(record)
    record["year"] = year
    record["fetched_at"] = datetime.datetime.utcnow().isoformat() + "Z"

    def stable(r):
        return {k: v for k, v in r.items() if k != "fetched_at"}

    prev = None
    if path.exists():
        try:
            prev = json.loads(path.read_text())
        except Exception:
            pass
    if prev is not None and stable(prev) == stable(record):
        print(f"  unchanged {record['cupType']} {year}")
        return False
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    nmatch = sum(len(s["matches"]) for s in record["sessions"])
    cs = record["cupScore"]
    print(f"  wrote {path.relative_to(out_root)}: {len(record['sessions'])} sessions, "
          f"{nmatch} matches, USA {cs['usa']}-{cs['intl']} {record['teams']['intl']['name']}")
    return True


def default_targets():
    """Cups worth checking now: the current year's cup by parity, plus the next year's."""
    y = datetime.datetime.utcnow().year
    targets = []
    for yr in (y, y + 1):
        cup = "presidents" if yr % 2 == 0 else "ryder"
        targets.append((yr, cup))
    return targets


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch a Ryder/Presidents Cup feed from ESPN.")
    ap.add_argument("--year", type=int)
    ap.add_argument("--cup", choices=list(CUPS.keys()))
    ap.add_argument("--event", help="ESPN event id (skips auto-discovery)")
    args = ap.parse_args()

    repo_root = pathlib.Path(__file__).resolve().parent.parent

    if args.year and args.cup:
        targets = [(args.year, args.cup)]
    elif args.year or args.cup:
        ap.error("--year and --cup must be used together (or pass neither for defaults)")
    else:
        targets = default_targets()

    changed = 0
    for year, cup in targets:
        cfg = CUPS[cup]
        print(f"{cup} {year}:")
        event_id = args.event
        if not event_id:
            event_id, ev_name = discover_event(year, cfg["needle"])
            if not event_id:
                print("  no ESPN Cup event found (not scheduled yet or off-season) — skipping")
                continue
            print(f"  discovered event {event_id} ({ev_name})")
        try:
            record = flatten(event_id, cup, cfg["teamB"])
        except Exception as e:
            print(f"  flatten failed: {e}")
            continue
        if write_feed(repo_root, year, record):
            changed += 1

    print("\nNo changes." if not changed else f"\nUpdated {changed} feed(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
