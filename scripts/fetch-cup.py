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
event is ~50 requests — far too heavy for the browser to poll. So we pre-flatten here,
server-side, into a small same-origin JSON the app reads (no CORS, no key), exactly like
scripts/fetch-fields.py does for the majors. The app merges this feed into a cup game,
never overwriting the host's manually pinned pairings/results, and never touching picks.

Validated against the completed 2025 Ryder Cup (event 401734110): reproduces Europe 15-13,
including all 6 halved Sunday singles, with correct sessions / pairings / margins.

--------------------------------------------------------------------------------
FAILURE HISTORY — read before loosening anything below (2026-09-23)
--------------------------------------------------------------------------------
The 2026 Presidents Cup feed sat at `"sessions": []` for a week while the workflow
reported success on every run. Cause, in order:

  1. A no-args run fired ~132 sequential requests (41 to discover the Presidents Cup,
     53 to flatten it, 38 more scanning for a 2027 Ryder Cup that does not exist yet),
     every 10 minutes -> ~19k requests/day from shared Actions IPs. ESPN throttled it.
  2. Every fetch was wrapped in a bare `except Exception` that returned a default.
  3. Worst of these: team_side() fell back to "intl" when the team lookup failed, so
     BOTH competitors resolved to the same side and the len(by_side)!=2 guard silently
     DROPPED every match -> 0 sessions, no traceback.
  4. The script still exited 0, so the workflow went green and nobody was told.
  5. 0 sessions then compared equal to the committed 0-session file -> "unchanged"
     -> never committed, so the feed could never heal itself.

The rules that keep that from recurring:
  - Distinguish ABSENT (404 -> legitimately not published yet) from FAILED
    (429/5xx/timeout -> retry, then raise). Never let a failure look like absence.
  - A dropped match is a bug, not a data condition. flatten() raises on one.
  - Never write a feed that is smaller than the one on disk (see write_feed).
  - Exit non-zero when a target fails, so the workflow goes red.
  - Keep request volume low: pin known event ids, and bail early when the event is
    outside its own start/end window.
"""
import argparse, json, re, sys, time, urllib.request, urllib.error, pathlib, datetime

CORE = "https://sports.core.api.espn.com/v2/sports/golf/leagues/pga"

# Which cups we know about and how to recognize their ESPN event names. Auto-discovery
# scans the year's PGA events for a "Cup" scoring system whose name matches; --event overrides.
CUPS = {
    "ryder":      {"needle": "ryder cup",      "teamB": "Europe"},
    "presidents": {"needle": "presidents cup", "teamB": "International"},
}
# Event ids we have already resolved. Discovery costs ~40 requests; a hit here costs 0.
# Add a row the first time a new cup is discovered (the script prints the line to paste).
KNOWN_EVENTS = {
    (2025, "ryder"):      "401734110",
    (2026, "presidents"): "401824815",
}
# ESPN "type.text" for a match -> our session/match type.
TYPE_MAP = {"foursome": "foursomes", "fourball": "fourballs", "singles": "singles"}
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

RETRIES = 4
BACKOFF = 1.75          # seconds, exponential
THROTTLE = 0.05         # polite gap between requests


class CupFetchError(RuntimeError):
    """A request failed in a way that must NOT be mistaken for missing data."""


_cache = {}
_stats = {"requests": 0, "retries": 0, "cached": 0}


def get(url: str, allow_missing: bool = False):
    """Fetch and parse JSON, with retries.

    Returns None only when the resource is genuinely absent (404) AND the caller
    passed allow_missing. Any other failure raises CupFetchError after RETRIES.
    """
    if url in _cache:
        _stats["cached"] += 1
        return _cache[url]

    last = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (major-pickem cup updater)",
                "Accept": "application/json",
            })
            _stats["requests"] += 1
            with urllib.request.urlopen(req, timeout=30) as r:
                doc = json.loads(r.read().decode("utf-8", errors="replace"))
            _cache[url] = doc
            time.sleep(THROTTLE)
            return doc
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                # Genuinely not published (e.g. no score on a match that has not teed off).
                if allow_missing:
                    _cache[url] = None
                    return None
                raise CupFetchError(f"404 {url}")
            if e.code not in (408, 425, 429, 500, 502, 503, 504):
                raise CupFetchError(f"HTTP {e.code} {url}")
            wait = float(e.headers.get("Retry-After") or 0) or BACKOFF ** attempt
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            last = e
            wait = BACKOFF ** attempt

        if attempt < RETRIES - 1:
            _stats["retries"] += 1
            time.sleep(wait)

    raise CupFetchError(f"{type(last).__name__} after {RETRIES} attempts: {url} ({last})")


def norm_id(name: str) -> str:
    return "espn_" + re.sub(r"[^a-z]+", "_", (name or "").lower()).strip("_")


def discover_event(year: int, needle: str):
    """Return (eventId, eventName) for the Cup in `year`, or (None, None) if not scheduled.

    Costs ~40 requests, so prefer KNOWN_EVENTS / --event. Raises on transport failure
    rather than reporting "not scheduled", which is a very different thing.
    """
    lst = get(f"{CORE}/events?limit=100&dates={year}")
    for item in lst.get("items", []):
        ref = item.get("$ref", "")
        m = re.search(r"/events/(\d+)", ref)
        if not m:
            continue
        ev = get(ref)
        name = (ev.get("name") or "")
        if needle not in name.lower():
            continue
        comps = ev.get("competitions") or []
        scoring = (comps[0].get("scoringSystem", {}).get("name", "") if comps else "")
        if scoring.lower() == "cup":
            return m.group(1), name
    return None, None


def team_side(ref: str) -> str:
    """Resolve a team $ref to 'usa' or 'intl'.

    Raises rather than guessing. A wrong guess here collapses both competitors onto one
    side and the match is dropped downstream -- the exact bug that emptied the 2026 feed.
    """
    if not ref:
        raise CupFetchError("competitor has no team $ref")
    t = get(ref)
    nm = (t.get("displayName") or t.get("name") or t.get("abbreviation") or "").lower()
    if not nm:
        raise CupFetchError(f"team {ref} has no name")
    return "usa" if ("united states" in nm or nm in ("usa", "us")) else "intl"


def athlete_names(cp: dict):
    """Player display names for a competitor, handling both foursome/fourball rosters
    and the flatter singles shape. Raises if neither shape yields a name."""
    names = []
    roster = cp.get("roster")
    if isinstance(roster, dict) and "$ref" in roster:
        r = get(roster["$ref"], allow_missing=True)
        for e in (r or {}).get("entries", []):
            a = e.get("athlete", {})
            nm = a.get("displayName")
            if not nm and "$ref" in a:
                nm = (get(a["$ref"], allow_missing=True) or {}).get("displayName")
            if nm:
                names.append(nm)
    if not names:
        # Singles: the athlete may hang directly off the resolved competitor.
        full = get(cp["$ref"]) if "$ref" in cp else cp
        a = full.get("athlete", {})
        nm = a.get("displayName")
        if not nm and "$ref" in a:
            nm = (get(a["$ref"], allow_missing=True) or {}).get("displayName")
        if nm:
            names.append(nm)
    if not names:
        raise CupFetchError(f"no athlete names for competitor {cp.get('$ref') or cp.get('id')}")
    return names


def score_display(cp: dict):
    """(displayValue, numericValue) for a competitor's match score, resolving the $ref.

    A scheduled match has no score yet; that 404 is absence, not failure."""
    sc = cp.get("score")
    if isinstance(sc, dict) and "$ref" in sc:
        sc = get(sc["$ref"], allow_missing=True)
    if isinstance(sc, dict):
        return sc.get("displayValue"), sc.get("value")
    return None, None


def match_status(cp_comp: dict) -> str:
    st = cp_comp.get("status")
    if isinstance(st, dict) and "$ref" in st:
        st = get(st["$ref"], allow_missing=True) or {}
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


def event_is_dormant(ev: dict) -> bool:
    """True when the event is far enough outside its own window that nothing can change.

    Keeps off-week runs at ~2 requests instead of ~50. One day of slack on each side
    covers timezone skew and ESPN publishing pairings the evening before."""
    today = datetime.datetime.now(datetime.timezone.utc).date()
    try:
        start = datetime.date.fromisoformat((ev.get("date") or "")[:10])
        end = datetime.date.fromisoformat((ev.get("endDate") or ev.get("date") or "")[:10])
    except ValueError:
        return False
    return not (start - datetime.timedelta(days=2) <= today <= end + datetime.timedelta(days=1))


def flatten(event_id: str, cup_type: str, team_b_default: str):
    ev = get(f"{CORE}/events/{event_id}?lang=en&region=us")
    event_name = ev.get("name")
    matches = []
    dropped = []
    team_names = {"usa": "United States", "intl": team_b_default}

    for c in ev.get("competitions", []):
        t = (c.get("type") or {}).get("text")
        if t == "tournament" or t not in TYPE_MAP:
            continue
        m = get(c["$ref"]) if "$ref" in c else c
        comps = m.get("competitors", [])
        if len(comps) != 2:
            dropped.append(f'{m.get("id")}: {len(comps)} competitors')
            continue
        by_side = {}
        for cp in comps:
            side = team_side(cp.get("team", {}).get("$ref", ""))
            disp, val = score_display(cp)
            by_side[side] = {"players": athlete_names(cp), "disp": disp, "val": val}
        if "usa" not in by_side or "intl" not in by_side:
            # Both competitors resolved to the same side. Real data never looks like this,
            # so treat it as a fault rather than quietly losing the match.
            dropped.append(f'{m.get("id")}: both competitors resolved to {list(by_side)[0]}')
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
        # A match still on the course has a running margin ("2 UP"), not a result.
        # Publishing a winner before it is final would show the group a decided match.
        if status != "final":
            winner, margin = None, None
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

    if dropped:
        raise CupFetchError("dropped %d match(es): %s" % (len(dropped), "; ".join(dropped)))

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
            # Tee times, carried through so the app can lock picks on the clock rather than
            # waiting for this feed to say a match is in progress. GitHub throttles the
            # workflow to hours, so a status-only lock would leave picks open during play.
            "date": s["date"],
            "matches": [{
                "espnId": mm["espnId"],
                "teamA": mm["teamA"],
                "teamB": mm["teamB"],
                "result": mm["result"],
                "status": mm["status"],
                "date": mm["date"],
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


def _size(record) -> tuple:
    return (len(record.get("sessions", [])),
            sum(len(s.get("matches", [])) for s in record.get("sessions", [])))


def write_feed(out_root: pathlib.Path, year: int, record: dict, allow_shrink: bool = False) -> bool:
    out_dir = out_root / "data" / str(year)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f'{record["cupType"]}.json'
    record = dict(record)
    record["year"] = year
    record["fetched_at"] = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    def stable(r):
        return {k: v for k, v in r.items() if k != "fetched_at"}

    prev = None
    if path.exists():
        try:
            prev = json.loads(path.read_text())
        except Exception:
            pass

    # A feed never legitimately loses sessions or matches. If this run produced less than
    # what is already published, something upstream failed -- keep the good file and fail.
    if prev and not allow_shrink:
        was, now = _size(prev), _size(record)
        if now < was:
            raise CupFetchError(
                f"refusing to shrink {path.name}: on disk {was[0]} sessions/{was[1]} matches, "
                f"this run {now[0]}/{now[1]}. Pass --allow-shrink if this is genuinely correct."
            )

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
    y = datetime.datetime.now(datetime.timezone.utc).year
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
    ap.add_argument("--discover", action="store_true",
                    help="Force a full event scan even when the year/cup is in KNOWN_EVENTS")
    ap.add_argument("--force", action="store_true",
                    help="Fetch even when the event is outside its own date window")
    ap.add_argument("--allow-shrink", action="store_true",
                    help="Permit writing a feed with fewer matches than the published one")
    ap.add_argument("--out", help="Write under this root instead of the repo (for previewing)")
    args = ap.parse_args()

    repo_root = pathlib.Path(args.out).resolve() if args.out else pathlib.Path(__file__).resolve().parent.parent

    if args.year and args.cup:
        targets = [(args.year, args.cup)]
    elif args.year or args.cup:
        ap.error("--year and --cup must be used together (or pass neither for defaults)")
    else:
        targets = default_targets()

    changed = 0
    failed = []
    for year, cup in targets:
        cfg = CUPS[cup]
        print(f"{cup} {year}:")
        try:
            event_id = args.event or (None if args.discover else KNOWN_EVENTS.get((year, cup)))
            if event_id:
                print(f"  event {event_id} (pinned)")
            elif year > datetime.datetime.now(datetime.timezone.utc).year and not args.discover:
                # ESPN does not create next year's Cup until its own season opens, so a scan
                # now costs ~40 requests to learn nothing. Pass --discover to force one.
                print("  next season — not scanned yet (use --discover to force)")
                continue
            else:
                event_id, ev_name = discover_event(year, cfg["needle"])
                if not event_id:
                    print("  no ESPN Cup event found (not scheduled yet or off-season) — skipping")
                    continue
                print(f'  discovered event {event_id} ({ev_name})')
                print(f'  -> add to KNOWN_EVENTS: ({year}, "{cup}"): "{event_id}",')

            if not args.force:
                ev = get(f"{CORE}/events/{event_id}?lang=en&region=us")
                if event_is_dormant(ev):
                    print(f'  dormant ({(ev.get("date") or "?")[:10]} to {(ev.get("endDate") or "?")[:10]}) — skipping')
                    continue

            record = flatten(event_id, cup, cfg["teamB"])
            if write_feed(repo_root, year, record, allow_shrink=args.allow_shrink):
                changed += 1
        except CupFetchError as e:
            print(f"  FAILED: {e}")
            failed.append(f"{cup} {year}: {e}")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            failed.append(f"{cup} {year}: {type(e).__name__}: {e}")

    print(f"\n[{_stats['requests']} requests, {_stats['retries']} retries, {_stats['cached']} cached]")
    if failed:
        print("FAILED:\n  - " + "\n  - ".join(failed), file=sys.stderr)
        return 1
    print("No changes." if not changed else f"Updated {changed} feed(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
