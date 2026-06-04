import asyncio
import json
import os
import random
import sqlite3
import time
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from dotenv import load_dotenv
from n8n_client import listing_exists, save_listing

load_dotenv()

DI_USER = os.getenv("DATAIMPULSE_USER")
DI_PASS = os.getenv("DATAIMPULSE_PASS")
DI_HOST = os.getenv("DATAIMPULSE_HOST")
DI_PORT = os.getenv("DATAIMPULSE_PORT")

PROXY = {
    "server":   f"http://{DI_HOST}:{DI_PORT}",
    "username": f"{DI_USER}_country_ae",
    "password": DI_PASS
}

URLS_TABLE = "data_table_user_nwDNwAiQOn7gLKXG"

BUSINESS_KEYWORDS = [
    "trading", "trade", "shop", "store", "mart",
    "company", "co.", "llc", "ltd", "enterprise",
    "wholesale", "supplier", "dealer", "distributor",
    "furniture", "appliances", "electronics",
    "new & used", "buy & sell", "used &"
]

def load_urls():
    try:
        db = os.path.expanduser("~/.n8n/database.sqlite")
        conn = sqlite3.connect(db, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute(
            f'SELECT url FROM "{URLS_TABLE}" WHERE active = "yes"'
        )
        rows = cursor.fetchall()
        conn.close()
        urls = [r[0] for r in rows if r[0]]
        print(f"Loaded {len(urls)} URLs from n8n")
        return urls
    except Exception as e:
        print(f"Error loading URLs: {e}")
        return []

def passes_prefilter(listing):
    if not listing.get("has_phone_number"):
        return False
    if listing.get("is_verified_business"):
        print("  Skip - verified business")
        return False
    if listing.get("is_trusted_seller"):
        print("  Skip - trusted seller")
        return False
    if listing.get("business"):
        print("  Skip - business account")
        return False
    return True

def is_business_name(name):
    return any(k in name.lower() for k in BUSINESS_KEYWORDS)

async def get_listings_playwright(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        context = await browser.new_context(
            proxy=PROXY,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()
        print(f"Fetching: {url}")
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=90000
        )
        await page.wait_for_timeout(8000)
        content = await page.content()
        print(f"Content: {len(content)} chars")
        await browser.close()

    soup = BeautifulSoup(content, "html.parser")
    next_data = soup.find("script", id="__NEXT_DATA__")
    if not next_data:
        print("No __NEXT_DATA__ found")
        return []

    data = json.loads(next_data.text)
    redux_actions = data["props"]["pageProps"]["reduxWrapperActionsGIPP"]
    for action in redux_actions:
        if action.get("type") == "listings/fetchListingDataForQuery/fulfilled":
            hits = action["payload"]["hits"]
            pagination = action["payload"]["pagination"]
            print(f"Found {len(hits)} listings")
            print(f"Total: {pagination['totalHits']}")
            return hits

    print("Listing data not found")
    return []

async def process_url(url):
    print(f"\n{'='*50}")
    print(f"URL: {url}")
    print(f"{'='*50}")
    listings = await get_listings_playwright(url)
    if not listings:
        print("No listings found")
        return

    new_count = 0
    skipped   = 0

    for listing in listings:
        name     = listing.get("name", {})
        name_en  = name.get("en", "") if isinstance(name, dict) else str(name)
        url_data = listing.get("absolute_url", {})
        url_en   = url_data.get("en", "") if isinstance(url_data, dict) else str(url_data)
        listing_id = str(listing.get("id", ""))

        print(f"\n{name_en[:50]}")
        print(f"   AED {listing.get('price')} | ID: {listing_id}")

        if not passes_prefilter(listing):
            skipped += 1
            continue
        if is_business_name(name_en):
            print("  Skipped - business name")
            skipped += 1
            continue
        if listing_exists(listing_id):
            print("  Already in database - skip")
            skipped += 1
            continue

        saved = save_listing({
            "listing_id": listing_id,
            "name":       name_en,
            "price":      str(listing.get("price", "")),
            "url":        url_en,
            "phone":      "",
            "status":     "pending_phone_extraction"
        })

        if saved:
            new_count += 1
            print(f"  New listing saved!")

        time.sleep(random.uniform(1, 3))

    print(f"\nNew: {new_count} | Skipped: {skipped}")

if __name__ == "__main__":
    URLS = load_urls()
    if not URLS:
        print("No URLs found in n8n scraper_urls table")
        print("Add URLs to scraper_urls table in n8n with active=yes")
    else:
        for url in URLS:
            asyncio.run(process_url(url))
