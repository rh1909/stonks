import csv
import datetime
import glob
import os
import re
import shutil
import tempfile
import time
from decimal import Decimal, InvalidOperation

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


TASE_URL = "https://market.tase.co.il/he/market_data/securities/data/all"
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
DIST_DIR = os.path.join(SCRIPT_DIR, "dist")
OUTPUT_FILE = os.path.join(DIST_DIR, "tase_prices.csv")


def wait_for_csv(download_dir, timeout=120):
    deadline = time.time() + timeout
    last_size = -1
    stable_checks = 0

    while time.time() < deadline:
        candidates = [
            path
            for path in glob.glob(os.path.join(download_dir, "*"))
            if path.lower().endswith((".csv", ".txt")) and not path.endswith(".crdownload")
        ]
        if candidates:
            newest = max(candidates, key=os.path.getmtime)
            size = os.path.getsize(newest)
            if size > 0 and size == last_size:
                stable_checks += 1
                if stable_checks >= 2:
                    return newest
            else:
                stable_checks = 0
                last_size = size
        time.sleep(1)

    raise TimeoutError("TASE CSV download did not complete")


def decode_csv(path):
    raw = open(path, "rb").read()
    for encoding in ("utf-8-sig", "utf-16", "cp1255"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeError("Could not decode the TASE CSV export")


def find_column(header, hebrew_text, english_text, fallback):
    for index, value in enumerate(header):
        compact = re.sub(r"\s+", " ", value).strip().lower()
        if hebrew_text in compact or english_text in compact:
            return index
    return fallback


def parse_price(value):
    normalized = value.replace(",", "").replace("−", "-").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return Decimal(match.group(0)) / Decimal("100")
    except InvalidOperation:
        return None


def export_all_tase_prices():
    os.makedirs(DIST_DIR, exist_ok=True)
    download_dir = tempfile.mkdtemp(prefix="stonks-tase-")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )

    driver = webdriver.Chrome(options=options)
    try:
        wait = WebDriverWait(driver, 90)
        driver.get(TASE_URL)

        download_button = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'button[aria-label="הורדת נתונים"]'))
        )
        driver.execute_script("arguments[0].click();", download_button)

        csv_link = wait.until(
            EC.presence_of_element_located((By.XPATH, '//a[normalize-space()="CSV"]'))
        )
        driver.execute_script("arguments[0].click();", csv_link)
        downloaded_file = wait_for_csv(download_dir)
    finally:
        driver.quit()

    text = decode_csv(downloaded_file)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel

    rows = list(csv.reader(text.splitlines(), dialect))
    header_index = next(
        (
            index
            for index, row in enumerate(rows)
            if any("שער אחרון" in cell or "last price" in cell.lower() or "last rate" in cell.lower() for cell in row)
        ),
        None,
    )
    if header_index is None:
        raise ValueError("Could not find the TASE CSV header")

    header = rows[header_index]
    security_index = find_column(header, "מס' ני", "security no", 2)
    price_index = find_column(header, "שער אחרון", "last price", 4)
    if price_index == 4 and not any("last price" in cell.lower() for cell in header):
        price_index = find_column(header, "שער אחרון", "last rate", 4)
    name_index = find_column(header, "שם", "name", 0)
    type_index = find_column(header, "סוג ני", "security type", 3)

    output_rows = []
    today = datetime.date.today().isoformat()
    for row in rows[header_index + 1 :]:
        if len(row) <= max(security_index, price_index):
            continue

        security_number = re.sub(r"\D", "", row[security_index])
        price = parse_price(row[price_index])
        if not security_number or price is None:
            continue

        price_text = format(price.normalize(), "f")
        name = row[name_index].strip() if len(row) > name_index else ""
        security_type = row[type_index].strip() if len(row) > type_index else ""
        output_rows.append((int(security_number), price_text, today, name, security_type))

    if len(output_rows) < 500:
        raise ValueError(f"Only {len(output_rows)} valid TASE rows were found")

    output_rows.sort(key=lambda row: row[0])
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(("symbol", "price", "price_date", "name", "type"))
        writer.writerows(output_rows)

    shutil.rmtree(download_dir, ignore_errors=True)
    print(f"Wrote {len(output_rows)} TASE prices to {OUTPUT_FILE}")


if __name__ == "__main__":
    export_all_tase_prices()
