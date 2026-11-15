# Job Radar

A daily-refreshed job board for early-career **product management, product marketing, and strategy / BizOps** roles in **New York City** (pay floor $130k) and the **SF Bay Area** (pay floor $150k), with optional US-remote.

It pulls postings directly from ~160 company career sites (Greenhouse, Lever, Ashby, Workday, Eightfold, plus Amazon and Google), classifies them by role and level, parses the posted salary range, scores each one for fit, and renders a filterable static site.

```
fetch_jobs.py       pull → classify → score → docs/data/jobs.json
companies.json      the companies to track (edit freely; run `python3 fetch_jobs.py --validate` after)
docs/               the website (index.html, app.js, style.css, programs.js, data/jobs.js)
data/seen.json      first-seen dates so "NEW" badges survive across refreshes
.github/workflows/  daily GitHub Actions refresh + GitHub Pages deploy
refresh.sh          local refresh for development (+ `--serve` to open it)
launchd/            old Mac-only daily refresh (not used now that Actions does it)
PLAN.md             the plan and its line-by-line viability review
```

## Where it lives

**Site:** https://youej.github.io/job-radar/ — open it on any device; bookmark it on her phone.

**Refresh:** a GitHub Actions workflow (`.github/workflows/refresh.yml`) runs `fetch_jobs.py` on GitHub's servers every day at 6am ET, commits the new `docs/data/jobs.json` / `jobs.js` / `data/seen.json`, and redeploys the site to GitHub Pages. Nothing on this Mac has to be running. To refresh on demand: repo → **Actions → "Refresh job listings" → Run workflow**, or `gh workflow run refresh.yml -R youej/job-radar`. Each run takes about 5–10 minutes; the time of the last refresh is shown in the site header.

Saved / applied / hidden marks live in the browser (localStorage), so they are per device and per browser. "Export CSV" on the Saved tab gets them out.

The repo is public (GitHub Pages is free only on public repos). It contains code, the company list and job postings only, nothing personal.

### Working on it locally

The folder really lives at `/Users/admin/job-radar`; `Documents/Personal Projects/job-radar` is a shortcut to it.

- Edit `fetch_jobs.py` or `companies.json`, then `git commit` and `git push`. A push that touches either file triggers a refresh and redeploy on its own.
- Changes to `docs/` (the site itself) deploy on the next refresh, or run the workflow by hand to deploy right away.
- To try the fetcher locally: `python3 fetch_jobs.py` (3–6 minutes) then open `docs/index.html`, or `./refresh.sh --serve` for a URL at http://localhost:8765. Don't commit the data files it writes unless you mean to; the workflow owns them. If a push is rejected because the bot committed data since your last pull, `git pull --rebase` first.
- The old Mac-only setup (`launchd/`, a daily local refresh) is kept for reference but is turned off; running both would make two writers for the same data files.

## How the Jobs tab is organised

The default view is built for a 0–2 year candidate. Every role is put in a tier from the years the posting asks for:

- **New-grad & rotational programs** — title says APM, rotational, new grad, etc. Shown regardless of age or pay.
- **Fits now** — entry-level titles, or roles asking 2 years or less. Shown regardless of pay; pay under her floor is just marked red, because entry roles pay less than Bain by nature and she should see the tradeoff rather than never see the role.
- **Adjacent fits** — same bar, for strategic finance, partnerships, product ops, growth and pricing titles that suit a consulting background.
- **Stretch** — asks 3 years, or doesn't state years (unless the posted minimum base is $180k+, which goes to 4+). Consulting backgrounds are routinely considered for these, and they are most of what pays $130k+. The pay floor and the "posted within" window apply here.
- **Asks 4+ years** — hidden unless "Include roles asking 4+ years" is ticked in More.

Senior titles and roles asking 5+ years never reach the page; they are dropped in `fetch_jobs.py`. Years asked are parsed from the posting text (`parse_years`), which handles "3+ years of experience", "at least 3 years", "4-6 years in product" and similar; when nothing matches the role counts as a stretch.

## Tuning for her

- Pay floors, "new" window, max posting age: top of `fetch_jobs.py` (`SALARY_FLOOR`, `NEW_DAYS`, `MAX_AGE_DAYS`).
- Add/remove companies: `companies.json`. Find a company's ATS by opening its careers page and looking at the URL of a posting (`boards.greenhouse.io/<token>`, `jobs.lever.co/<token>`, `jobs.ashbyhq.com/<token>`, `<tenant>.wd5.myworkdayjobs.com/<site>`).
- Title rules (what counts as PM / PMM / strategy, what's excluded, what's senior): `ROLE_PATTERNS`, `EXCLUDE_TITLE`, `SENIOR_PATTERNS`, `ENTRY_PATTERNS` in `fetch_jobs.py`.
- Saved / applied / hidden state lives in the browser (localStorage), so it's per device. "Export CSV" on the Saved tab gets it out.

## Known gaps

- Meta, Apple, Uber, LinkedIn, Microsoft, American Express, JPMorgan, Bloomberg have no reachable feed. The **Programs & manual checks** tab has pre-filtered links for them and for LinkedIn/Indeed.
- Salary ranges are base salary as posted; equity and bonus are not included. Ranges "parsed from text" come from the posting body and can occasionally pick up the wrong city's range.
- Level is inferred from the title, so a plain "Product Manager" may want 3–5 years; the "asks N+ yrs" chip is parsed from the description to help judge.
