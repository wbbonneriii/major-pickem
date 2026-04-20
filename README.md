# Major Pick'em

A single-page, serverless web app for running a Men's Professional Golf Majors Pick'em league.
Snake-draft four players (one from each category), then track live scores from the ESPN public
leaderboard — no backend, no database, no API key.

**Live URL format:** `https://wbbonneriii.github.io/major-pickem/`

---

## Features

- **Four Majors** — Masters, PGA Championship, U.S. Open, The Open Championship
- **Snake draft** — 1-2-2-1 logic for 2 players, reversed-round logic for 3+
- **Four categories per player** — Top 10, International, No Major Wins, First Timers
- **Global no-duplicates** — once a player is picked in any category, they're removed everywhere
- **Live ESPN sync** — fetch current leaderboard with one click; cumulative scores, position, cut status
- **Winner rules** — (1) picker of the champion wins; (2) otherwise most cuts made; (3) tiebreaker is lowest team score
- **localStorage persistence** — your game survives refreshes
- **Shareable URL** — the whole game (users, picks, roster, scores) is encoded into a Base64 hash fragment so you can send a single link with zero infra

---

## Repository Structure

```
major-pickem/
├── index.html     # Complete SPA: HTML + Tailwind CSS (CDN) + Vanilla JS
└── README.md      # This file
```

That's it. Two files. No build step, no dependencies to install.

---

## Local Development

Just open `index.html` in a browser, or serve the directory:

```bash
# Python
python3 -m http.server 8080
# then open http://localhost:8080

# Node
npx serve .
```

The app stores state in `localStorage` under the key `major-pickem:v1`.

---

## GitHub Pages Deployment

1. Create the repository on GitHub as **`wbbonneriii/major-pickem`** (public).
2. Commit and push these two files to the `main` branch:

   ```bash
   git init
   git remote add origin https://github.com/wbbonneriii/major-pickem.git
   git add index.html README.md
   git commit -m "Initial Major Pick'em app"
   git branch -M main
   git push -u origin main
   ```

3. On GitHub: **Settings → Pages → Build & deployment → Source: Deploy from a branch**,
   select **`main`** and **`/root`**. Save.
4. Your site goes live at **https://wbbonneriii.github.io/major-pickem/** within a minute.

---

## URL Sharing Format

The **Share** button copies a URL that looks like:

```
https://wbbonneriii.github.io/major-pickem/#g=<base64-payload>
```

The `#g=` fragment contains the full game state — tournament, users, draft order, picks, roster,
and any synced scores — serialized as JSON → UTF-8 → Base64 (URL-safe). When anyone opens that
link, the app decodes the payload into `localStorage` and renders the game exactly as shared.
No server ever sees the data.

---

## Data Sources

- **ESPN PGA Leaderboard** (public, no key):
  `https://site.api.espn.com/apis/site/v2/sports/golf/pga/leaderboard`
  Used for live scoring, positions, and cut tracking. When no tournament is active, ESPN returns
  the most recent event.
- **OWGR / Majors history** — the seed field in `index.html` is a plausible 2025-era snapshot.
  Edit it in-app (Setup → Field / Roster) before each Major, or click **Pull Field from ESPN** to
  import the current event's competitors and then tag majors/first-timers by hand.

---

## Winner Determination

The scoreboard sorts teams by this priority:

1. **Champion picker wins.** If a user drafted the player in position 1 at tournament end,
   they win outright.
2. **Most cuts made (36-hole).** Otherwise, whichever team has the most players still in the
   field after the cut.
3. **Lowest cumulative team score** as tiebreaker.

---

## Notes & Limitations

- ESPN's leaderboard endpoint is unofficial and may change its response shape without notice. The
  parser in `index.html` (`applyEspnData`) is defensive but not bulletproof — if a future event
  doesn't populate, update the selectors there.
- Name matching between the local roster and ESPN is normalized (diacritics, case, punctuation)
  but exotic name variants may need manual alignment via the roster editor.
- Base64-encoded URLs can get long with many users. Browsers and most chat apps handle multi-KB
  URLs fine, but email clients sometimes wrap them — prefer copy/paste into messaging apps.

---

**Built for** [@wbbonneriii](https://github.com/wbbonneriii) • **Project:** Major Pick'em Development Plan v1.0
