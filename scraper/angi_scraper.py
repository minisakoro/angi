import base64
import json
import os
import random
import re
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup

CITY = os.environ.get("CITY", "columbus", "cleveland", "cincinnati", "toledo", "akron", "dayton", "youngstown"]).lower()

CITY_SLUGS = {
    "columbus": "columbus-oh-us-probr0-bo~t_11819~r_4509177",
    "cleveland": "cleveland-oh-us-probr0-bo~t_11819~r_4509177",
    "cincinnati": "cincinnati-oh-us-probr0-bo~t_11819~r_4509177",
    "toledo": "toledo-oh-us-probr0-bo~t_11819~r_4509177",
    "akron": "akron-oh-us-probr0-bo~t_11819~r_4509177",
    "dayton": "dayton-oh-us-probr0-bo~t_11819~r_4509177",
    "youngstown": "youngstown-oh-us-probr0-bo~t_11819~r_4509177",
}

BASE_URL = "https://www.houzz.com/professionals/roofing-and-gutter/{slug}"
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Referer": "https://www.google.com/",
}

MAX_RETRIES = 3
RETRY_DELAY = 5


def fetch_page(url: str) -> str | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with httpx.Client(http2=False, follow_redirects=True, timeout=30) as client:
                resp = client.get(url, headers=HEADERS)
                print(f"Status: {resp.status_code} | URL: {resp.url}")
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 403:
                    print(f"[WARN] 403 Blocked on attempt {attempt}")
        except Exception as e:
            print(f"[WARN] Attempt {attempt} failed: {e}")
        time.sleep(RETRY_DELAY * attempt)
    return None


def parse_professionals(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    cards = (
        soup.select("li[class*='hz-pro-search-result']") or
        soup.select("div[class*='hz-pro-search-result']") or
        soup.select("[data-component='ProCard']") or
        soup.select("li.hz-pro-results__item")
    )

    for card in cards:
        name_el = (
            card.select_one("h2[class*='hz-pro-title']") or
            card.select_one("[class*='pro-title']") or
            card.select_one("h2") or
            card.select_one("h3")
        )

        review_el = (
            card.select_one("[class*='hz-star-rating__label']") or
            card.select_one("[class*='reviews-count']") or
            card.select_one("[class*='review-count']")
        )

        link_el = (
            card.select_one("a[href*='/pro/']") or
            card.select_one("a[href*='professionals']") or
            card.select_one("a[href]")
        )

        review_count = None
        if review_el:
            nums = re.findall(r'\d+', review_el.get_text())
            review_count = int(nums[0]) if nums else None

        profile_url = None
        if link_el and link_el.get("href"):
            href = link_el["href"]
            profile_url = "https://www.houzz.com" + href if href.startswith("/") else href

        name_text = name_el.get_text(strip=True) if name_el else None

        if not name_text or name_text.replace('.', '').isdigit():
            continue

        results.append({
            "businessName": name_text,
            "phoneNumber": None,
            "reviewCount": review_count,
            "location": CITY.title() + ", OH",
            "profileUrl": profile_url,
            "source": "houzz",
            "city": CITY.title(),
            "state": "OH",
        })

    return results


def scrape_city() -> list[dict]:
    slug = CITY_SLUGS.get(CITY)
    if not slug:
        print(f"[ERROR] No slug for city: {CITY}")
        return []

    all_pros = []
    for page in range(1, 20):
        if page == 1:
            url = BASE_URL.format(slug=slug)
        else:
            url = BASE_URL.format(slug=slug) + f"?fi={((page - 1) * 15)}"

        print(f"Fetching page {page} for {CITY}: {url}")
        html = fetch_page(url)
        if not html:
            print(f"[WARN] Failed page {page}, stopping")
            break

        pros = parse_professionals(html)
        if not pros:
            print(f"[INFO] No results on page {page}, stopping")
            break

        all_pros.extend(pros)
        print(f"[INFO] Found {len(pros)} on page {page}, total: {len(all_pros)}")
        time.sleep(random.uniform(2.0, 4.5))

    return all_pros


def save_and_send(providers: list[dict]) -> None:
    df = pd.DataFrame(providers)
    df["is_new_roofer"] = df["reviewCount"].fillna(0).astype(float) <= 10

    all_path = RESULTS_DIR / f"all_{CITY}_roofing.csv"
    new_path = RESULTS_DIR / f"new_roofers_{CITY}.csv"
    df.to_csv(all_path, index=False)
    df[df["is_new_roofer"]].to_csv(new_path, index=False)

    print(f"[DONE] Total: {len(df)} | New roofers: {int(df['is_new_roofer'].sum())}")

    webhook_url = os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        print("[INFO] No WEBHOOK_URL, skipping")
        return

    csv_b64 = base64.b64encode(df.to_csv(index=False).encode()).decode()
    payload = {
        "city": CITY,
        "data": csv_b64,
        "run_id": os.environ.get("GITHUB_RUN_ID", "")
    }
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=30)
        print(f"[DONE] Webhook: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] Webhook failed: {e}")


def main():
    print(f"[START] Houzz scraper for {CITY.title()}, OH")
    providers = scrape_city()
    if not providers:
        print("[WARN] No data — Houzz may have blocked or changed structure")
        sys.exit(0)
    save_and_send(providers)


if __name__ == "__main__":
    main()
