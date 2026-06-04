import asyncio
import json
import os
import random
import re
import base64
import requests
from datetime import datetime
import pytz
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from twocaptcha import TwoCaptcha
from dotenv import load_dotenv
from n8n_client import already_contacted, mark_contacted, update_listing_phone, listing_exists
from n8n_client import DB_PATH, LISTINGS_TABLE, get_conn

load_dotenv()

TEST_MODE   = True
TEST_PHONE  = "9**89315****"
MAX_PER_RUN = 10
DUBAI_TZ    = pytz.timezone("Asia/Dubai")

DI_USER     = os.getenv("DATAIMPULSE_USER")
DI_PASS     = os.getenv("DATAIMPULSE_PASS")
DI_HOST     = os.getenv("DATAIMPULSE_HOST")
DI_PORT     = os.getenv("DATAIMPULSE_PORT")
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")
WHAPI_URL   = os.getenv("WHAPI_URL", "https://gate.whapi.cloud")
GEMINI_KEY  = os.getenv("GEMINI_API_KEY")
CAPTCHA_KEY = os.getenv("CAPTCHA_API_KEY")
GEMINI_URL  = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_KEY}"

PROXY = {
    "server":   f"http://{DI_HOST}:{DI_PORT}",
    "username": f"{DI_USER}",
    "password": DI_PASS
}

DUBIZZLE_SITEKEY = "dd6e16a7-972e-47d2-93d0-96642fb6d8de"

solver = TwoCaptcha(CAPTCHA_KEY)

def is_within_time_window():
    now = datetime.now(DUBAI_TZ)
    hour = now.hour
    in_window = 8 <= hour < 22
    if not in_window:
        print(f"  Outside sending window (Dubai time: {now.strftime('%H:%M')})")
    return in_window

def clean_product_name(title):
    try:
        response = requests.post(
            GEMINI_URL,
            json={"contents": [{"parts": [{"text": f"Extract just the short product name from this listing title. Return only the product name, nothing else.\nExamples:\n'Brand new styling coffee table 180x200cm' -> 'coffee table'\n'iPhone 15 with broken screen' -> 'iPhone 15'\n'1960 Corvette in excellent condition for sale' -> 'Corvette'\nTitle: {title}"}]}]},
            timeout=30
        )
        if response.status_code == 200:
            return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        return title
    except:
        return title

def send_whatsapp(phone, item_name):
    target     = TEST_PHONE if TEST_MODE else phone
    clean_name = clean_product_name(item_name)
    message    = f"Hi, is your {clean_name} still available for sale?"
    if TEST_MODE:
        print(f"  TEST MODE: sending to {target}")
    print(f"  Message: {message}")
    try:
        r = requests.post(
            f"{WHAPI_URL}/messages/text",
            headers={
                "Authorization": f"Bearer {WHAPI_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "to":   f"{target}@s.whatsapp.net",
                "body": message
            },
            timeout=120
        )
        if r.status_code == 200:
            print("  WhatsApp sent!")
            return True
        else:
            print(f"  Failed: {r.text[:100]}")
            return False
    except Exception as e:
        print(f"  Error: {e}")
        return False

async def solve_hcaptcha(page, url):
    try:
        content = await page.content()
        if 'incapsula' not in content.lower() and 'NOINDEX' not in content:
            return True

        print("  Incapsula challenge detected — solving via 2Captcha...")
        sitekey = DUBIZZLE_SITEKEY
        print(f"  Sitekey: {sitekey}")

        result = solver.hcaptcha(sitekey=sitekey, url=url)
        token = result['code']
        print("  Got solution token")

        await page.evaluate(f"""
            () => {{
                const el = document.querySelector('[name="h-captcha-response"]');
                if (el) el.value = '{token}';
                const el2 = document.querySelector('[name="g-recaptcha-response"]');
                if (el2) el2.value = '{token}';
            }}
        """)

        await page.evaluate("""
            () => {
                const form = document.querySelector('form');
                if (form) form.submit();
            }
        """)

        await page.wait_for_timeout(5000)
        print("  hCaptcha solved!")
        return True

    except Exception as e:
        print(f"  Captcha solve error: {e}")
        return False

async def extract_phone(page, listing_url):
    try:
        await page.goto(listing_url, wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(7000)

        await solve_hcaptcha(page, listing_url)

        await page.evaluate("window.scrollTo(0, 300)")
        await page.wait_for_timeout(4000)

        buttons = await page.query_selector_all("button")
        print(f"  Found {len(buttons)} buttons")

        show_btn = await page.query_selector("[data-testid='call-cta-button']")
        if not show_btn:
            print("  No show number button found")
            return ""

        print("  Clicking show number button...")
        await show_btn.click()
        await page.wait_for_timeout(6000)

        # Method 1 - JavaScript DOM
        phone_js = await page.evaluate("""
            () => {
                const allText = document.body.innerText;
                const match = allText.match(/(\\+971|00971|971|05|\\+9715)\\d{7,9}/);
                return match ? match[0] : null;
            }
        """)
        if phone_js:
            print(f"  JS phone: {phone_js}")
            return re.sub(r"\D", "", phone_js)

        # Method 2 - HTML content
        content = await page.content()
        for pattern in [r'\+971\d{8,9}', r'971\d{8,9}', r'05\d{8}']:
            matches = re.findall(pattern, content)
            if matches:
                phone = re.sub(r"\D", "", matches[0])
                print(f"  Content phone: {phone}")
                return phone

        # Method 3 - Gemini screenshot
        await page.screenshot(path="/home/scraper/full_page.png")
        try:
            with open("/home/scraper/full_page.png", "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")
            resp = requests.post(
                GEMINI_URL,
                json={"contents": [{"parts": [{"inline_data": {"mime_type": "image/png", "data": img_data}}, {"text": "Find the phone number in this Dubizzle screenshot. Return ONLY the digits. If not found return NOT_FOUND."}]}]},
                timeout=30
            )
            if resp.status_code == 200:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                if "NOT_FOUND" not in text:
                    phone = re.sub(r"\D", "", text)
                    if 9 <= len(phone) <= 12:
                        return phone
        except:
            pass

        print("  Phone not found")
        return ""
    except Exception as e:
        print(f"  Error: {e}")
        return ""

def get_pending_listings(limit=10):
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            f'''SELECT listing_id, name, url, price
                FROM "{LISTINGS_TABLE}"
                WHERE status = "pending_phone_extraction"
                LIMIT ?''',
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"listing_id": r[0], "name": r[1], "url": r[2], "price": r[3]} for r in rows]
    except Exception as e:
        print(f"  Error getting pending: {e}")
        return []

async def process_pending():
    if not is_within_time_window():
        print("Outside 8am-10pm Dubai window. Skipping.")
        return

    listings = get_pending_listings(MAX_PER_RUN)
    print(f"Found {len(listings)} pending listings to process")

    if not listings:
        print("No pending listings")
        return

    with open("/home/scraper/dubizzle_session.json") as f:
        cookies = json.load(f)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1280,800",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process"
            ]
        )

        sent    = 0
        skipped = 0

        for listing in listings:
            listing_id = listing["listing_id"]
            name       = listing["name"]
            url        = listing["url"]

            print(f"\n{'─'*40}")
            print(f"{name[:50]}")

            context = await browser.new_context(
                proxy=PROXY,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            await context.add_cookies(cookies)
            page = await context.new_page()
            await Stealth().apply_stealth_async(page)

            phone = await extract_phone(page, url)

            await page.close()
            await context.close()

            if not phone:
                print("  No phone — skipping")
                skipped += 1
                continue

            if already_contacted(phone):
                print(f"  Already contacted {phone} — skip")
                update_listing_phone(listing_id, phone)
                skipped += 1
                continue

            success = send_whatsapp(phone, name)

            if success:
                update_listing_phone(listing_id, phone)
                mark_contacted(phone, listing_id)
                sent += 1

            delay = random.randint(30, 60)
            print(f"  Waiting {delay}s...")
            await asyncio.sleep(delay)

        await browser.close()
        print(f"\nSent: {sent} | Skipped: {skipped}")

if __name__ == "__main__":
    asyncio.run(process_pending())
