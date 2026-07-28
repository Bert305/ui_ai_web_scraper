# Transforms the scraped South Florida jobs into the upload format (see example.csv).
#
# Input : source_scraped_data_south_florida.csv  (title, company, location, href, salary,
#                                                  added_at, close_date, description, industry)
# Lookups: industries_rows.csv (name -> id), companies_id_download.csv (name -> company_id)
# Output: jobs_upload.csv  (columns/order match example.csv)
#
# Transformations applied:
#   href       -> application_url
#   company    -> company_name  (+ company_id via companies_id_download.csv)
#   close_date -> expires_at     (append "T00:00:00.000000Z" if date-only)
#   industry   -> industry_id    (name mapped to number via industries_rows.csv)
#   salary     -> salary_min / salary_max  (commas and $ stripped)
#   salary "per year" -> job_type Full-time / salary_period year
#   salary "per hour" -> job_type Part-time / salary_period hour
#   location   -> "Florida" replaced with "FL"
#   posted_at / created_at -> the date/time this script runs
#
# Run: python wrangle_for_upload.py

# Part 2 - Go to Supabase and run the SQL Query to get the companies_id_download.csv file (name -> company_id) for all companies in the Workforce Miami database.
# Part 2.5 - Don't forget to add the new companies to the Workforce Miami database before running this script, or they won't have a company_id and will be left blank in the output.
# Part 3 - Run this script to generate jobs_upload.csv, which can be uploaded to Supabase.
# Files needed to run script:
#   source_scraped_data_south_florida.csv  (from usa_jobs_gov.py)
#   industries_rows.csv  (csv file from Workforce Miami Database -- backend/industries_rows.csv)
#   companies_id_download.csv  (from Workforce Miami Database -- Supabase export)

import csv
import re
from datetime import datetime, timezone

SOURCE_FILE = "source_scraped_data_south_florida3.csv"
INDUSTRIES_FILE = "industries_rows.csv"
COMPANIES_FILE = "companies_id_download2.csv"
OUTPUT_FILE = "jobs_upload3.csv"

# Manual fixes for industry names in the source that don't exactly match industries_rows.csv.
# (e.g. "Telecommunications" has no exact row — map it here if you want a number.)
INDUSTRY_ALIASES = {
    # "Telecommunications": "33",  # e.g. Information Technology; uncomment/change to use
}

# Output columns, in the exact order example.csv uses.
OUTPUT_COLUMNS = [
    "title", "posted_at", "expires_at", "created_at", "salary_min", "salary_max",
    "industry_id", "description", "company_name", "location", "job_type",
    "application_url", "is_active", "salary_period", "is_bulk_upload", "remote_type",
    "approval_status", "experience_level", "contact_email", "company_id", "category",
    "qualifications", "responsibilities", "is_featured", "verified", "applicant_count",
    "outbound_clicks", "applications_count", "keywords", "external_clicks",
]

# Constant/default values (taken from example.csv).
DEFAULTS = {
    "is_active": "TRUE",
    "is_bulk_upload": "TRUE",
    "approval_status": "Approved",
    "applicant_count": "0",
    "outbound_clicks": "0",
    "applications_count": "0",
    "external_clicks": "0",
}


def load_lookup(path, key_col, val_col):
    """Load a CSV into a case-insensitive name -> value dict."""
    out = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row.get(key_col) or "").strip().lower()
            if key:
                out[key] = (row.get(val_col) or "").strip()
    return out


def parse_salary(salary):
    """Return (salary_min, salary_max, salary_period, job_type) from a salary string like
    '$56,000 - $68,000 per year' or '$18.70 - $23.17 per hour ...'. Amounts have $ and
    commas stripped."""
    amounts = re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)", salary or "")
    clean = [a.replace(",", "") for a in amounts]
    salary_min = clean[0] if clean else ""
    salary_max = clean[1] if len(clean) > 1 else salary_min

    low = (salary or "").lower()
    if "per year" in low or "/year" in low or "annually" in low:
        return salary_min, salary_max, "year", "Full-time"
    if "per hour" in low or "/hour" in low or "hourly" in low:
        return salary_min, salary_max, "hour", "Part-time"
    return salary_min, salary_max, "", ""


def to_expires_at(close_date):
    """Convert a date-only close_date (e.g. '2026-07-09') into ISO with time+Z."""
    cd = (close_date or "").strip()
    if not cd:
        return ""
    if "T" in cd:
        return cd
    return cd + "T00:00:00.000000Z"


def fix_location(location):
    """Replace 'Florida' with 'FL' (whole word)."""
    return re.sub(r"\bFlorida\b", "FL", location or "").strip()


def main():
    industries = load_lookup(INDUSTRIES_FILE, "name", "id")
    companies = load_lookup(COMPANIES_FILE, "name", "company_id")
    industry_aliases = {k.strip().lower(): v for k, v in INDUSTRY_ALIASES.items()}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    missing_industries = []   # (industry_name, title) for rows left with a blank industry_id
    missing_companies = set()
    rows_out = []

    with open(SOURCE_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            salary_min, salary_max, salary_period, job_type = parse_salary(row.get("salary", ""))

            industry_name = (row.get("industry") or "").strip()
            industry_key = industry_name.lower()
            industry_id = industries.get(industry_key) or industry_aliases.get(industry_key, "")
            if industry_name and not industry_id:
                missing_industries.append((industry_name, (row.get("title") or "").strip()))

            company_name = (row.get("company") or "").strip()
            company_id = companies.get(company_name.lower(), "")
            if company_name and not company_id:
                missing_companies.add(company_name)

            out = {c: "" for c in OUTPUT_COLUMNS}
            out.update(DEFAULTS)
            out.update({
                "title": (row.get("title") or "").strip(),
                "posted_at": now,
                "created_at": now,
                "expires_at": to_expires_at(row.get("close_date", "")),
                "salary_min": salary_min,
                "salary_max": salary_max,
                "industry_id": industry_id,
                "description": (row.get("description") or "").strip(),
                "company_name": company_name,
                "location": fix_location(row.get("location", "")),
                "job_type": job_type,
                "application_url": (row.get("href") or "").strip(),
                "salary_period": salary_period,
                "company_id": company_id,
            })
            rows_out.append(out)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"Wrote {len(rows_out)} rows to {OUTPUT_FILE}")
    if missing_industries:
        print(f"\nWARNING: {len(missing_industries)} row(s) left with a BLANK industry_id "
              "(no match in industries_rows.csv). Fix these manually or add to INDUSTRY_ALIASES:")
        for industry_name, title in missing_industries:
            print(f"   - industry {industry_name!r}  ->  job: {title}")
    if missing_companies:
        print("\nWARNING: companies with no match in companies_id_download.csv "
              "(company_id left blank):")
        for name in sorted(missing_companies):
            print(f"   - {name}")


if __name__ == "__main__":
    main()
