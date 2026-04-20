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
- **Starter categories** (configurable quotas per game) — Top 10, International, No Major Wins, First Timers
- **Alternates** — each user drafts N alternates (default 2) after their starters; any field player qualifies
- **Swap starter ↔ alternate** — swap in an alternate from the scoreboard; their category label transfers with them
- **Global no-duplicates** — once a player is picked in any category, they're removed everywhere
- **Live ESPN sync** — fetch current leaderboard with one click; cumulative scores, position, cut status
- **Pull field from ESPN** — import the current event's competitor list into the roster
- **Winner rules** — (1) picker of the champion wins; (2) otherwise most cuts made; (3) tiebreaker is lowest team score
- **localStorage persistence** — games survive refreshes
- **Shareable URL** — slim Base64 hash fragment encodes only what's needed; shared links land in the recipient's saved-games list

---

## Repository Structure

```
major-pickem/
├── index.html                    # Complete SPA: HTML + Tailwind CSS (CDN) + Vanilla JS
├── README.md                     # This file
└── Master_Development_Plan_v2.md # As-built plan (v2.0)
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

## Data Sources

- **ESPN PGA Leaderboard** (public, no key):
  `https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard`
  Used for live scoring, positions, and cut tracking. When no tournament is active, ESPN returns
  the most recent event. Year-specific events are fetched via `espnEventId` in `YEAR_DATA`.
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
