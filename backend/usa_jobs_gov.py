# Peterson's Career Prep — Florida job scraper (via Miami-Dade Public Library System).
#
# ACCESS / AUTH FLOW (this is the important part):
#   Peterson's Career Prep (tcpr.petersons.com) is NOT public. It is unlocked through the
#   Gale proxy link that MDPLS exposes on its learning page. Hitting the job URLs directly
#   returns 401. The working order is:
#     1. https://mdpls.org/learning
#     2. click "Peterson's Career Prep"  ->  https://link.gale.com/apps/PCPR?&userGroupName=29081_mdpls
#     3. Gale redirects to https://tcpr.petersons.com/  (session cookies now set)
#     4. the "Job Search" tile leads to /job-search, whose "Government jobs" option calls:
#            GET /api/v1/jobs?page[number]=N&page[size]=..&filter[location]=FL&filter[timeFrame]=7d
#   We reproduce steps 1-3 in one Playwright context so the session cookies persist, then
#   read the JSON:API directly (far more reliable than scraping the Vue-rendered DOM).
#
# The jobs API returns clean JSON, so there is no HTML parsing. Each job has:
#   attributes: title, description, url, company, location, country, zipCode, addedAt
#
# NOTE: "Government jobs" (this API, sourced from usajobs.gov) vs "Non-government jobs"
#       (opens a separate external board) are two different sources. This scraper targets
#       the Government jobs API.
#
# Install: pip install playwright beautifulsoup4 lxml
#          playwright install chromium
# Run:     python scraper2.py

import json
import csv
import re
import time
import urllib.request
from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ---- Access chain ----
MDPLS_LEARNING_URL = "https://mdpls.org/learning"
GALE_ENTRY_URL = "https://link.gale.com/apps/PCPR?&userGroupName=29081_mdpls"
PETERSONS_HOME = "https://tcpr.petersons.com/"
JOBS_API = "https://tcpr.petersons.com/api/v1/jobs"

# ---- Search filters (these mirror the site's own "Government jobs" query) ----
LOCATION_FILTER = "FL"     # state code the site filters on
TIME_FRAME = "7d"          # site default; jobs added in the last 7 days
PAGE_SIZE = 100            # server may cap this; pagination follows meta.lastPage regardless

# Run headed (False) to watch the auth/redirect chain; True for silent/background runs.
HEADLESS = True
DEBUG_DUMPS = False        # set True to save HTML/screenshots of each hop for troubleshooting

# When True, also write South-Florida-only outputs (Miami-Dade, Broward, Palm Beach counties).
SAVE_SOUTH_FLORIDA = True

# Close/expiration dates and salary aren't in Peterson's API — they live on each usajobs.gov
# job page (JobPosting "validThrough" + the visible "Salary" field). When True, fetch that
# page per job to add close_date and salary. ENRICH_SCOPE controls how many pages we fetch:
# "south_florida" (default, ~few dozen requests) or "all" (one request per job, slower).
# ENRICH_DELAY is a polite pause between usajobs.gov requests.
ENRICH_CLOSE_DATES = True
ENRICH_SCOPE = "south_florida"   # "south_florida" or "all"
ENRICH_DELAY = 0.4               # seconds between usajobs.gov requests

# South Florida counties -> city/keyword list used to classify a job's location string.
# The API only filters at state level (FL), so county filtering is done here on the returned
# location text. Add cities here if new ones show up in future runs.
SOUTH_FL_COUNTIES = {
    "Miami-Dade": [
        "Miami-Dade", "Miami", "Doral", "Hialeah", "Hialeah Gardens", "Homestead",
        "Miami Beach", "Miami Gardens", "North Miami", "North Miami Beach", "South Miami",
        "Coral Gables", "Aventura", "Kendall", "Cutler Bay", "Palmetto Bay", "Pinecrest",
        "Sunny Isles", "Opa-locka", "Sweetwater", "Florida City", "Key Biscayne",
        "Miami Lakes", "Miami Springs", "Coral Way", "Westchester",
    ],
    "Broward": [
        "Broward", "Fort Lauderdale", "Ft. Lauderdale", "Hollywood", "Pembroke Pines",
        "Coral Springs", "Miramar", "Sunrise", "Plantation", "Davie", "Deerfield Beach",
        "Pompano Beach", "Weston", "Tamarac", "Margate", "Coconut Creek", "Oakland Park",
        "Hallandale", "Hallandale Beach", "Lauderhill", "Lauderdale Lakes", "Dania Beach",
        "Cooper City", "Parkland", "Wilton Manors", "Lighthouse Point",
    ],
    "Palm Beach": [
        "Palm Beach", "West Palm Beach", "North Palm Beach", "Palm Beach Gardens",
        "Boca Raton", "Boynton Beach", "Delray Beach", "Jupiter", "Wellington",
        "Lake Worth", "Riviera Beach", "Royal Palm Beach", "Greenacres", "Belle Glade",
        "Lantana", "Juno Beach",
    ],
}


def south_florida_county(location):
    """Return 'Miami-Dade' / 'Broward' / 'Palm Beach' if the location falls in one of the
    three South Florida counties, else None. Matches on whole words so 'Miami' won't hit
    unrelated strings and 'Palm Beach' won't match 'Palm Bay' (Brevard)."""
    if not location:
        return None
    for county, cities in SOUTH_FL_COUNTIES.items():
        for kw in cities:
            if re.search(r"\b" + re.escape(kw) + r"\b", location, re.IGNORECASE):
                return county
    return None


def dump_page(page, tag):
    """Diagnostic helper: save URL/title/HTML/screenshot of the current page."""
    if not DEBUG_DUMPS:
        return
    try:
        print(f"    [dump:{tag}] url={page.url}  title={page.title()!r}")
        with open(f"debug_{tag}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        page.screenshot(path=f"debug_{tag}.png", full_page=True)
    except Exception as e:
        print(f"    [dump:{tag}] failed: {e}")


def authenticate(context, page):
    """Walk mdpls.org -> Gale -> Peterson's so the session cookies get established.
    Returns the page that holds the authenticated Peterson's session."""
    print(f"[1] Opening library page: {MDPLS_LEARNING_URL}")
    page.goto(MDPLS_LEARNING_URL, wait_until="networkidle", timeout=60000)
    time.sleep(2)
    dump_page(page, "step1_mdpls_learning")

    # Click the Peterson's Career Prep link. It's target="_blank", so it opens a new tab.
    gale_page = page
    link = page.query_selector("a[href*='link.gale.com/apps/PCPR']") or \
        page.query_selector("a:has-text(\"Peterson's Career Prep\")")
    if link:
        print("[2] Clicking Peterson's Career Prep link (new tab expected)...")
        try:
            with context.expect_page(timeout=30000) as popup_info:
                link.click()
            gale_page = popup_info.value
            gale_page.wait_for_load_state("networkidle", timeout=60000)
        except Exception:
            page.wait_for_load_state("networkidle", timeout=60000)
            gale_page = page
    else:
        print("[2] Link not found; navigating to Gale directly (with referer)...")
        gale_page.goto(GALE_ENTRY_URL, wait_until="networkidle",
                       timeout=60000, referer=MDPLS_LEARNING_URL)

    time.sleep(3)
    print(f"    Landed on: {gale_page.url}")
    dump_page(gale_page, "step2_after_gale")

    if "petersons.com" not in gale_page.url:
        print("    WARNING: did not land on tcpr.petersons.com — session may not be authenticated.")
    return gale_page


def build_jobs_url(page_number):
    # Brackets are intentional and match the site's own request format.
    return (f"{JOBS_API}?page[number]={page_number}&page[size]={PAGE_SIZE}"
            f"&filter[location]={LOCATION_FILTER}&filter[timeFrame]={TIME_FRAME}")


def fetch_usajobs_details(url):
    """Fetch a usajobs.gov job page and pull the close date (JobPosting validThrough), the
    posted date, and the salary. Salary is taken from the visible 'Salary' field (which shows
    the full range, e.g. '$56,000 - $68,000 per year'), falling back to the JSON-LD baseSalary
    single value. Returns {} for non-usajobs URLs or on any error."""
    if not url or "usajobs" not in url.lower():
        return {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    except Exception:
        return {}
    out = {}
    m = re.search(r'"validThrough"\s*:\s*"([^"]+)"', html)
    if m:
        out["close_date"] = m.group(1)
    m = re.search(r'"datePosted"\s*:\s*"([^"]+)"', html)
    if m:
        out["date_posted_usajobs"] = m.group(1)

    # Preferred: the visible "Salary" dt/dd, which carries the full displayed range.
    m = re.search(r"Salary</dt>\s*<dd>(.*?)</dd>", html, re.S)
    if m:
        out["salary"] = re.sub(r"\s+", " ", m.group(1)).strip()
    else:
        # Fallback: JSON-LD baseSalary (usually a single value + interval).
        m = re.search(r'"baseSalary".*?"value"\s*:\s*([\d.]+)\s*,\s*"unitText"\s*:\s*"([^"]+)"',
                      html, re.S)
        if m:
            amount = float(m.group(1))
            out["salary"] = f"${amount:,.0f} per {m.group(2).lower()}"
    return out


def enrich_from_usajobs(jobs):
    """Add 'close_date' and 'salary' (and usajobs 'date_posted') to each job by reading its
    usajobs.gov page."""
    total = len(jobs)
    print(f"    Enriching {total} job(s) with close date + salary from usajobs.gov...")
    found = 0
    for i, job in enumerate(jobs, 1):
        details = fetch_usajobs_details(job.get("href", ""))
        job["close_date"] = details.get("close_date", "")
        job["salary"] = details.get("salary", "")
        if details.get("date_posted_usajobs"):
            job["date_posted_usajobs"] = details["date_posted_usajobs"]
        if job["close_date"] or job["salary"]:
            found += 1
        if i % 10 == 0 or i == total:
            print(f"      {i}/{total} (enriched: {found})")
        time.sleep(ENRICH_DELAY)
    return jobs


def parse_job(item):
    a = item.get("attributes", {})
    return {
        "id": item.get("id", ""),
        "title": a.get("title", ""),
        "company": a.get("company", ""),
        "location": a.get("location", ""),
        "country": a.get("country", ""),
        "zip_code": a.get("zipCode", ""),
        "href": a.get("url", ""),
        "description": a.get("description", ""),
        "added_at": a.get("addedAt", ""),
    }


def fetch_all_jobs(page):
    """Page through the jobs API using the authenticated session and return all jobs."""
    jobs = []
    page_number = 1
    last_page = 1
    while page_number <= last_page:
        url = build_jobs_url(page_number)
        resp = page.request.get(url)
        if resp.status != 200:
            print(f"    Jobs API page {page_number} returned HTTP {resp.status}; stopping.")
            break
        payload = resp.json()
        meta = payload.get("meta", {})
        last_page = meta.get("lastPage", page_number)
        total = meta.get("total", "?")
        batch = [parse_job(it) for it in payload.get("data", [])]
        jobs.extend(batch)
        print(f"    page {page_number}/{last_page}  (+{len(batch)} jobs, total reported: {total})")
        page_number += 1
    return jobs


def scrape_job_search():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        try:
            session_page = authenticate(context, page)
        except Exception as e:
            print(f"Authentication failed: {e}")
            browser.close()
            return []

        print(f"[3] Fetching jobs (location={LOCATION_FILTER}, timeFrame={TIME_FRAME})...")
        try:
            jobs = fetch_all_jobs(session_page)
        except Exception as e:
            print(f"Failed while fetching jobs API: {e}")
            jobs = []

        browser.close()
        return jobs


def save_south_florida(jobs):
    """Filter to jobs located in Miami-Dade, Broward, or Palm Beach counties, tag each with
    its county, and save scraped_data_south_florida.json / .csv."""
    from collections import Counter
    sf = []
    for job in jobs:
        county = south_florida_county(job.get("location", ""))
        if county:
            tagged = dict(job)
            tagged["county"] = county
            sf.append(tagged)

    counts = Counter(j["county"] for j in sf)
    print(f"\nSouth Florida jobs (Miami-Dade / Broward / Palm Beach): {len(sf)}")
    for county in ("Miami-Dade", "Broward", "Palm Beach"):
        print(f"    {county}: {counts.get(county, 0)}")

    # Add close dates + salary from usajobs.gov (unless already enriched at the "all" scope).
    if ENRICH_CLOSE_DATES and ENRICH_SCOPE == "south_florida":
        enrich_from_usajobs(sf)

    with open("scraped_data_south_florida.json", "w", encoding="utf-8") as f:
        json.dump(sf, f, indent=2, ensure_ascii=False)
    print("Saved scraped_data_south_florida.json")

    fieldnames = ["title", "company", "county", "location", "country", "zip_code",
                  "href", "salary", "added_at", "close_date", "description", "id"]
    with open("scraped_data_south_florida.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in sf:
            writer.writerow({k: job.get(k, "") for k in fieldnames})
    print("Saved scraped_data_south_florida.csv")
    return sf


def save_results(jobs):
    # Deduplicate by job id (fall back to href).
    seen = set()
    unique = []
    for job in jobs:
        key = job.get("id") or job.get("href") or job.get("title")
        if key and key not in seen:
            seen.add(key)
            unique.append(job)

    print(f"\nTotal unique jobs found: {len(unique)}")

    # Enrich every job with close date + salary only when explicitly asked (one request/job).
    if ENRICH_CLOSE_DATES and ENRICH_SCOPE == "all":
        enrich_from_usajobs(unique)

    with open("scraped_data.json", "w", encoding="utf-8") as f:
        json.dump(unique, f, indent=2, ensure_ascii=False)
    print("Saved scraped_data.json")

    fieldnames = ["title", "company", "location", "country", "zip_code",
                  "href", "salary", "added_at", "close_date", "description", "id"]
    with open("scraped_data.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for job in unique:
            writer.writerow({k: job.get(k, "") for k in fieldnames})
    print("Saved scraped_data.csv")

    if SAVE_SOUTH_FLORIDA:
        save_south_florida(unique)

    if not unique:
        print(
            "\nWARNING: No jobs were returned. Check that:\n"
            "1. The auth chain reached tcpr.petersons.com (run with HEADLESS=False,\n"
            "   DEBUG_DUMPS=True to inspect each hop).\n"
            "2. The Gale entry URL / userGroupName is still valid:\n"
            f"     {GALE_ENTRY_URL}\n"
            "3. There are actually jobs for the current filters "
            f"(location={LOCATION_FILTER}, timeFrame={TIME_FRAME})."
        )


if __name__ == "__main__":
    jobs = scrape_job_search()
    save_results(jobs)
