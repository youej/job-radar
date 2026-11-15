#!/usr/bin/env python3
"""
Job Radar fetcher.

Pulls postings straight from company ATS APIs (Greenhouse, Lever, Ashby,
SmartRecruiters, Workday), a few big-tech public search endpoints, and The Muse,
then classifies, filters, scores and writes docs/data/jobs.json.

Usage:
  python3 fetch_jobs.py              # full run
  python3 fetch_jobs.py --validate   # just check every company token responds
  python3 fetch_jobs.py --only stripe,figma   # debug a few companies
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import html
import json
import re
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
DATA_OUT = DOCS / "data" / "jobs.json"
SEEN_PATH = ROOT / "data" / "seen.json"
COMPANIES_PATH = ROOT / "companies.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 JobRadar/1.0")
TIMEOUT = 25
TODAY = dt.date.today()

# ----------------------------------------------------------------------------
# Her preferences (edit here)
# ----------------------------------------------------------------------------
SALARY_FLOOR = {"nyc": 130_000, "bay": 150_000, "remote": 130_000}
NEW_DAYS = 3            # "New" badge window
MAX_AGE_DAYS = 60       # drop postings older than this when a date is known
PROGRAM_MAX_AGE_DAYS = 400  # new-grad / rotational reqs are posted early and stay open for months

# ----------------------------------------------------------------------------
# Classification rules
# ----------------------------------------------------------------------------
ROLE_PATTERNS = {
    "pm": [
        r"\bproduct manag", r"\bapm\b", r"associate product", r"\bproduct lead\b",
        r"\bproduct owner\b", r"technical product", r"\bproduct, ", r"\bproduct director\b",
        r"\bproduct associate\b",
        r"\bproduct strateg", r"\bhead of product\b", r"\bproduct management\b",
        r"\bproduct & ", r"\bgrowth product\b", r"\bproduct (?:ii?|1|2)\b",
    ],
    "pmm": [r"product marketing", r"\bpmm\b", r"solutions? marketing"],
    "strategy": [
        r"\bstrateg", r"business operations", r"\bbiz ?ops\b", r"chief of staff",
        r"corporate development", r"\bcorp dev\b", r"business planning",
        r"\bs&o\b", r"strategy & operations", r"strategy and operations",
        r"\bbusiness strategy\b", r"\bstrategic (?:finance|initiatives|planning|projects|partnerships)\b",
        r"\bbusiness analyst\b",
        r"\bcommercial strategy\b", r"\bgrowth strategy\b", r"\bmarket expansion\b",
        r"rotational (?:\w+ ){0,3}program", r"leadership development program", r"\bgraduate program\b",
        r"\bnew grad accelerator\b", r"\bassociate program\b", r"\banalyst program\b",
        r"go[- ]to[- ]market manag", r"\bgtm manag", r"\bgtm strateg", r"\bgo-to-market strateg",
        r"\bgtm (?:strategy|operations|planning)\b", r"\bbusiness operations\b",
    ],
    "adjacent": [
        r"product operations", r"\bproduct ops\b", r"\bgrowth manager\b", r"\bgrowth lead\b",
        r"\bgrowth associate\b", r"\bprogram manager\b", r"\bbusiness development\b",
        r"\bgeneral manager\b", r"\bgm\b", r"\brevenue operations\b", r"\brev ?ops\b",
        r"\bpartnerships\b", r"\bcustomer insights\b", r"\bmarket research\b",
        r"\bbrand manager\b", r"\bmarketing manager\b", r"\bgrowth marketing\b",
        r"\bproduct analyst\b", r"strategic financ", r"finance (?:&|and) strategy", r"\bfp&a\b",
        r"corporate finance", r"investor relations", r"\bfinancial analyst\b", r"\bstrategic financial\b",
        r"\bpartner development\b", r"\bpricing\b",
    ],
}
EXCLUDE_TITLE = [
    r"\bintern(ship)?\b", r"\bco-?op\b", r"\bengineer", r"\bengineering\b", r"\bdesigner\b", r"\bdesign\b",
    r"content strateg", r"creative strateg", r"media strateg", r"\bseo\b", r"\bsem\b", r"\bpaid (media|search|social)\b",
    r"\brecruit", r"\btalent\b", r"\bcounsel\b", r"attorney", r"\blegal\b", r"\bnurse\b", r"physician",
    r"\bux\b", r"\b(user|ux) research", r"data scien", r"\barchitect\b", r"\bphd\b",
    r"security", r"\btax\b", r"\baccount(ant|ing)\b", r"actuar", r"procurement", r"\bclinical\b",
    r"\bsales (development|engineer|executive|rep)", r"\baccount (executive|manager)\b",
    r"\bcustomer success\b", r"\bsupport\b", r"\bwriter\b", r"\bcopy", r"\beditor\b",
    r"\bvideo\b", r"\bsocial media\b", r"\binfluencer\b", r"\bcommunity\b", r"\bevents?\b",
    r"\bpublic relations\b", r"\bcommunications\b", r"\bpeople (ops|operations|strategy)\b",
    r"\bhr\b", r"\bhuman resources\b", r"\bworkplace\b", r"\bfacilities\b", r"\breal estate\b",
    r"\btechnical program\b", r"\bsoftware\b", r"\bdeveloper\b", r"\bdevops\b", r"\bsre\b",
    r"\bscientist\b", r"\bmachine learning\b", r"\bML\b", r"\bresearch(er)?\b",
    r"\binvestment\b", r"\bportfolio manager\b", r"\btrader\b", r"\btrading\b", r"\bquant",
    r"\bcompliance\b", r"\brisk\b", r"\baudit", r"\bcontroller\b", r"\btreasury\b", r"\bpayroll\b",
    r"\bfield\b", r"\bstore\b", r"\bretail\b", r"\bwarehouse\b", r"\bdriver\b",
    r"\bsupply chain\b", r"\blogistics\b", r"\bmanufactur", r"\bhardware\b", r"\bmechanical\b",
    r"\bimplementation\b", r"\bsolutions? (engineer|architect|consultant)\b", r"\bsolutions? consult",
    r"\btechnical account\b", r"\bprofessional services\b", r"\bcustomer (engineer|solutions)\b",
    r"\bmba\b", r"\bfraud\b", r"\bsourcing\b", r"\bdata analyst\b", r"\bforward deployed\b",
    r"\bdeployment strateg", r"\btrainer\b", r"\bconnectivity\b", r"\bdata center\b", r"\bportfolio\b",
    r"\bcapital formation\b", r"\bproduct specialist\b", r"\bcomms\b", r"\bpackaging\b", r"\bconsultant\b",
    r"\btechnical business analyst\b", r"\bcredit risk\b", r"\bunderwriting\b", r"\bcollections strateg",
    r"\bcontractor\b", r"\btemporary\b", r"\bfixed[- ]term\b", r"\bpart[- ]time\b",
    r"\bcoordinator\b", r"\bspecialist\b", r"\brepresentative\b", r"\bassociate program manager\b",
    r"\bworkforce\b", r"\bregulatory\b", r"\binbound\b", r"\boutbound\b", r"\bpayment operations\b",
]
# marketing roles that are not product marketing
NON_PMM_MARKETING = r"\b(integrated|lifecycle|brand|growth|performance|field|content|digital|email|consumer|b2b|partner|events?|influencer|social) marketing\b"
# "manager" in these means people-manager / senior
SENIOR_PATTERNS = [
    r"\bsenior\b", r"\bsr\.?\b", r"\bstaff\b", r"\bprincipal\b", r"\blead\b", r"\bdirector\b",
    r"\bhead\b", r"\bvp\b", r"\bvice president\b", r"\bchief\b", r"\bgroup product\b", r"\bexecutive\b",
    r"\bdistinguished\b", r"\bfellow\b", r"\bmanager, product management\b", r"\bmanager of product\b",
    r"\b(iii|iv|v|3|4|5)\b", r"\bexperienced\b", r"\bexpert\b", r"\bpartner\b", r"\bgm\b",
]
ENTRY_PATTERNS = [
    r"\bassociate\b", r"\bapm\b", r"\bnew grad", r"\bearly career\b", r"\brotational\b",
    r"\buniversity\b", r"\bgraduate\b", r"\bjunior\b", r"\bjr\.?\b", r"\bentry\b", r"\banalyst\b",
    r"\b(i|1)\b", r"\bemerging talent\b", r"\bcampus\b", r"\bclass of 20\d\d\b", r"\b20\d\d (?:grads?|start)\b",
]
PROGRAM_PATTERNS = [
    r"\bapm\b", r"associate product manager", r"associate product marketing", r"\brotational\b", r"\bnew grad", r"\buniversity grad",
    r"\bearly career\b", r"\bclass of 20\d\d\b", r"\brpm\b", r"\bleadership development program\b",
    r"\bldp\b", r"\bgraduate program\b", r"\bfellowship\b",
]

NYC_PATTERNS = [r"new york", r"\bnyc\b", r"brooklyn", r"manhattan", r"\bny\b", r"\bn\.y\.\b", r"\bnew york city\b"]
BAY_PATTERNS = [
    r"san francisco", r"\bsf\b", r"bay area", r"palo alto", r"menlo park", r"mountain view", r"sunnyvale",
    r"san jose", r"santa clara", r"redwood city", r"san mateo", r"\boakland\b", r"\bberkeley\b", r"cupertino",
    r"foster city", r"south san francisco", r"burlingame", r"\bfremont\b", r"los altos", r"san bruno",
    r"emeryville", r"san carlos", r"milpitas", r"\bsf bay\b", r"\bsouth bay\b", r"\bsilicon valley\b",
    r"\bsan ramon\b", r"\bpleasanton\b", r"\bwalnut creek\b", r"\bsausalito\b", r"\bmill valley\b",
]
REMOTE_PATTERNS = [r"\bremote\b", r"\banywhere\b", r"\bdistributed\b", r"\bwork from home\b", r"\bwfh\b",
                   r"^united states$", r"^usa?$", r"^us$", r"^u\.s\.$", r"^united states of america$"]
NON_US_PATTERNS = [
    r"canada", r"\bemea\b", r"europe", r"\buk\b", r"united kingdom", r"london", r"india", r"\bapac\b", r"latam",
    r"germany", r"berlin", r"france", r"paris", r"mexico", r"brazil", r"australia", r"singapore", r"japan",
    r"ireland", r"dublin", r"poland", r"netherlands", r"amsterdam", r"spain", r"israel", r"tel aviv",
    r"toronto", r"vancouver", r"bangalore", r"bengaluru", r"hyderabad", r"sydney", r"tokyo", r"portugal",
    r"lisbon", r"sweden", r"stockholm", r"switzerland", r"zurich", r"philippines", r"colombia", r"argentina",
    r"chile", r"nigeria", r"kenya", r"south africa", r"uae", r"dubai", r"korea", r"seoul", r"china", r"shanghai",
    r"hong kong", r"taiwan", r"italy", r"milan", r"austria", r"belgium", r"denmark", r"finland", r"norway",
    r"czech", r"prague", r"romania", r"hungary", r"turkey", r"egypt", r"indonesia", r"vietnam", r"thailand",
    r"malaysia", r"new zealand", r"\bapj\b", r"\blatin america\b",
]

MONEY = r"(?:USD\s?)?\$\s?(\d{2,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}(?:\.\d{1,2})?\s?[kK]\b|\d{5,6}(?:\.\d+)?)"
RANGE_RE = re.compile(MONEY + r"\s*(?:-|–|—|to|and|through)\s*" + MONEY, re.I)
RANGE_NO_DOLLAR_RE = re.compile(
    r"(\d{3},\d{3})\s*(?:-|–|—|to)\s*(\d{3},\d{3})\s*(?:USD|per year|annually|/\s?year|/\s?yr|a year)", re.I)
YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(\d{1,2})?\s*\+?\s*(?:years|yrs)[^.]{0,60}?experience|"
                      r"experience[^.]{0,40}?(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(\d{1,2})?\s*\+?\s*(?:years|yrs)", re.I)
# Broader form: "8+ years in product management", "at least 3 years of consulting", "4-6 years building ...".
# Requires a plus, a range or a qualifier word so company-history lines ("25 years", "2 year anniversary") don't match.
_Y_NUM = r"(?:(?:at least|minimum(?: of)?|min\.?|over|more than)\s*(\d{1,2})\s*\+?|(\d{1,2})\s*(?:\+|\s*(?:-|–|to)\s*(\d{1,2})\s*\+?))"
_Y_CTX = (r"(?:experience|exp\b|background|track record|working|professional|relevant|as an? |building|leading|managing|"
          r"driving|shipping|launching|owning|in (?:a |an )?(?:product|strategy|consulting|marketing|business|operations|bizops|"
          r"finance|tech|software|b2b|saas|growth|analytics|data|fintech|startup|high[- ]growth|management|a problem|similar|related)|"
          r"of (?:product|strategy|consulting|marketing|business|operations|relevant|professional|progressive|hands|full|total|work|industry))")
YEARS_RE2 = re.compile(rf"{_Y_NUM}\s*(?:years?|yrs)(?:\s+or more)?[^.\n•;]{{0,80}}?{_Y_CTX}|{_Y_CTX}[^.\n•;]{{0,40}}?{_Y_NUM}\s*(?:years?|yrs)", re.I)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def rx_any(patterns, text):
    return any(re.search(p, text, re.I) for p in patterns)


def strip_html(s: str) -> str:
    if not s:
        return ""
    s = html.unescape(s)
    s = html.unescape(s)  # Greenhouse double-encodes
    s = re.sub(r"<(br|/p|/li|/div|/h\d)\s*/?>", "\n", s, flags=re.I)
    s = TAG_RE.sub(" ", s)
    s = s.replace("\xa0", " ")
    return WS_RE.sub(" ", s).strip()


def norm_title(t: str) -> str:
    t = re.sub(r"[()\[\]]", " ", t or "")
    t = re.sub(r"[^a-z0-9& ]+", " ", t.lower())
    return WS_RE.sub(" ", t).strip()


def classify_role(title: str):
    t = " " + norm_title(title) + " "
    if re.search(r"\bassistant\b|\bintern(ship)?\b|\bco-?op\b", t):
        return None
    # rotational / leadership programs are generalist tracks: keep them even if the org name trips an exclusion
    if re.search(r"rotational (?:\w+ ){0,3}program|leadership development program|new grad accelerator", t):
        return "pm" if re.search(r"\bproduct\b", t) else "strategy"
    if rx_any(EXCLUDE_TITLE, t):
        # allow a few whitelisted exceptions
        if not re.search(r"product (manager|marketing)|chief of staff|strategy", t, re.I):
            return None
        # excluded word present alongside a core term: still exclude hard ones
        if re.search(r"intern|co-?op|engineer|designer|\bdesign\b|recruit|counsel|attorney|data scien|security|"
                     r"\bux\b|research|technical program|software|hardware|\bML\b|"
                     r"machine learning|content strateg|creative strateg|media strateg|\bmba\b|\bfraud\b|"
                     r"consultant|sourcing|trainer|forward deployed|deployment strateg|data analyst|portfolio|"
                     r"packaging|contractor|temporary|fixed[- ]term|part[- ]time|credit risk|underwriting|"
                     r"\bcomms\b|workforce|regulatory|inbound|outbound|payment operations|\bpayroll\b|coordinator|representative", t, re.I):
            return None
    if re.search(NON_PMM_MARKETING, t) and not re.search(r"product marketing", t):
        return "adjacent"
    if re.search(r"\bprogram manager\b|\bpartnerships?\b|\bpartner development\b|strategic financ|finance (?:&|and) strategy|\bfp&a\b|corporate finance|\bproduct analyst\b", t):
        return "adjacent"
    for role in ("pm", "pmm", "strategy", "adjacent"):
        if rx_any(ROLE_PATTERNS[role], t):
            # a "Product Marketing" title would also hit "product" patterns - pmm wins
            if role == "pm" and re.search(r"product marketing", t):
                return "pmm"
            return role
    return None


def classify_seniority(title: str) -> str:
    t = " " + norm_title(title) + " "
    t_no_cos = t.replace("chief of staff", " ")
    if re.search(r"senior associate|sr associate|associate manager", t):
        return "mid" if re.search(r"senior associate|sr associate", t) else "entry"
    if rx_any(SENIOR_PATTERNS, t_no_cos):
        return "senior"
    # Only the title "head" (before the team/suffix) decides entry level, so
    # "Manager, Product Manager - Small Business Associate Servicing" is not entry.
    head = re.split(r"\s[-–—|:(]\s?|\s-\s|\(", title, maxsplit=1)[0]
    head = " " + norm_title(head) + " "
    if re.match(r"\s*(manager|business manager)\b", head):
        return "mid"
    if rx_any(ENTRY_PATTERNS, head) or is_program(title):
        return "entry"
    return "mid"


def is_program(title: str) -> bool:
    # keep punctuation: "Senior Associate, Product Manager" is not an "Associate Product Manager" program
    t = " " + re.sub(r"\s+", " ", (title or "").lower()) + " "
    if re.search(r"senior associate|sr\.? associate", t):
        return False
    return rx_any(PROGRAM_PATTERNS, t)


def classify_locations(locs: list[str], remote_flag: bool = False):
    buckets = set()
    matched = {}
    for raw in locs:
        l = (raw or "").strip().lower()
        if not l:
            continue
        if rx_any(NYC_PATTERNS, l) and not re.search(r"rochester|buffalo|albany|syracuse|ithaca", l):
            buckets.add("nyc"); matched.setdefault("nyc", raw)
        if rx_any(BAY_PATTERNS, l):
            buckets.add("bay"); matched.setdefault("bay", raw)
        if rx_any(REMOTE_PATTERNS, l) and not rx_any(NON_US_PATTERNS, l):
            buckets.add("remote"); matched.setdefault("remote", raw)
    if remote_flag and not rx_any(NON_US_PATTERNS, " ".join(locs).lower()):
        buckets.add("remote"); matched.setdefault("remote", "Remote")
    return sorted(buckets), matched


def money_to_int(s: str):
    s = s.strip().replace(",", "").replace("$", "").replace("USD", "").strip()
    mult = 1
    if s.lower().endswith("k"):
        s = s[:-1].strip(); mult = 1000
    try:
        v = float(s) * mult
    except ValueError:
        return None
    return int(v)


def parse_salary_ranges(text: str):
    """Return list of (min, max, context_before) from free text."""
    out = []
    for m in RANGE_RE.finditer(text):
        a, b = money_to_int(m.group(1)), money_to_int(m.group(2))
        if a and b and 40_000 <= a <= 900_000 and 40_000 <= b <= 1_200_000 and b >= a:
            out.append((a, b, text[max(0, m.start() - 220):m.start()].lower()))
    for m in RANGE_NO_DOLLAR_RE.finditer(text):
        a, b = money_to_int(m.group(1)), money_to_int(m.group(2))
        if a and b and 40_000 <= a <= 900_000 and b >= a:
            out.append((a, b, text[max(0, m.start() - 220):m.start()].lower()))
    return out


def choose_range(ranges, buckets):
    """Prefer a range whose preceding context mentions the matched city."""
    if not ranges:
        return None, []
    allr = [(a, b) for a, b, _ in ranges]
    pref_patterns = []
    if "nyc" in buckets:
        pref_patterns += NYC_PATTERNS
    if "bay" in buckets:
        pref_patterns += BAY_PATTERNS
    if pref_patterns:
        for a, b, ctx in ranges:
            if rx_any(pref_patterns, ctx):
                return (a, b), allr
    # otherwise the widest/highest range (companies list the top-tier market first or last)
    best = max(ranges, key=lambda r: r[1])
    return (best[0], best[1]), allr


def _first_years(rx, text):
    for m in rx.finditer(text):
        for g in m.groups():
            if not g:
                continue
            try:
                n = int(g)
            except ValueError:
                continue
            if 0 < n <= 15:
                return m.start(), n
    return None


def parse_years(text: str):
    """Minimum years asked, from the earliest experience statement (minimum quals come first)."""
    hits = [h for h in (_first_years(YEARS_RE, text), _first_years(YEARS_RE2, text)) if h]
    return min(hits)[1] if hits else None


def to_date(v):
    if not v:
        return None
    if isinstance(v, (int, float)):
        if v > 1e12:
            v = v / 1000
        return dt.datetime.utcfromtimestamp(v).date().isoformat()
    s = str(v)
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    m = re.match(r"posted\s+(\d+)\+?\s+days? ago", s, re.I)
    if m:
        return (TODAY - dt.timedelta(days=int(m.group(1)))).isoformat()
    if re.match(r"posted (today|yesterday)", s, re.I):
        return (TODAY - dt.timedelta(days=1 if "yesterday" in s.lower() else 0)).isoformat()
    m = re.match(r"posted\s+(\d+)\+?\s+hours? ago", s, re.I)
    if m:
        return TODAY.isoformat()
    for fmt in ("%m/%d/%Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s[:20].strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})


RETRY_STATUSES = {403, 429, 500, 502, 503, 504}


def _request(method, url, **kw):
    """GET/POST with backoff. Raises (never returns None) so callers see the real HTTP status."""
    last = None
    for attempt in range(4):
        try:
            r = SESSION.request(method, url, timeout=TIMEOUT, **kw)
            if r.status_code in RETRY_STATUSES:
                last = f"HTTP {r.status_code}"
                time.sleep(3 * (2 ** attempt))  # 3, 6, 12, 24s
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = f"{type(e).__name__}: {e}"[:160]
            if attempt == 3:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{last} after retries: {url[:120]}")


def get_json(url, **kw):
    return _request("GET", url, **kw)


def post_json(url, body, **kw):
    return _request("POST", url, json=body, **kw)


# ----------------------------------------------------------------------------
# Raw job record produced by every fetcher
# ----------------------------------------------------------------------------
def raw(company, title, url, locations, description="", posted=None, salary=None, remote=False,
        source="", extra=None):
    return {
        "company": company, "title": (title or "").strip(), "url": url,
        "locations": [l for l in (locations or []) if l], "description": description or "",
        "posted": posted, "salary": salary, "remote": remote, "source": source, "extra": extra or {},
    }


# ----------------------------------------------------------------------------
# ATS fetchers. Each returns a list of raw records for one company.
# ----------------------------------------------------------------------------
def fetch_greenhouse(c):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{c['token']}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        locs = []
        if j.get("location", {}).get("name"):
            locs.append(j["location"]["name"])
        for o in j.get("offices", []) or []:
            if o.get("name"):
                locs.append(o["name"])
        sal = None
        for pr in j.get("pay_input_ranges") or []:
            if pr.get("currency_type", "USD") == "USD" and pr.get("min_cents") and pr.get("max_cents"):
                a, b = pr["min_cents"] // 100, pr["max_cents"] // 100
                if a >= 40_000:
                    sal = (a, b) if not sal else (min(sal[0], a), max(sal[1], b))
        out.append(raw(c["name"], j.get("title"), j.get("absolute_url"), locs,
                       strip_html(j.get("content", "")), to_date(j.get("first_published") or j.get("updated_at")),
                       sal, source="greenhouse"))
    return out


def fetch_lever(c):
    data = get_json(f"https://api.lever.co/v0/postings/{c['token']}?mode=json")
    out = []
    for j in data:
        cats = j.get("categories", {}) or {}
        locs = [cats.get("location")] + (j.get("allLocations") or [])
        remote = (j.get("workplaceType") == "remote")
        sal = None
        sr = j.get("salaryRange") or {}
        if sr.get("min") and sr.get("max") and sr.get("currency", "USD") == "USD" and sr.get("interval", "per-year-salary").startswith("per-year"):
            sal = (int(sr["min"]), int(sr["max"]))
        desc = strip_html(j.get("descriptionPlain") or j.get("description") or "") + " " + \
            " ".join(strip_html(l.get("content", "")) for l in j.get("lists", []) or []) + " " + \
            strip_html(j.get("additionalPlain") or j.get("additional") or "")
        out.append(raw(c["name"], j.get("text"), j.get("hostedUrl"), locs, desc, to_date(j.get("createdAt")),
                       sal, remote, source="lever"))
    return out


def fetch_ashby(c):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{c['token']}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location")] + [s.get("location") for s in (j.get("secondaryLocations") or [])]
        addr = (j.get("address") or {}).get("postalAddress") or {}
        if addr.get("addressLocality"):
            locs.append(f"{addr.get('addressLocality')}, {addr.get('addressRegion', '')}")
        sal = None
        comp = j.get("compensation") or {}
        for comp_c in comp.get("summaryComponents") or []:
            if comp_c.get("compensationType") == "Salary" and comp_c.get("currencyCode", "USD") == "USD":
                a, b = comp_c.get("minValue"), comp_c.get("maxValue")
                if a and b and a >= 40_000:
                    sal = (int(a), int(b))
        desc = strip_html(j.get("descriptionHtml") or j.get("descriptionPlain") or "")
        if not sal and comp.get("compensationTierSummary"):
            desc = comp["compensationTierSummary"] + " " + desc
        out.append(raw(c["name"], j.get("title"), j.get("jobUrl") or j.get("applyUrl"), locs, desc,
                       to_date(j.get("publishedAt")), sal, bool(j.get("isRemote")), source="ashby"))
    return out


def fetch_smartrecruiters(c):
    out = []
    offset = 0
    postings = []
    while True:
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{c['token']}/postings?limit=100&offset={offset}")
        content = data.get("content", [])
        postings += content
        offset += 100
        if offset >= data.get("totalFound", 0) or not content:
            break
    # only fetch details for title/location matches (details are 1 call each)
    for p in postings:
        title = p.get("name", "")
        loc = p.get("location", {}) or {}
        locs = [", ".join(x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x)]
        if loc.get("remote"):
            locs.append("Remote")
        if classify_role(title) is None:
            continue
        buckets, _ = classify_locations(locs, bool(loc.get("remote")))
        if not buckets:
            continue
        desc = ""
        try:
            d = get_json(f"https://api.smartrecruiters.com/v1/companies/{c['token']}/postings/{p['id']}")
            sections = (d.get("jobAd") or {}).get("sections") or {}
            desc = " ".join(strip_html(s.get("text", "")) for s in sections.values() if isinstance(s, dict))
        except Exception:
            pass
        url = f"https://jobs.smartrecruiters.com/{c['token']}/{p['id']}"
        out.append(raw(c["name"], title, url, locs, desc, to_date(p.get("releasedDate")), None,
                       bool(loc.get("remote")), source="smartrecruiters"))
    return out


WORKDAY_SEM = threading.Semaphore(3)   # Workday throttles bursts from one IP (seen as 429s on GitHub runners)


def _wd(fn, *a, **kw):
    with WORKDAY_SEM:
        time.sleep(0.4)
        return fn(*a, **kw)


def fetch_workday(c):
    base = f"https://{c['tenant']}.{c['wd']}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{c['tenant']}/{c['site']}/jobs"
    headers = {"Content-Type": "application/json", "Accept": "application/json",
               "Accept-Language": "en-US,en;q=0.9", "Referer": f"{base}/{c['site']}", "Origin": base}
    # warm cookies
    try:
        SESSION.get(f"{base}/{c['site']}", timeout=TIMEOUT)
    except Exception:
        pass
    seen = {}
    for q in c.get("queries", ["product manager", "product marketing", "strategy"]):
        offset = 0
        while offset < 400:
            body = {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": q}
            data = _wd(post_json, api, body, headers=headers)
            posts = data.get("jobPostings", [])
            for p in posts:
                if p.get("externalPath"):
                    seen[p["externalPath"]] = p
            total = data.get("total", 0)
            offset += 20
            if offset >= total or not posts:
                break
    out = []
    for path, p in seen.items():
        title = p.get("title", "")
        if classify_role(title) is None:
            continue
        loctext = p.get("locationsText", "") or ""
        locs = [loctext]
        need_detail = True
        buckets, _ = classify_locations(locs)
        if not buckets and not re.search(r"\d+ locations|remote", loctext, re.I):
            continue
        desc, posted, sal = "", to_date(p.get("postedOn")), None
        if need_detail:
            try:
                d = _wd(get_json, f"{base}/wday/cxs/{c['tenant']}/{c['site']}{path}", headers=headers)
                info = d.get("jobPostingInfo", {}) or {}
                desc = strip_html(info.get("jobDescription", ""))
                locs = [info.get("location", "")] + (info.get("additionalLocations") or [])
                if info.get("remoteType"):
                    locs.append(str(info["remoteType"]))
                posted = to_date(info.get("startDate")) or posted
            except Exception:
                pass
        out.append(raw(c["name"], title, f"{base}/{c['site']}{path}", locs, desc, posted, sal, source="workday"))
    return out


def fetch_amazon(c):
    out = []
    for q in ["product manager", "product marketing", "strategy"]:
        for loc in ["New York, NY", "San Francisco, CA", "Sunnyvale, CA", "Palo Alto, CA"]:
            offset = 0
            while offset < 300:
                url = ("https://www.amazon.jobs/en/search.json?result_limit=100&sort=recent"
                       f"&base_query={requests.utils.quote(q)}&loc_query={requests.utils.quote(loc)}&offset={offset}")
                data = get_json(url)
                jobs = data.get("jobs", [])
                for j in jobs:
                    desc = " ".join(strip_html(j.get(k, "")) for k in ("description", "basic_qualifications", "preferred_qualifications"))
                    out.append(raw("Amazon", j.get("title"), "https://www.amazon.jobs" + j.get("job_path", ""),
                                   [j.get("location") or j.get("normalized_location") or ""], desc,
                                   to_date(j.get("posted_date")), None, source="amazon"))
                offset += 100
                if len(jobs) < 100:
                    break
    return out


GOOGLE_CARD_RE = re.compile(
    r'<h3[^>]*>(?P<title>[^<]+)</h3>.*?<p class="l103df">(?P<company>[^<|]+)\|\s*<span class="pwO9Dc">(?P<locs>.*?)</span></p>'
    r'(?:<div class="Xsxa1e"><h4>Minimum qualifications</h4>(?P<quals>.*?)</div>)?.*?href="jobs/results/(?P<id>\d+)-(?P<slug>[a-z0-9-]+)',
    re.S)


def fetch_google(c):
    """Google has no public JSON API any more; parse the public results pages (20 per page)."""
    base = "https://www.google.com/about/careers/applications/jobs/results"
    seen = {}
    for q in ['"product manager"', '"product marketing"', 'strategy', '"associate product manager"', '"business operations"']:
        for loc in ["New York, NY, USA", "San Francisco, CA, USA", "Mountain View, CA, USA", "Sunnyvale, CA, USA"]:
            for page in range(1, 4):
                url = f"{base}?q={requests.utils.quote(q)}&location={requests.utils.quote(loc)}&page={page}"
                r = SESSION.get(url, timeout=TIMEOUT)
                if not r.ok:
                    break
                cards = list(GOOGLE_CARD_RE.finditer(r.text))
                for m in cards:
                    jid = m.group("id")
                    if jid in seen:
                        continue
                    locs = [strip_html(x) for x in re.findall(r"<span class=\"r0wTof[^\"]*\">([^<]+)</span>", m.group("locs"))]
                    seen[jid] = {
                        "title": html.unescape(m.group("title")).strip(),
                        "company": html.unescape(m.group("company")).strip() or "Google",
                        "locs": [l.strip("; ").strip() for l in locs],
                        "quals": strip_html(m.group("quals") or ""),
                        "url": f"{base}/{jid}-{m.group('slug')}",
                    }
                if len(cards) < 20:
                    break
                time.sleep(0.4)
    out = []
    for jid, j in seen.items():
        if classify_role(j["title"]) is None:
            continue
        buckets, _ = classify_locations(j["locs"])
        if not buckets:
            continue
        desc = j["quals"]
        # detail page carries the full description incl. the US base salary range
        try:
            r = SESSION.get(j["url"], timeout=TIMEOUT)
            if r.ok:
                i = r.text.find("Minimum qualifications")
                chunk = r.text[max(0, i - 200): i + 20000] if i > 0 else r.text[:40000]
                desc = strip_html(chunk)
            time.sleep(0.3)
        except Exception:
            pass
        out.append(raw(j["company"], j["title"], j["url"], j["locs"], desc, None, None, source="google"))
    return out


def fetch_eightfold(c):
    """Eightfold-hosted career sites (Netflix). List endpoint + per-job detail for descriptions."""
    host, domain = c["host"], c["domain"]
    seen = {}
    for q in c.get("queries", ["product manager", "product marketing", "strategy", "business operations"]):
        start = 0
        while start < 200:
            url = f"https://{host}/api/apply/v2/jobs?domain={domain}&query={requests.utils.quote(q)}&start={start}&num=50"
            data = get_json(url)
            pos = data.get("positions", [])
            for p in pos:
                seen[p["id"]] = p
            start += 50
            if len(pos) < 50 or start >= data.get("count", 0):
                break
    out = []
    for pid, p in seen.items():
        title = p.get("name", "")
        if classify_role(title) is None:
            continue
        locs = list(p.get("locations") or []) + [p.get("location", "")]
        locs = [l.replace(",", ", ") for l in locs if l]
        remote = (p.get("work_location_option") or "").lower().startswith("remote")
        buckets, _ = classify_locations(locs, remote)
        if not buckets:
            continue
        desc = ""
        try:
            d = get_json(f"https://{host}/api/apply/v2/jobs/{pid}?domain={domain}")
            desc = strip_html(d.get("job_description", ""))
        except Exception:
            pass
        out.append(raw(c["name"], title, p.get("canonicalPositionUrl"), locs, desc,
                       to_date(int(p["t_create"])) if p.get("t_create") else None, None, remote, source="eightfold"))
    return out


FETCHERS = {
    "greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters, "workday": fetch_workday,
    "amazon": fetch_amazon, "google": fetch_google, "eightfold": fetch_eightfold,
}


# ----------------------------------------------------------------------------
# Normalize + score
# ----------------------------------------------------------------------------
def job_id(company, title, loc):
    return hashlib.sha1(f"{company.lower()}|{norm_title(title)}|{(loc or '').lower()[:40]}".encode()).hexdigest()[:12]


def score(job):
    s = 15
    s += {"pm": 20, "pmm": 18, "strategy": 18, "adjacent": 6}.get(job["role"], 0)
    s += {"entry": 20, "mid": 12, "senior": -8}.get(job["seniority"], 0)
    b = job["buckets"]
    s += 15 if "nyc" in b else (10 if "bay" in b else 4)
    floor = min(SALARY_FLOOR[x] for x in b) if b else 130_000
    sal = job["salary"]
    if sal["max"]:
        if sal["max"] >= floor:
            s += 8
            mid = (sal["min"] + sal["max"]) / 2
            if mid >= floor:
                s += 6
        else:
            s -= 18
    if job["program"]:
        s += 10
    y = job["years_min"]
    if y is not None:
        if y <= 2:
            s += 5
        elif y >= 5:
            s -= 12
        elif y >= 3:
            s -= 3
    if job["posted"]:
        try:
            age = (TODAY - dt.date.fromisoformat(job["posted"])).days
            if age <= 7:
                s += 5
            elif age > 45:
                s -= 5
        except ValueError:
            pass
    return max(0, min(100, s))


def normalize(r, company_meta):
    title = r["title"]
    role = classify_role(title)
    if role is None:
        return None
    buckets, matched = classify_locations(r["locations"], r.get("remote", False))
    if not buckets:
        return None
    desc = r["description"] or ""
    sal_src = "none"
    if r.get("salary"):
        a, b = r["salary"]; ranges_all = [(a, b)]; sal_src = "structured"
    else:
        ranges = parse_salary_ranges(desc)
        chosen, ranges_all = choose_range(ranges, buckets)
        if chosen:
            a, b = chosen; sal_src = "parsed"
        else:
            a, b = None, None
    posted = r.get("posted")
    seniority = classify_seniority(title)
    if seniority == "senior":
        return None  # her brief: no senior / lead / director roles, ever
    program = is_program(title)
    years_min = parse_years(desc)
    if years_min is not None and years_min >= 5 and not program:
        return None  # roles asking 5+ years are out of scope
    if posted:
        try:
            if (TODAY - dt.date.fromisoformat(posted)).days > (PROGRAM_MAX_AGE_DAYS if program else MAX_AGE_DAYS):
                return None
        except ValueError:
            posted = None
    levels = (r.get("extra") or {}).get("levels") or []
    if levels and seniority == "mid":
        if any("entry" in l.lower() or "internship" == l.lower() for l in levels):
            seniority = "entry"
        if any("senior" in l.lower() for l in levels):
            seniority = "senior"
    primary_loc = matched.get("nyc") or matched.get("bay") or matched.get("remote") or (r["locations"][0] if r["locations"] else "")
    job = {
        "id": job_id(r["company"], title, primary_loc),
        "title": title, "company": r["company"], "url": r["url"], "source": r["source"],
        "locations": sorted(set(l for l in r["locations"] if l))[:6],
        "primary_location": primary_loc,
        "buckets": buckets, "role": role, "seniority": seniority, "program": program,
        "salary": {"min": a, "max": b, "source": sal_src, "all": ranges_all[:6]},
        "years_min": years_min,
        "posted": posted,
        "snippet": desc[:420],
        "tags": company_meta.get("tags", []),
    }
    job["score"] = score(job)
    return job


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def load_companies():
    return json.loads(COMPANIES_PATH.read_text())


def run_company(c):
    t0 = time.time()
    try:
        recs = FETCHERS[c["ats"]](c)
        return c, recs, None, time.time() - t0
    except Exception as e:  # noqa
        return c, [], f"{type(e).__name__}: {str(e)[:140]}", time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true", help="only check that each source responds")
    ap.add_argument("--only", help="comma separated company names/tokens to run")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--cache-raw", help="write location-matched raw records to this .json.gz for --from-cache")
    ap.add_argument("--from-cache", help="re-classify from a cache written by --cache-raw instead of fetching")
    args = ap.parse_args()

    companies = load_companies()
    if args.only:
        keys = {k.strip().lower() for k in args.only.split(",")}
        companies = [c for c in companies if c["name"].lower() in keys or str(c.get("token", c.get("tenant", ""))).lower() in keys]

    seen = {}
    if SEEN_PATH.exists():
        seen = json.loads(SEEN_PATH.read_text())

    results, health, cache = [], [], []
    import gzip
    if args.from_cache:
        blob = json.loads(gzip.open(args.from_cache, "rt").read())
        health = blob["health"]
        by_name = {c["name"]: c for c in companies}
        for r in blob["raw"]:
            j = normalize(r, by_name.get(r["company"], {}))
            if j:
                results.append(j)
        companies = [by_name[n] for n in by_name]
        stream = []
    else:
        stream = None
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        for c, recs, err, secs in (stream if stream is not None else ex.map(run_company, companies)):
            status = "ok" if err is None else "fail"
            health.append({"company": c["name"], "ats": c["ats"], "status": status, "raw": len(recs),
                           "error": err, "secs": round(secs, 1)})
            flag = "OK " if err is None else "ERR"
            print(f"[{flag}] {c['name']:<28} {c['ats']:<15} {len(recs):>5} postings  {secs:5.1f}s  {err or ''}", flush=True)
            if args.validate:
                continue
            for r in recs:
                if args.cache_raw and classify_locations(r["locations"], r.get("remote", False))[0]:
                    cache.append(r)
                j = normalize(r, c)
                if j:
                    results.append(j)
    if args.cache_raw and not args.from_cache:
        with gzip.open(args.cache_raw, "wt") as f:
            f.write(json.dumps({"health": health, "raw": cache}))
        print(f"cached {len(cache)} raw records -> {args.cache_raw}")

    if args.validate:
        bad = [h for h in health if h["status"] != "ok" or h["raw"] == 0]
        print(f"\n{len(health) - len(bad)}/{len(health)} sources OK. Problems:")
        for h in bad:
            print(f"  - {h['company']} ({h['ats']}): {h['error'] or 'returned 0 postings'}")
        return

    # dedupe: same id, or same company + title + salary band (one req posted per office)
    dedup, by_key = {}, {}
    for j in results:
        key = (j["company"].lower(), norm_title(j["title"]), j["salary"]["min"], j["salary"]["max"])
        if key in by_key:
            k = by_key[key]
            k["buckets"] = sorted(set(k["buckets"]) | set(j["buckets"]))
            k["locations"] = sorted(set(k["locations"]) | set(j["locations"]))[:6]
            if j["score"] > k["score"]:
                k["url"], k["primary_location"], k["score"], k["posted"] = j["url"], j["primary_location"], j["score"], j["posted"] or k["posted"]
            continue
        if j["id"] in dedup:
            if j["score"] > dedup[j["id"]]["score"]:
                dedup[j["id"]] = j
            continue
        dedup[j["id"]] = j; by_key[key] = j
    jobs = list(dedup.values())
    for j in jobs:
        j["score"] = score(j)

    # first-seen tracking
    today = TODAY.isoformat()
    for j in jobs:
        j["first_seen"] = seen.get(j["id"], today)
        seen[j["id"]] = j["first_seen"]
        j["is_new"] = (TODAY - dt.date.fromisoformat(j["first_seen"])).days < NEW_DAYS
    # prune seen ids not present for a long time
    live = {j["id"] for j in jobs}
    cutoff = (TODAY - dt.timedelta(days=90)).isoformat()
    seen = {k: v for k, v in seen.items() if k in live or v >= cutoff}

    jobs.sort(key=lambda j: (-j["score"], j["posted"] or "", j["company"]))

    meta = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "salary_floor": SALARY_FLOOR, "new_days": NEW_DAYS,
        "counts": {
            "total": len(jobs),
            "nyc": sum("nyc" in j["buckets"] for j in jobs),
            "bay": sum("bay" in j["buckets"] for j in jobs),
            "remote": sum("remote" in j["buckets"] for j in jobs),
            "new": sum(j["is_new"] for j in jobs),
            "with_salary": sum(1 for j in jobs if j["salary"]["max"]),
        },
        "sources": health,
        "companies_tracked": len(companies),
    }
    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"meta": meta, "jobs": jobs}, indent=0, ensure_ascii=False)
    DATA_OUT.write_text(payload)
    # same data as a script, so docs/index.html works when double-clicked (file:// blocks fetch)
    DATA_OUT.with_suffix(".js").write_text("window.JOB_RADAR_DATA = " + payload + ";\n")
    SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_PATH.write_text(json.dumps(seen, indent=0, sort_keys=True))
    ok = sum(1 for h in health if h["status"] == "ok")
    print(f"\nWrote {len(jobs)} jobs ({meta['counts']['nyc']} NYC / {meta['counts']['bay']} Bay / "
          f"{meta['counts']['remote']} remote; {meta['counts']['with_salary']} with salary) from {ok}/{len(health)} sources -> {DATA_OUT}")


if __name__ == "__main__":
    main()
