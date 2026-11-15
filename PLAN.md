# Job Radar — Plan, viability review, and refinements

## 1. Who this is for

| Dimension | Her profile / preference | What the tool must do |
|---|---|---|
| Background | Vanderbilt '25, Econ + Data Science minor, 3.9. Wells Fargo PM intern. Bain Associate Consultant (Atlanta), ~1 yr experience | Treat her as **new grad / early career (0–2 yrs)**. Surface APM programs, Associate PM, PM I/II, Strategy Associate / Analyst, Product Marketing Manager |
| Role families | Product Management, Product Marketing, Strategy | Three role buckets with keyword matching on titles, plus an "adjacent" bucket (Product Ops, BizOps, Chief of Staff) that is off by default |
| Location #1 | New York City, pay should not drop far below ~$135–140k (Bain Y1 total comp) | NYC bucket; default salary floor $130k (base, as posted) |
| Location #2 | SF / Bay Area only if ~$150k+ (tech = better WLB) | Bay Area bucket; default salary floor $150k |
| Refresh | Daily or every few days | Automated daily refresh; "new since last visit" markers |

## 2. The deliverable

A **static website backed by a daily data job**. No server, no database, no paid services.

```
job-radar/
  fetch_jobs.py          # pulls, filters, scores, writes docs/data/jobs.json
  companies.json         # curated list of ~150 companies + which ATS they use
  programs.json          # curated APM / new-grad rotational programs (static)
  docs/
    index.html           # the site (single page, vanilla JS, no build step)
    app.js / style.css
    data/jobs.json       # refreshed daily
  data/seen.json         # first-seen dates so "New" badges work across runs
  .github/workflows/refresh.yml   # daily cron -> commit jobs.json -> GitHub Pages
  refresh.sh             # one-command local refresh + serve
  launchd/               # optional: run refresh.sh daily on this Mac
```

### 2a. Data sources (in order of value)

1. **Company ATS public APIs** — the same JSON endpoints company career pages use. No auth, no scraping, no ToS issues, posting text is complete (so salary ranges can be parsed).
   - Greenhouse: `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true`
   - Lever: `api.lever.co/v0/postings/{token}?mode=json`
   - Ashby: `api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true`
   - SmartRecruiters: `api.smartrecruiters.com/v1/companies/{token}/postings`
   - Workday: `{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` (POST, JSON) — covers Salesforce, Adobe, Nvidia, Intuit, PayPal, Capital One, Mastercard, Disney, etc.
2. **Big-tech public search endpoints** (best effort; may break): Amazon (`amazon.jobs/en/search.json`), Google (`careers.google.com/api/v3/search/`), Microsoft (`gcsservices.careers.microsoft.com/search/api/v1/search`).
3. **The Muse public API** (`themuse.com/api/public/jobs`, categories Product Management / Marketing / Business & Strategy, locations NYC + SF) — adds non-tech NYC employers (media, CPG, finance) that are not on the curated list.
4. **Not used**: LinkedIn and Indeed (no public API; scraping violates ToS and gets blocked). Adzuna / JSearch (need an account + API key — can be added later by her).

### 2b. Processing

- **Role classification** from title: PM / PMM / Strategy / Adjacent, with exclusions (engineering manager, product designer, content/creative strategist, intern, co-op).
- **Seniority** from title: `entry` (APM, associate, new grad, rotational, PM I, junior), `mid` (plain PM, PM II, "Manager, Product Marketing"), `senior+` (senior, staff, principal, lead, group, director, head, VP). Default view shows entry + mid.
- **Location** from the ATS location string(s): NYC, Bay Area, Remote-US, Other (dropped).
- **Salary**: structured fields when the ATS exposes them (Lever `salaryRange`, Ashby `compensation`, Greenhouse `pay_input_ranges`), otherwise regex over the description for `$130,000 – $160,000`, `$130K-$160K`, `130,000 USD`, etc. NYC (Local Law 32, 2022) and California (SB 1162, 2023) require ranges in postings, so coverage in the two target cities is high. Jobs with no range are kept and labelled "not listed" (toggleable).
- **Score** (0–100): role fit, seniority fit, location priority (NYC > SF > Remote), salary vs. floor, APM-program bonus, recency.
- **Dedupe** by (company, normalized title, location). Track `first_seen` across runs for the "New" badge.

### 2c. Website

- Filters: location, role bucket, seniority, salary floor (per city defaults), "include unlisted salary", posted-within, company/text search, source.
- Sort: best match (default), newest, highest salary.
- Per-job state in `localStorage`: ⭐ saved, ✅ applied, 🙈 hidden. Export saved/applied to CSV.
- "New since you last opened this" count and badges.
- Separate tab for **APM / new-grad programs** (curated, with typical application windows).
- Mobile friendly, light/dark.

### 2d. Refresh

- **Primary**: GitHub Actions cron (daily 11:00 UTC ≈ 6am ET) runs `fetch_jobs.py`, commits `docs/data/jobs.json`, GitHub Pages serves `docs/`. Free on a public repo; nothing personal is in the repo.
- **Fallback / local**: `./refresh.sh` runs the same script and opens the site; optional launchd plist runs it daily on this Mac.

---

## 3. Line-by-line viability review

| # | Plan line | Viable? | Risk / issue found | Refinement |
|---|---|---|---|---|
| 1 | Pull from Greenhouse / Lever / Ashby / SmartRecruiters public APIs | ✅ Yes | Board tokens guessed from memory will be wrong for some companies | Build a `--validate` mode that hits every token and reports failures; fix the list against live responses before shipping |
| 2 | Workday JSON endpoint | ⚠️ Mostly | Needs correct tenant + `wd` number + site name; some tenants rate-limit or require a session cookie | Try with a browser-like UA, retry once, skip on failure; keep Workday to ~20 high-value tenants |
| 3 | Big-tech endpoints (Amazon, Google, Microsoft) | ⚠️ Fragile | Undocumented; can change or block | Wrap in try/except, never fail the whole run; log source health in `jobs.json` so the UI can show "Google feed failed today" |
| 4 | The Muse API | ✅ Yes | Rate limit ~500/hr without a key; categories are coarse | Only 3 categories × 2 cities × a few pages ≈ 30 calls. Fine |
| 5 | Skip LinkedIn / Indeed | ✅ Correct | Coverage gap for companies not on the curated list | Mitigate with a broad curated list (~150 cos) + Muse; recommend she keep one LinkedIn alert as a complement |
| 6 | Curated company list of ~150 | ✅ Yes | List quality is the single biggest driver of result quality | Bias toward NYC/SF tech + fintech + ex-consultant-friendly companies; include finance/media firms with NYC strategy teams; make the list a plain JSON file she can edit |
| 7 | Title-keyword role classification | ✅ Yes | False positives ("Product Marketing Designer", "Strategy Consultant" at agencies) and false negatives (titles like "Business Operations Associate") | Explicit exclusion list; include common BizOps/S&O/Chief-of-Staff titles under "Strategy"; show role tag so misfires are obvious |
| 8 | Seniority from title | ✅ Yes | Many companies post plain "Product Manager" and mean 3–5 yrs | Can't fix from title alone. Parse "X+ years" from description and show it on the card as "asks for N+ yrs" so she can judge |
| 9 | Location matching | ✅ Yes | "New York" could mean the state; multi-location postings; "Remote" appended to a city | Match specific city/neighbourhood tokens; a job can belong to several buckets; treat "Remote" as its own bucket only if no target city is present |
| 10 | Salary regex | ✅ Yes | Multiple ranges per posting (per-city), hourly rates, equity mentioned as dollars | Keep all ranges; prefer the one nearest a mention of the matched city; ignore hourly (<$500) and totals >$1M; display min–max and note "base, as posted" |
| 11 | Salary floor via posted *maximum* ≥ floor | ✅ Yes | A $110k–$135k NYC range technically passes $130k but midpoint is low | Default filter uses max ≥ floor (so she doesn't miss negotiable roles) but the card shows midpoint and colours it green/amber vs. her floor |
| 12 | "New since last visit" badges | ✅ Yes | Needs state across runs | `data/seen.json` committed by the Action; `localStorage` stores last-visit timestamp |
| 13 | Scoring & default sort | ✅ Yes | Subjective weights | Expose "sort by newest" and "by salary" so scoring is never a trap; weights documented at top of `fetch_jobs.py` |
| 14 | Vanilla JS static site, no build step | ✅ Yes | None; keeps it editable by anyone | — |
| 15 | GitHub Actions daily cron + Pages | ✅ Yes | Needs a GitHub repo; `gh` CLI isn't installed here, so publishing is a manual step for the user | Ship the workflow file + a `DEPLOY.md` with the 4 commands; nothing in repo is personal (no names, no résumé) |
| 16 | launchd local refresh | ✅ Yes | Only runs when this Mac is awake; she's in Atlanta so a local-only site isn't reachable for her | Treat as a fallback; GitHub Pages is the real distribution path. Provide the plist but do not install it without asking |
| 17 | APM program tab | ⚠️ Partly | Program dates change yearly; I can't verify every current window | Label windows as "typically"; link to program pages; let the live feed catch actual postings (titles containing "APM", "Associate Product Manager", "Rotational") |
| 18 | Pay target | ✅ Yes | Her $135–140k is total comp; postings show base ranges. Equity/bonus not included | Floors set at $130k NYC / $150k SF on *base*, which is conservative in her favour. Noted in UI |
| 19 | Testing "as her" | ✅ Yes | Need a real run with real data | Run the fetcher now, open the site in the browser pane, audit the top 30 results for relevance, fix classifier misses, repeat |

### Refinements adopted from the review
- Live token validation before shipping (#1).
- Per-source health reporting in the data file and UI (#3).
- "Asks for N+ years" extraction from descriptions (#8).
- Multi-bucket locations and city-aware salary range selection (#9, #10).
- Midpoint colouring vs. floor (#11).
- Deployment as documented manual step rather than an automated push (#15); launchd provided but not installed (#16).

---

## 4. Out of scope (for now)
- LinkedIn/Indeed scraping; Adzuna/JSearch (need accounts).
- Auto-applying or résumé tailoring.
- Email / Slack digests (easy follow-up: GitHub Action can email a diff with a free SMTP action).

---

## 5. What testing as her changed (2026-11-14)

Two full runs against all 163 sources, then an audit of the default view (NYC + Bay, PM/PMM/strategy, entry + mid, pay floor on).

| Found | Fix |
|---|---|
| 60 of my 162 guessed ATS tokens were wrong (OpenAI, Notion, Plaid, Snowflake are on Ashby; Box is `boxinc`, NYT is `thenewyorktimes`, Block is `block`…) | Live `--validate` pass; every remaining token verified. The Muse (Cloudflare wall), Microsoft (bad TLS cert on their API), Uber (API removed), Intuit/Expedia/Nike (Workday auth/404) dropped and moved to the manual-check list |
| Google's JSON API is gone | Parse the public results HTML (20/page) + detail pages; works, no dates though |
| Adobe "2027 MBA University Graduate" roles ranked #1 | Exclude `MBA` titles |
| Strategic Finance / FP&A / Corporate Finance showed as "Strategy" | Reclassified to Adjacent (off by default) |
| "GTM Strategy & Operations" showed as Product Marketing | Moved to Strategy |
| Capital One "Manager, Product Manager – … Associate Servicing" tagged entry-level | Entry keywords only count in the title head; "Manager, …" is mid |
| "Senior Director, Chief of Staff" tagged mid | Senior check runs on the title minus "chief of staff" |
| Years-of-experience picked the lowest number in the posting (Google PM II said "2") | First statement wins (minimum qualifications come first); PM II now correctly reads 5 |
| Same req posted once per office showed twice (Mixpanel) | Merge on company + title + salary band, union the locations |
| "Program" badge on "Senior Associate, Product Manager" | Program detection keeps punctuation and ignores Senior Associate |
| Every top result scored 100 | Baseline lowered; scores now spread 99→60 and sort is meaningful |
| Capital One was 68 of 166 default results | UI folds each company to its top 5 with a "show N more" expander |
| 14-day window left only 2 product-marketing roles | Default window 30 days; "NEW" badges still flag the fresh ones |
| Mobile filter sheet had no way to close | Done button |

**What the data says about her search (honest read):**
- True entry-level PM/strategy postings are rare right now: ~15 of ~165 default-view roles. The bulk are "Product Manager" / "Senior Associate" / "Associate Manager, S&O" roles asking 1–4 years, which a Bain AC with a PM internship can credibly apply to.
- Product marketing is almost never hired at 0–2 years outside Google's APMM program; the mid-level PMM roles ask 5+ years. The PMM filter will stay thin.
- Capital One (NYC) and DoorDash (S&O, NYC/SF) are the deepest pipelines for her profile; Google PM I (NYC/Bay, $138–197k) and the Associate BizOps & Strategy roles are the best big-tech fits.
- NYC base ranges for these roles cluster $120–180k, so the $130k floor is not restrictive; Bay Area ranges cluster $150–250k.

### Follow-up (2026-11-15): "where are the new-grad roles?"
- The 60-day age cutoff was silently dropping new-grad reqs, which are posted in spring/late summer and stay open for months (Stripe PM New Grad Accelerator, Roblox 2027 APM, Perplexity Associate PMM, DoorDash Rotational Leadership Program). Program-flagged postings now stay for 400 days.
- Rotational / leadership-program titles are now classified (strategy, or PM if "product" is in the title) even when the org name trips an exclusion ("Dasher & Logistics").
- New filter: "Only new-grad / rotational programs". Programs tab gained a timing note, eligibility caveats (most "2027" cohorts want 2026–27 graduates; "Early Career / Associate / Accelerator" roles fit someone 1–2 years out) and campus-portal links (Handshake, Google early-career, Capital One and Amex campus sites) that no ATS feed exposes.
- Honest baseline: across all 163 sources there are ~23 entry-level PM/PMM/strategy postings in NYC + Bay at any time, versus ~320 mid and ~590 senior. Mid-November is after most APM cycles closed; the next wave is Aug–Oct 2027.

### Redesign (2026-11-15): "a lot going on at once"
Research applied: NN/g progressive disclosure (few frequent options up front, one secondary level, clearly labelled trigger), NN/g list-vs-card (lists for repetitive scannable content), Baymard list-item findings (same attributes in the same place on every row, each visually distinct).
- Her non-negotiables are now data rules, not checkboxes: senior/lead/director titles and roles asking 5+ years never reach the page (1,353 → 308 roles kept).
- Primary controls reduced to search, location (NYC + Bay / New York / Bay Area), role (All / Product / Product marketing / Strategy) and sort. Twelve secondary options live behind one "More" button that shows a count when any is changed.
- Rows instead of cards, no sidebar, one 920px column. Every row: title · company · location · posted, one muted meta line (role · level · years asked), salary on the right coloured against her floor. Source and match-score chips removed.
- Results grouped: New-grad & rotational programs · This week · Earlier. Per-company fold kept.
- Row actions appear on hover (always on touch). Sources moved from a tab to a footer link.
