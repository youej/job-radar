# Job Radar

A daily-refreshed job board for early-career **product management, product marketing, and strategy / BizOps** roles in **New York City** (pay floor $130k) and the **SF Bay Area** (pay floor $150k), with optional US-remote.

It pulls postings directly from ~160 company career sites (Greenhouse, Lever, Ashby, Workday, Eightfold, plus Amazon and Google), classifies them by role and level, parses the posted salary range, scores each one for fit, and renders a filterable static site.

```
fetch_jobs.py       pull → classify → score → docs/data/jobs.json
companies.json      the companies to track (edit freely; run `python3 fetch_jobs.py --validate` after)
docs/               the website (index.html, app.js, style.css, programs.js, data/jobs.js)
data/seen.json      first-seen dates so "NEW" badges survive across refreshes
.github/workflows/  daily GitHub Actions refresh + GitHub Pages deploy
refresh.sh          local refresh (+ `--serve` to open it)
launchd/            optional daily refresh on a Mac
PLAN.md             the plan and its line-by-line viability review
```

## Use it (local setup)

The folder really lives at `/Users/admin/job-radar`; `Documents/Personal Projects/job-radar` is a shortcut to it. It has to be outside Documents because macOS blocks background (launchd) jobs from reading Documents, Desktop and Downloads.

- **Open the site:** double-click `docs/index.html`. No server needed; the data is embedded as `docs/data/jobs.js`.
- **Turn on the daily refresh** (one time, from this folder):
  ```bash
  cp /Users/admin/job-radar/launchd/com.jobradar.refresh.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.jobradar.refresh.plist
  ```
  That runs `refresh.sh` every day at 7:00am while this Mac is awake. If the Mac was asleep at 7, launchd runs it when it next wakes; run `./refresh.sh` by hand any time (3–6 minutes, Workday tenants are slow). Logs: `/tmp/jobradar.log`, `/tmp/jobradar.err`.
- **Turn it off:** `launchctl unload ~/Library/LaunchAgents/com.jobradar.refresh.plist && rm ~/Library/LaunchAgents/com.jobradar.refresh.plist`.
- `./refresh.sh --serve` refreshes and serves at http://localhost:8765 if you prefer a URL.

Saved / applied / hidden marks live in whichever browser opened the file, so she should always open it in the same browser on this machine (or share the folder with her and let her open her own copy).

## Optional later: host it so she can open it from anywhere (GitHub Pages, free)

1. Create an empty **public** GitHub repository (Pages is free only on public repos; nothing personal is in this folder).
2. In this folder:
   ```bash
   git init -b main && git add -A && git commit -m "Job Radar"
   git remote add origin https://github.com/<you>/job-radar.git && git push -u origin main
   ```
3. Repo → **Settings → Pages → Source: GitHub Actions**.
4. Repo → **Actions → "Refresh job listings" → Run workflow** once. After that it runs every day at 6am ET.
5. The site is at `https://<you>.github.io/job-radar/`.

## Tuning for her

- Pay floors, "new" window, max posting age: top of `fetch_jobs.py` (`SALARY_FLOOR`, `NEW_DAYS`, `MAX_AGE_DAYS`).
- Add/remove companies: `companies.json`. Find a company's ATS by opening its careers page and looking at the URL of a posting (`boards.greenhouse.io/<token>`, `jobs.lever.co/<token>`, `jobs.ashbyhq.com/<token>`, `<tenant>.wd5.myworkdayjobs.com/<site>`).
- Title rules (what counts as PM / PMM / strategy, what's excluded, what's senior): `ROLE_PATTERNS`, `EXCLUDE_TITLE`, `SENIOR_PATTERNS`, `ENTRY_PATTERNS` in `fetch_jobs.py`.
- Saved / applied / hidden state lives in the browser (localStorage), so it's per device. "Export CSV" on the Saved tab gets it out.

## Known gaps

- Meta, Apple, Uber, LinkedIn, Microsoft, American Express, JPMorgan, Bloomberg have no reachable feed. The **Programs & manual checks** tab has pre-filtered links for them and for LinkedIn/Indeed.
- Salary ranges are base salary as posted; equity and bonus are not included. Ranges "parsed from text" come from the posting body and can occasionally pick up the wrong city's range.
- Level is inferred from the title, so a plain "Product Manager" may want 3–5 years; the "asks N+ yrs" chip is parsed from the description to help judge.
