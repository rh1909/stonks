import csv
import datetime
import os
import re
from decimal import Decimal, InvalidOperation

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


LISTINGS = (
    ("https://market.tase.co.il/he/market_data/securities/data/all", 2, 4, 3),
    ("https://market.tase.co.il/he/market_data/f-etfs", 1, 2, 6),
)
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "dist", "tase_prices.csv")
SECURITY_LINK = 'a[href*="/market_data/security/"]'


def parse_price(value):
    normalized = value.replace(",", "").replace("−", "-").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return Decimal(match.group(0)) / Decimal("100")
    except InvalidOperation:
        return None


def scrape_listing(driver, wait, url, security_column, price_column, type_column, prices):
    driver.get(url)

    for page_number in range(1, 100):
        wait.until(lambda browser: len(browser.find_elements(By.CSS_SELECTOR, SECURITY_LINK)) > 0)
        links = driver.find_elements(By.CSS_SELECTOR, SECURITY_LINK)
        first_href = links[0].get_attribute("href")

        for link in links:
            row = link.find_element(By.XPATH, "ancestor::tr")
            cells = row.find_elements(By.CSS_SELECTOR, "td")
            required_column = max(security_column, price_column, type_column)
            if len(cells) <= required_column:
                continue

            security_number = re.sub(r"\D", "", cells[security_column].text)
            price = parse_price(cells[price_column].text)
            if not security_number or price is None:
                continue

            prices[int(security_number)] = (
                format(price.normalize(), "f"),
                link.text.strip(),
                cells[type_column].text.strip(),
            )

        next_container = driver.find_element(By.CSS_SELECTOR, "li.pagination-next")
        if next_container.get_attribute("aria-disabled") == "true":
            return

        next_link = next_container.find_element(By.CSS_SELECTOR, 'a[aria-label="לעמוד הבא"]')
        driver.execute_script("arguments[0].click();", next_link)
        wait.until(
            lambda browser: (
                browser.find_elements(By.CSS_SELECTOR, SECURITY_LINK)
                and browser.find_elements(By.CSS_SELECTOR, SECURITY_LINK)[0].get_attribute("href")
                != first_href
            )
        )

    raise RuntimeError(f"TASE pagination did not finish for {url}")


def export_all_tase_prices():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 60)
    prices = {}

    try:
        for listing in LISTINGS:
            scrape_listing(driver, wait, *listing, prices)
    finally:
        driver.quit()

    if len(prices) < 500:
        raise ValueError(f"Only {len(prices)} valid TASE rows were found")

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    today = datetime.date.today().isoformat()
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(("symbol", "price", "price_date", "name", "type"))
        for symbol in sorted(prices):
            price, name, security_type = prices[symbol]
            writer.writerow((symbol, price, today, name, security_type))

    print(f"Wrote {len(prices)} TASE prices to {OUTPUT_FILE}")


if __name__ == "__main__":
    export_all_tase_prices()
