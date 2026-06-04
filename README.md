# Dubizzle WhatsApp Automation

> **Contract project — production system built for a Dubai-based client.**
> Fully automated pipeline that scrapes Dubizzle classifieds, extracts seller phone numbers, and sends personalised WhatsApp outreach — all within business hours, with zero duplicate contacts.

---

## What It Does

A client in Dubai needed a hands-free system to reach individual sellers on Dubizzle before competitors could. This pipeline:

1. Scrapes Dubizzle listings hourly from target Dubai neighbourhoods
2. Filters out businesses, agents, and property listings — only individual sellers
3. Extracts phone numbers from each listing (bypassing canvas/SVG rendering)
4. Sends a personalised WhatsApp message to each seller automatically
5. Handles YES/NO replies and sends follow-ups if no response within 12 hours
6. Runs only within Dubai business hours (8am – 10pm, Asia/Dubai timezone)
7. Never contacts the same seller twice

**Live test result:**
```
Listing:   1960 Corvette in excellent condition for sale
Phone:     +971506504508 (extracted via JavaScript DOM)
AI clean:  "Corvette"
Message:   "Hi, is your Corvette still available for sale?"
Status:    Confirmed received ✅
```

---

## Architecture

```
Dubizzle Search Pages (hourly)
        |
  main_scraper.py
  [Playwright + UAE Proxy]
  [Business filter: verified flag, keywords, no-phone skip]
        |
   SQLite DB (n8n)
   status: pending_phone_extraction
        |
  phone_extractor.py
  [JavaScript DOM injection → phone number]
  [Gemini 2.5 Flash fallback for canvas/SVG renders]
  [Gemini AI product name cleaning]
        |
   Whapi WhatsApp API
   [Personalised message sent]
   [Seller marked as contacted — never messaged again]
        |
   n8n Workflows
   ├── Workflow 1: Hourly Monitor (runs both scripts)
   ├── Workflow 2: Reply Handler (YES → group invite / NO → declined)
   └── Workflow 3: Follow-up Scheduler (every 12h, max 3 follow-ups)
```

---

## Tech Stack

| Tool | Role |
|---|---|
| Python + Playwright | Headless Chromium scraping with anti-detection |
| DataImpulse Proxy | UAE residential IP — bypasses Dubizzle geo-blocks |
| Whapi | WhatsApp Business API (send + receive) |
| Gemini 2.5 Flash | Phone extraction from screenshots + product name cleaning |
| n8n Community Edition | Workflow orchestration, scheduling, data tables |
| SQLite | Listings DB, contacted sellers, URL management |
| Hostinger KVM1 VPS | Ubuntu 24.04, 24/7 uptime, Singapore region |

---

## Key Engineering Decisions

**Playwright over requests/BeautifulSoup**
Dubizzle uses JavaScript rendering and Incapsula bot protection. Playwright runs a real Chromium browser with anti-detection scripts — requests look like a real user session.

**UAE residential proxy**
Dubizzle restricts access by geography. DataImpulse routes all traffic through a real Dubai IP, bypassing geo-blocks and reducing bot detection risk.

**JavaScript DOM injection for phone extraction**
After clicking "Show Number", the phone briefly appears in the DOM before a login overlay renders. A 500ms JavaScript regex captures it — faster and more reliable than screenshot-based approaches.

**Gemini AI fallback**
Dubizzle renders phone numbers as canvas/SVG elements to block scraping. When JS extraction fails, Gemini 2.5 Flash reads a screenshot and extracts the number visually — more accurate than Tesseract OCR for this layout.

**n8n SQLite over Supabase**
Client wanted to avoid additional subscriptions. n8n's built-in data tables + direct Python SQLite access gave the same reliability at zero extra cost.

**Client-managed URL table**
Scraper target URLs live in an n8n data table the client controls directly from the UI. No code changes needed to add or remove neighbourhoods.

---

## Rate Limiting & Safety Rules

```
Max 10 WhatsApp messages per hour
Active hours: 8am – 10pm Dubai time only (Asia/Dubai timezone)
Duplicate prevention: contacted_sellers table — never messages same phone twice
Listing deduplication: listing_id checked on every scrape run
All Dubizzle traffic routed through DataImpulse UAE proxy — no exceptions
Max 3 follow-ups per seller before marking as expired
```

---

## Database Schema

**listings**
```
listing_id | name | price | url | phone
status     | follow_up_count | last_followup | created_at
```
Status values: `pending_phone_extraction` → `messaged` → `declined` / `expired`

**contacted_sellers**
```
phone | listing_id | contacted_at
```

**scraper_urls**
```
url | active
```
Client manages this table directly from n8n UI.

---

## n8n Workflows

**Workflow 1 — Dubizzle Monitor**
Runs every hour. Executes `main_scraper.py` then `phone_extractor.py` in sequence.
Error handler sends a WhatsApp alert via Whapi if the workflow crashes.

**Workflow 2 — Reply Handler**
Webhook-triggered on incoming WhatsApp replies.
- YES → asks seller to list on buy/sell group
- NO → marks listing as declined
- Unknown → logged for manual review

**Workflow 3 — Follow-up Scheduler**
Runs every 12 hours. Sends follow-up to no-reply listings (max 3 attempts).
Increments follow-up counter. Marks listing as expired after 3 unanswered messages.

---

## Delivered to Client

- Full VPS setup (Hostinger, Ubuntu 24.04, Singapore)
- DataImpulse UAE proxy configured and tested
- Dubizzle scraper with multi-layer business filter
- Phone extraction via JS DOM injection + Gemini AI fallback
- Gemini AI product name cleaning
- WhatsApp messaging via Whapi — live tested and confirmed received
- Duplicate prevention across full pipeline
- Rate limiting (max 10/hr, business hours only)
- n8n Community Edition installed and all 3 workflows built
- Client-managed URL table — no code changes needed for new neighbourhoods
- End-to-end pipeline tested with real Dubizzle listing

---

## Stack Summary

`Python` `Playwright` `n8n` `SQLite` `Gemini 2.5 Flash` `Whapi` `OpenAI-compatible APIs` `REST APIs` `VPS / Linux` `Automated Workflows` `Web Scraping` `WhatsApp Automation`
