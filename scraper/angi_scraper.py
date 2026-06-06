import base64
import json
import os
import random
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup

CITY = os.environ.get("CITY", "columbus").lower()
BASE_URL = "https://www.angi.com/companylist/us/oh/{city}/roofing-contractors.htm"
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Referer": "https://www.google.com/",
    "Cache-Control": "max-age=0",
}

MAX_RETRIES = 3
RETRY_DELAY = 5


def fetch_page(client: httpx.Client, url: str) -> str | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = client.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
            if resp.status_code == 200:
                return resp.text
        except httpx.RequestError as e:
            print(f"[WARN] Attempt {attempt} failed for {url}: {e}")
        time.sleep(RETRY_DELAY)
    return None


def extract_from_next_data(html: str) -> list[dict] | None:
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        return None
    try:
        data = json.loads(script.string)
        providers = data.get("props", {}) \
            .get("pageProps", {}) \
            .get("apiResponse", {}) \
            .get("state", {}) \
            .get("directory", {}) \
            .get("providers", [])
        return providers if providers else None
    except (json.JSONDecodeError, AttributeError):
        return None


def extract_from_fallback(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(".provider-card")
    results = []
    for card in cards:
        name_tag = card.select_one("[data-qa='provider-name']") or card.select_one("h2")
        phone_tag = card.select_one("[data-qa='provider-phone']") or card.select_one(".phone")
        rating_tag = card.select_one("[data-qa='provider-rating']") or card.select_one(".rating")
        review_tag = card.select_one("[data-qa='provider-review-count']") or card.select_one(".review-count")
        years_tag = card.select_one("[data-qa='provider-years']") or card.select_one(".years")
        website_tag = card.select_one("a[href]")
        address_tag = card.select_one(".address") or card.select_one("[data-qa='provider-address']")

        results.append({
            "businessName": name_tag.get_text(strip=True) if name_tag else None,
            "phoneNumber": phone_tag.get_text(strip=True) if phone_tag else None,
            "overallStarRating": rating_tag.get_text(strip=True) if rating_tag else None,
            "reviewCount": _parse_int(review_tag.get_text()) if review_tag else None,
            "yearsInBusiness": _parse_int(years_tag.get_text()) if years_tag else None,
            "website": website_tag["href"] if website_tag else None,
            "address.streetAddress": address_tag.get_text(strip=True) if address_tag else None,
            "address.city": CITY.title(),
            "address.state": "OH",
            "address.zip": None,
            "licenseNumber": None,
            "serviceAreas": None,
        })
    return results


def _parse_int(text: str) -> int | None:
    try:
        return int("".join(filter(str.isdigit, text)))
    except ValueError:
        return None


def normalize_provider(p: dict) -> dict:
    address = p.get("address") or {}
    return {
        "businessName": p.get("businessName"),
        "phoneNumber": p.get("phoneNumber"),
        "overallStarRating": p.get("overallStarRating"),
        "reviewCount": p.get("reviewCount"),
        "yearsInBusiness": p.get("yearsInBusiness"),
        "website": p.get("website"),
        "address.streetAddress": address.get("streetAddress"),
        "address.city": address.get("city") or CITY.title(),
        "address.state": address.get("state") or "OH",
        "address.zip": address.get("zip"),
        "licenseNumber": p.get("licenseNumber"),
        "serviceAreas": ", ".join(p.get("serviceAreas", [])) if isinstance(p.get("serviceAreas"), list) else p.get("serviceAreas"),
    }


def scrape_city(client: httpx.Client) -> tuple[list[dict], int]:
    all_providers: list[dict] = []
    pages_scraped = 0

    for page_num in range(1, 50):
        if page_num == 1:
            url = BASE_URL.format(city=CITY)
        else:
            url = f"{BASE_URL.format(city=CITY)}?page={page_num}"

        print(f"Fetching page {page_num} for {CITY}: {url}")
        html = fetch_page(client, url)
        if not html:
            print(f"[WARN] Failed to fetch page {page_num} after retries")
            break

        providers = extract_from_next_data(html)
        if providers is None:
            print("[INFO] __NEXT_DATA__ not found, trying fallback parser")
            providers = extract_from_fallback(html)

        if not providers:
            print(f"[INFO] No providers found on page {page_num}, stopping pagination")
            break

        normalized = [normalize_provider(p) for p in providers]
        all_providers.extend(normalized)
        pages_scraped += 1

        delay = random.uniform(1.5, 4.0)
        print(f"[INFO] Sleeping {delay:.2f}s before next page")
        time.sleep(delay)

    return all_providers, pages_scraped


def save_results(providers: list[dict], pages_scraped: int) -> None:
    df = pd.DataFrame(providers)
    df["is_new_roofer"] = (df["reviewCount"].fillna(0) <= 15) | (df["yearsInBusiness"].fillna(0) <= 3)

    all_path = RESULTS_DIR / f"all_{CITY}_roofing.csv"
    new_path = RESULTS_DIR / f"new_roofers_{CITY}.csv"

    df.to_csv(all_path, index=False)
    df[df["is_new_roofer"] == True].to_csv(new_path, index=False)

    print(f"[DONE] Saved {len(df)} total contractors to {all_path}")
    print(f"[DONE] Saved {df['is_new_roofer'].sum()} new roofers to {new_path}")
    print(f"[SUMMARY] City: {CITY.title()} | Pages scraped: {pages_scraped} | Total: {len(df)} | New roofers: {int(df['is_new_roofer'].sum())}")


def post_to_webhook(df: pd.DataFrame) -> None:
    webhook_url = os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        print("[INFO] WEBHOOK_URL not set, skipping POST")
        return

    csv_b64 = base64.b64encode(df.to_csv(index=False).encode("utf-8")).decode("utf-8")
    payload = {
        "city": CITY,
        "data": csv_b64,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
    }

    try:
        resp = httpx.post(webhook_url, json=payload, timeout=30)
        if resp.status_code == 200:
            print(f"[DONE] Posted results for {CITY} to webhook")
        else:
            print(f"[WARN] Webhook returned {resp.status_code}: {resp.text[:200]}")
    except httpx.RequestError as e:
        print(f"[ERROR] Failed to POST to webhook: {e}")


def main():
    if not CITY:
        print("[ERROR] CITY environment variable is required")
        sys.exit(1)

    print(f"[START] Scraping Angi roofing contractors for {CITY.title()}, OH")

    with httpx.Client(http2=True, limits=httpx.Limits(max_connections=10)) as client:
        providers, pages_scraped = scrape_city(client)

    if not providers:
        print("[ERROR] No providers scraped, exiting")
        sys.exit(1)

    save_results(providers, pages_scraped)

    df = pd.DataFrame(providers)
    df["is_new_roofer"] = (df["reviewCount"].fillna(0) <= 15) | (df["yearsInBusiness"].fillna(0) <= 3)
    post_to_webhook(df)


if __name__ == "__main__":
    main()
