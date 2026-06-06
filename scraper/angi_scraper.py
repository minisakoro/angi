import base64
import os
import random
import re
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup

# ✅ همه شهرهای اوهایو
OHIO_CITIES = {
    "columbus":     "columbus-oh-us-probr0-bo~t_11819~r_4509177",
    "cleveland":    "cleveland-oh-us-probr0-bo~t_11819~r_4509177",
    "cincinnati":   "cincinnati-oh-us-probr0-bo~t_11819~r_4509177",
    "toledo":       "toledo-oh-us-probr0-bo~t_11819~r_4509177",
    "akron":        "akron-oh-us-probr0-bo~t_11819~r_4509177",
    "dayton":       "dayton-oh-us-probr0-bo~t_11819~r_4509177",
    "youngstown":   "youngstown-oh-us-probr0-bo~t_11819~r_4509177",
    "canton":       "canton-oh-us-probr0-bo~t_11819~r_4509177",
    "lorain":       "lorain-oh-us-probr0-bo~t_11819~r_4509177",
    "hamilton":     "hamilton-oh-us-probr0-bo~t_11819~r_4509177",
    "springfield":  "springfield-oh-us-probr0-bo~t_11819~r_4509177",
    "kettering":    "kettering-oh-us-probr0-bo~t_11819~r_4509177",
    "elyria":       "elyria-oh-us-probr0-bo~t_11819~r_4509177",
    "parma":        "parma-oh-us-probr0-bo~t_11819~r_4509177",
    "newark":       "newark-oh-us-probr0-bo~t_11819~r_4509177",
    "mentor":       "mentor-oh-us-probr0-bo~t_11819~r_4509177",
    "mansfield":    "mansfield-oh-us-probr0-bo~t_11819~r_4509177",
    "zanesville":   "zanesville-oh-us-probr0-bo~t_11819~r_4509177",
    "middletown":   "middletown-oh-us-probr0-bo~t_11819~r_4509177",
    "lima":         "lima-oh-us-probr0-bo~t_11819~r_4509177",
}

# اگه env variable داده شده، فقط اون شهر — وگرنه همه
SINGLE_CITY = os.environ.get("CITY", "").strip().lower()
CITIES_TO_SCRAPE = {SINGLE_CITY: OHIO_CITIES[SINGLE_CITY]} if SINGLE_CITY and SINGLE_CITY in OHIO_CITIES else OHIO_CITIES

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
                print(f"  Status: {resp.status_code} | {resp.url}")
                if resp.status_code == 200:
                    return resp.text
                elif resp.status_code == 403:
                    print(f"  [WARN] 403 Blocked on attempt {attempt}")
        except Exception as e:
            print(f"  [WARN] Attempt {attempt} failed: {e}")
        time.sleep(RETRY_DELAY * attempt)
    return None


def parse_professionals(html: str, city: str) -> list[dict]:
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
            "location": city.title() + ", OH",
            "profileUrl": profile_url,
            "source": "houzz",
            "city": city.title(),
            "state": "OH",
        })

    return results


def scrape_one_city(city: str, slug: str) -> list[dict]:
    all_pros = []
    for page in range(1, 20):
        url = BASE_URL.format(slug=slug)
        if page > 1:
            url += f"?fi={(page - 1) * 15}"

        print(f"  Page {page}: {url}")
        html = fetch_page(url)
        if not html:
            print(f"  [WARN] Failed page {page}, stopping {city}")
            break

        pros = parse_professionals(html, city)
        if not pros:
            print(f"  [INFO] No results on page {page}, done with {city}")
            break

        all_pros.extend(pros)
        print(f"  Found {len(pros)} | total: {len(all_pros)}")
        time.sleep(random.uniform(2.0, 4.5))

    return all_pros


def send_to_webhook(df: pd.DataFrame, city: str) -> None:
    webhook_url = os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        return

    csv_b64 = base64.b64encode(df.to_csv(index=False).encode()).decode()
    payload = {
        "city": city,
        "data": csv_b64,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
    }
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=30)
        print(f"  [WEBHOOK] {city} → {resp.status_code}")
    except Exception as e:
        print(f"  [ERROR] Webhook failed for {city}: {e}")


def main():
    print(f"[START] Scraping {len(CITIES_TO_SCRAPE)} city/cities in Ohio")
    print(f"  Cities: {', '.join(CITIES_TO_SCRAPE.keys())}\n")

    all_results = []

    for city, slug in CITIES_TO_SCRAPE.items():
        print(f"\n{'='*50}")
        print(f"[CITY] {city.upper()}")
        print(f"{'='*50}")

        pros = scrape_one_city(city, slug)
        if not pros:
            print(f"  [WARN] No data for {city}")
            continue

        df_city = pd.DataFrame(pros)
        df_city["is_new_roofer"] = df_city["reviewCount"].fillna(0).astype(float) <= 10

        # ذخیره CSV جداگانه برای هر شهر
        df_city.to_csv(RESULTS_DIR / f"all_{city}_roofing.csv", index=False)
        df_city[df_city["is_new_roofer"]].to_csv(RESULTS_DIR / f"new_roofers_{city}.csv", index=False)

        new_count = int(df_city["is_new_roofer"].sum())
        print(f"  [DONE] {city}: {len(df_city)} total | {new_count} new roofers")

        # ارسال webhook برای هر شهر جداگانه
        send_to_webhook(df_city, city)

        all_results.append(df_city)

        # pause بین شهرها تا block نشیم
        if city != list(CITIES_TO_SCRAPE.keys())[-1]:
            wait = random.uniform(8, 15)
            print(f"  [PAUSE] Waiting {wait:.1f}s before next city...")
            time.sleep(wait)

    # ذخیره یه فایل کلی از همه شهرها
    if all_results:
        df_all = pd.concat(all_results, ignore_index=True)
        df_all.to_csv(RESULTS_DIR / "all_ohio_roofing.csv", index=False)
        df_all[df_all["is_new_roofer"]].to_csv(RESULTS_DIR / "new_roofers_ohio_ALL.csv", index=False)

        total = len(df_all)
        new_total = int(df_all["is_new_roofer"].sum())
        print(f"\n{'='*50}")
        print(f"[FINAL] Ohio Total: {total} | New roofers: {new_total}")
        print(f"  Files saved to: {RESULTS_DIR}/")
        print(f"{'='*50}")
    else:
        print("[WARN] No data collected from any city")
        sys.exit(0)


if __name__ == "__main__":
    main()
