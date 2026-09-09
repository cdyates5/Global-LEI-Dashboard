# Global Growth Leading Indicators

A self-contained, auto-refreshing dashboard of Variant-Perception-style growth
leading indicators for the **US, Australia, UK, Euro Area, Japan and China**,
each calibrated to a 3–6 month lead versus GDP (China also validated vs actual
GDP over history). Data is pulled from FRED; the page is a single HTML file with
the data baked in.

## How it works
- **`build.py`** — fetches ~49 series from the FRED API, rebuilds the six
  composites, and injects the result into `template.html`, writing `index.html`.
- **`template.html`** — the dashboard shell (all CSS/JS) with a `/*__DATA__*/{}`
  placeholder that `build.py` fills.
- **`.github/workflows/refresh.yml`** — runs `build.py` on a schedule and
  publishes `index.html` to GitHub Pages.
- `index.html` is a **build artifact** (git-ignored); CI regenerates it each run.

## One-time setup
1. Create a new GitHub repo and add these files.
2. Get a free FRED API key: https://fredaccount.stlouisfed.org/apikeys
3. Repo → **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `FRED_API_KEY`   Value: *your key*
4. Repo → **Settings → Pages → Build and deployment → Source: GitHub Actions**
5. Repo → **Actions** tab → enable workflows if prompted → run **Refresh
   dashboard** once (`Run workflow`), or wait for the schedule.
6. The site publishes at `https://<your-username>.github.io/<repo-name>/`.

## Run locally
```bash
pip install -r requirements.txt
export FRED_API_KEY=your_key_here      # Windows: set FRED_API_KEY=your_key_here
python build.py                        # writes index.html
open index.html                        # or just double-click it
```

## Change the schedule
Edit the `cron` line in `.github/workflows/refresh.yml`
(e.g. weekly Mondays: `0 6 * * 1`). Times are UTC.

## Notes
- Most inputs are monthly, so readings move on data-release days, not daily.
- BIS credit legs are quarterly and carried forward up to two quarters.
- Euro-area survey series publish to FRED on a lag; the board stays current via a
  Bund-minus-policy yield curve and other timely legs.
- If FRED renames/discontinues a series, that leg is dropped automatically; the
  build aborts only if more than six series fail to fetch.
