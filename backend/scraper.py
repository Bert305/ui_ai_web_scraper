# Target URL: https://northmiamims.net/staff-directory/
# Extracts: Name, Position, Department, Email from staff directory table
# Install: pip install playwright beautifulsoup4 lxml
# After install run: playwright install chromium
# Run: python scraper.py

import json
import csv
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

TARGET_URL = "https://northmiamims.net/staff-directory/"
OUTPUT_JSON = "scraped_data.json"
OUTPUT_CSV = "scraped_data.csv"


def scrape():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print(f"Navigating to {TARGET_URL} ...")
        page.goto(TARGET_URL, wait_until="networkidle", timeout=60000)
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "lxml")

    # Find the staff table — the HTML shows a plain <table> with <tr><td> rows
    # The first row is the header row: Name, Position, Department, Email
    tables = soup.find_all("table")

    staff_table = None
    for table in tables:
        rows = table.find_all("tr")
        if rows:
            first_row_cells = [td.get_text(strip=True) for td in rows[0].find_all("td")]
            if "Name" in first_row_cells and "Email" in first_row_cells:
                staff_table = table
                break

    if staff_table is None:
        print("ERROR: Could not find the staff directory table on the page.")
        return

    rows = staff_table.find_all("tr")
    # Parse header from first row
    header_cells = [td.get_text(strip=True) for td in rows[0].find_all("td")]
    print(f"Header found: {header_cells}")

    # Map expected columns (handle slight variations gracefully)
    def find_index(header, *candidates):
        for candidate in candidates:
            for i, h in enumerate(header):
                if candidate.lower() in h.lower():
                    return i
        return None

    name_idx = find_index(header_cells, "Name")
    position_idx = find_index(header_cells, "Position")
    department_idx = find_index(header_cells, "Department")
    email_idx = find_index(header_cells, "Email")

    records = []
    skipped = 0

    for row in rows[1:]:
        cells = row.find_all("td")
        if not cells:
            continue

        def get_cell(idx):
            if idx is None or idx >= len(cells):
                return ""
            return cells[idx].get_text(strip=True)

        name = get_cell(name_idx)
        position = get_cell(position_idx)
        department = get_cell(department_idx)
        email = get_cell(email_idx)

        # Some rows in the HTML appear to have only 3 cells (missing Department)
        # e.g. Hollis, Bruce and Nilchian, Nasrin — handle gracefully
        # Detect if the row has 3 cells: the 3rd cell looks like an email
        if len(cells) == 3:
            # Columns are: Name, Position, Email (Department missing)
            name = cells[0].get_text(strip=True)
            position = cells[1].get_text(strip=True)
            department = ""
            email = cells[2].get_text(strip=True)

        # Require at minimum a name to include the record
        if not name:
            skipped += 1
            continue

        record = {
            "Name": name,
            "Position": position,
            "Department": department,
            "Email": email,
        }
        records.append(record)

    print(f"Extracted {len(records)} records. Skipped {skipped} empty rows.")

    # Save JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"JSON saved to {OUTPUT_JSON}")

    # Save CSV
    fieldnames = ["Name", "Position", "Department", "Email"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    print(f"CSV saved to {OUTPUT_CSV}")


if __name__ == "__main__":
    scrape()