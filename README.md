# Major Pick'em

A single-page, serverless web app for running a Men's Professional Golf Majors Pick'em league.
Snake-draft starters + alternates, run multiple games per tournament, and track live scores
from the ESPN public leaderboard — no backend, no database, no API key.

**Live URL:** `https://wbbonneriii.github.io/major-pickem/`

---

## Features

- **Four Majors** — Masters, PGA Championship, U.S. Open, The Open Championship
- **Multi-year** — 2024 – 2026 built in; add more in `YEAR_DATA` in `index.html`
- **Multiple games per tournament** — start as many games as you want under each Major, each with its own players, picks, and scores
- **Snake draft** — standard snake ordering (A-B → B-A → A-B…) for any number of players
- **Starter categories** (configurable quotas per game) — Top 10, Wildcard (any field player), International, No Major Wins, First Timers
- **Alternates** — each user drafts N alternates (default 2) after their starters; any field player qualifies
- **Swap starter ↔ alternate** — swap in an alternate from the scoreboard; their category label transfers with them
- **Global no-duplicates** — once a player is picked in any category, they're removed everywhere
- **Live ESPN sync** — fetch current leaderboard with one click; cumulative scores, position, cut status
- **Pull field from ESPN** — import the current event's competitor list into the roster
- **Winner rules** — (1) picker of the champion wins; (2) otherwise most cuts made; (3) tiebreaker is lowest team score
- **localStorage persistence** — games survive refreshes
- **Shareable URL** — slim Base64 hash fragment encodes only what's needed; shared links land in the recipient's saved-games list
- **Shared async draft rooms** — text/email each player a link and run the snake draft from separate phones, on your own time; picks sync automatically and each person is notified when it's their turn (requires a one-time free Firebase Realtime Database URL — see below)

---

## Repository Structure

```
major-pickem/
├── index.html                        # Complete SPA: HTML + Tailwind CSS (CDN) + Vanilla JS
├── README.md                         # This file
├── Master_Development_Plan_v2.md     # As-built plan (v2.0)
├── data/<year>/<id>.json             # Pre-fetched fields (majors) + cup feeds (ryder/presidents)
├── scripts/
│   ├── fetch-fields.py               # Majors field puller (DataGolf)
│   └── fetch-cup.py                  # Ryder/Presidents Cup feed puller (ESPN core API)
└── .github/workflows/
    ├── update-fields.yml             # Cron: refresh major fields
    └── update-cups.yml               # Cron: refresh cup pairings + live results
```

No build step, no dependencies to install.

---

## Local Development

Open `index.html` directly in a browser, or serve the directory:

```bash
# Python
python3 -m http.server 8080
# then open http://localhost:8080

# Node
npx serve .
```

The app uses two `localStorage` keys:

- `major-pickem:v1` — the game currently in view.
- `major-pickem:games:v1` — the multi-game store, keyed by `gameId`.

---

## GitHub Pages Deployment

1. Create the repository on GitHub as **`wbbonneriii/major-pickem`** (public).
2. Commit and push to the `main` branch:

   ```bash
   git init
   git remote add origin https://github.com/wbbonneriii/major-pickem.git
   git add index.html README.md Master_Development_Plan_v2.md
   git commit -m "Major Pick'em v2 — multi-game support"
   git branch -M main
   git push -u origin main
   ```

3. On GitHub: **Settings → Pages → Build & deployment → Source: Deploy from a branch**,
   select **`main`** and **`/root`**. Save.
4. Your site goes live at **https://wbbonneriii.github.io/major-pickem/** within a minute.

---

## Multi-Game Workflow

1. **Home page** lists all four Majors with a `+ New Game` button on each card.
2. Click `+ New Game` under a tournament to start a fresh draft — it's auto-named
   `<Major> Game N` and appears immediately in that card's game list.
3. Each saved game shows its players, a phase pill (Setup / In Progress / Complete),
   and a `✕` delete button.
4. Click a game row to resume it. `Home` in the nav returns without losing anything —
   all games are saved to the games store.
5. `Reset` deletes only the game currently in view.

---

## URL Sharing Format

The **Share** button (on the scoreboard) opens a modal with a URL like:

```
https://wbbonneriii.github.io/major-pickem/#g=<base64-payload>
```

The `#g=` fragment contains a **slimmed** game state — only the players referenced by
picks plus the tournament winner — serialized as JSON → UTF-8 → Base64 (URL-safe). This
keeps typical share URLs under ~6 KB instead of tens of KB.

When anyone opens the link:

- The payload decodes into the recipient's `localStorage`.
- A fresh `gameId` is minted so the shared game lands in their games list.
- The current view renders the shared game exactly as sent.

No server ever sees the data.

---

## Shared Async Draft Rooms

Run a snake draft with someone who isn't sitting next to you — each player drafts from their
own phone, whenever it's their turn. This is built for the two-game-per-major pattern (e.g.
the Tim/Hodge game) where a live call isn't possible.

**How it works**

1. **Host** sets up players + categories and clicks **Start Snake Draft** as usual.
2. On the draft screen, click **📲 Shared Room**. The app creates a room and shows one
   link **per player** (identity baked into each link), with **Text** and **Email** buttons.
3. Send each other player their link. They open it, the app drops them straight into the
   draft **as that player**, and shows the live board.
4. Whoever is on the clock makes their pick; everyone else sees a **"Waiting on …"** card
   that refreshes every few seconds and buzzes/notifies when it becomes their turn.
5. The draft is done when all picks are in — the scoreboard appears for everyone, and each
   device syncs ESPN scores on its own.

The room only carries the draft (players, picks, field) — not live scores. Anyone with a
link can draft as that player, so treat the links like the draft itself (low-stakes golf
picks, no logins).

**One-time setup (free, ~10 min)** — enables rooms for all future majors:

1. Go to [console.firebase.google.com](https://console.firebase.google.com) → **Add project** (any name; you can skip Analytics).
2. **Build → Realtime Database → Create Database → Start in test mode.**
3. Copy the database URL shown at the top of the **Data** tab — it looks like
   `https://major-pickem-xxxx-default-rtdb.firebaseio.com`.
4. In `index.html`, paste it into the `FIREBASE_DB_URL` constant near the top
   (`const FIREBASE_DB_URL = 'https://…';`) and re-upload to GitHub.

That's it — no API key needed (the REST endpoint + default `/rooms` rules are enough).
Leave `FIREBASE_DB_URL` blank to keep the app single-device; the one-shot **Share** link
on the scoreboard still works either way.

> Test mode rules expire after 30 days. To keep rooms working long-term, set the Realtime
> Database rules to allow read/write only under `/rooms`:
> ```json
> { "rules": { "rooms": { ".read": true, ".write": true } } }
> ```

## Team Events (Ryder Cup & Presidents Cup)

A second game **mode** for the biennial team match-play events, shown under **Team Events** on
the home page (below the four Majors). Instead of drafting golfers, each participant **predicts
every match's winner and margin**.

- **Ryder Cup** — USA vs **Europe**, odd years (2027, 2029…). 12/side, 3 days, **28 matches**,
  14½ to win (14–14 → holder retains).
- **Presidents Cup** — USA vs **International**, even years (2026, 2028…). 12/side, 4 days,
  **30 matches**, 15½ to win (tie → shared).

**Flow**
1. **Setup** — pick the year, enter each 12-player team, add participants, and **Build standard
   sessions** (the correct 28/30-match skeleton). Choose the host (commissioner).
2. **Matches & Picks** — the host confirms pairings as captains announce them and flips a session
   to **In Progress** (which **locks** that session's picks) then **Final**, entering each match's
   winner + margin. Participants predict winner + margin for every open match.
3. **Scoreboard** — a live USA-vs-opponent Cup tally with a to-win marker, the in-progress and
   final matches, and a **participant leaderboard**.

**Scoring** — **1 point** for the correct winner (a correctly predicted halved match counts),
**+1 bonus** for the exact margin (e.g. you said `2&1` and it finished `2&1`).

**Remote picking** — the same shared-room mechanism as the snake draft: the host opens a room and
sends each participant their own link; everyone picks from their own phone and the board syncs.
(Requires the one-time `FIREBASE_DB_URL` setup above; local play works without it.)

**Auto-sync from ESPN** — pairings and live results sync automatically, same idea as the Majors:
`scripts/fetch-cup.py` walks ESPN's public core API (one competition per match) and writes a flat
`data/<year>/<cupType>.json`, refreshed by `.github/workflows/update-cups.yml` (every ~10 min;
cheap off-season). The app reads that file same-origin — **↻ Sync ESPN** in the hub/scoreboard, plus
a ~60s auto-poll. Switch a game to **Manual** to enter everything by hand; editing any pairing or
result **pins** it (📌) so the feed won't overwrite you. Run the fetch locally with:

```bash
python3 scripts/fetch-cup.py --year 2025 --cup ryder   # writes data/2025/ryder.json
python3 scripts/fetch-cup.py                            # auto: current + next year's cups
```

The event id is auto-discovered from the year; override with `--event <espnId>` (or the **Event ID**
field in Setup) for a brand-new event ESPN hasn't tagged yet.

## Data Sources

- **ESPN PGA Leaderboard** (public, no key):
  `https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard`
  Used for live scoring, positions, and cut tracking. When no tournament is active, ESPN returns
  the most recent event. Year-specific events are fetched via `espnEventId` in `YEAR_DATA`.
- **ESPN Golf core API** (public, no key) for **Team Events**:
  `https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/events/<id>` — a Ryder/Presidents
  Cup event exposes one `competition` per match (foursome/fourball/singles) with pairings, live
  status, and the match-play margin. `scripts/fetch-cup.py` flattens this server-side into
  `data/<year>/<cupType>.json`.
- **Seed field** — the `SEED_FIELD` constant in `index.html` is a curated 2026 Masters-week
  snapshot (OWGR Top 15, ranked pros, LIV golfers with deflated OWGR, and the 2026 Masters
  first-timers). Edit in-app (Setup → Field / Roster) before each Major, or click
  **Pull Field from ESPN** to import the current event's competitors and tag majors/first-timers
  by hand. The `SEED_VERSION` constant triggers an automatic roster refresh when bumped.

---

## Winner Determination

The scoreboard sorts teams by this priority:

1. **Champion picker wins.** If a user drafted the player in position 1 at tournament end,
   they win outright.
2. **Most cuts made (36-hole).** Otherwise, whichever team has the most players still in the
   field after the cut.
3. **Lowest cumulative team score** as tiebreaker.

Alternate picks never count unless explicitly swapped in via the scoreboard.

---

## Notes & Limitations

- ESPN's leaderboard endpoint is unofficial and may change its response shape without notice. The
  parser in `index.html` (`applyEspnData`) is defensive but not bulletproof — if a future event
  doesn't populate, update the selectors there.
- Name matching between the local roster and ESPN is normalized (diacritics, case, punctuation)
  but exotic name variants may need manual alignment via the roster editor.
- Share URLs are slimmed, but with many users and deep rosters can still reach a few KB. Browsers
  and most chat apps handle this fine; email clients sometimes wrap long URLs — prefer copy/paste
  into messaging apps.
- The scoreboard **Share** button is the only entry point for sharing; there is no nav-level
  share to avoid duplication.

---

**Built for** [@wbbonneriii](https://github.com/wbbonneriii) • **Project:** Major Pick'em Development Plan **v2.0 (As Built)**
