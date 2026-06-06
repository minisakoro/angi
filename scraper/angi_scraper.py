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

CITY = os.environ.get("CITY", "columbus").lower()

CITY_SLUGS = {
    "columbus":   "columbus-oh-us-probr0-bo~t_11819~r_4509177",
    "cleveland":  "cleveland-oh-us-probr0-bo~t_11819~r_4509177",
    "cincinnati": "cincinnati-oh-us-probr0-bo~t_11819~r_4509177",
    "toledo":     "toledo-oh-us-probr0-bo~t_11819~r_4509177",
    "akron":      "akron-oh-us-probr0-bo~t_11819~r_4509177",
    "dayton":     "dayton-oh-us-probr0-bo~t_11819~r_4509177",
    "youngstown": "youngstown-oh-us-probr0-bo~t_11819~r_4509177",
}

BASE_URL = "https://www.houzz.com/professionals/roofing-and-gutter/{slug}"
RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}


def fetch_page(url: str) -> str | None:
    for attempt in range(1, 4):
        try:
            with httpx.Client(follow_redirects=True, timeout=30) as client:
                resp = client.get(url, headers=HEADERS)
                print(f"Status: {resp.status_code} | URL: {resp.url}")
                if resp.status_code == 200:
                    return resp.text
        except Exception as e:
            print(f"[WARN] Attempt {attempt} failed: {e}")
        time.sleep(5 * attempt)
    return None


def parse_professionals(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    results = []

    # لینک‌ها داخل li هستن با href به /professionals/roofing-and-gutters/ (با s)
    links = soup.find_all("a", href=re.compile(r"/professionals/roofing-and-gutters/[^/]+-pf~\d+"))

    seen_urls = set()
    for a in links:
        href = a.get("href", "")
        # normalize: هر دو فرمت hznb و مستقیم
        clean_href = href.replace("/hznb/", "/")
        if clean_href in seen_urls:
            continue
        seen_urls.add(clean_href)

        full_text = a.get_text("\n", strip=True)
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]

        if not lines:
            continue

        name = lines[0]
        if len(name) < 3:
            continue

        # review count
        review_count = None
        joined = " ".join(lines)
        m = re.search(r'(\d+)\s+Review', joined, re.IGNORECASE)
        if m:
            review_count = int(m.group(1))

        # آدرس — خط آخری که OH داره
        address = None
        for line in reversed(lines):
            if ", OH" in line or "Ohio" in line:
                address = line
                break

        profile_url = "https://www.houzz.com" + clean_href if clean_href.startswith("/") else clean_href

        results.append({
            "businessName": name,
            "phoneNumber": None,
            "reviewCount": review_count,
            "address": address,
            "location": CITY.title() + ", OH",
            "profileUrl": profile_url,
            "source": "houzz",
            "city": CITY.title(),
            "state": "OH",
        })

    print(f"  → parsed {len(results)} profiles from page")
    return results


def scrape_city() -> list[dict]:
    slug = CITY_SLUGS.get(CITY)
    if not slug:
        print(f"[ERROR] No slug for city: {CITY}")
        return []

    all_pros = []
    for page in range(1, 25):
        offset = (page - 1) * 15
        url = BASE_URL.format(slug=slug) + (f"?fi={offset}" if page > 1 else "")

        print(f"Fetching page {page} for {CITY}: {url}")
        html = fetch_page(url)
        if not html:
            print(f"[WARN] Failed page {page}, stopping")
            break

        pros = parse_professionals(html)
        if not pros:
            print(f"[INFO] No results on page {page}, stopping")
            break

        existing_urls = {p["profileUrl"] for p in all_pros}
        new_pros = [p for p in pros if p["profileUrl"] not in existing_urls]

        if not new_pros:
            print(f"[INFO] All duplicates on page {page}, stopping")
            break

        all_pros.extend(new_pros)
        print(f"[INFO] +{len(new_pros)} new | total: {len(all_pros)}")
        time.sleep(random.uniform(2.0, 4.0))

    return all_pros


def save_and_send(providers: list[dict]) -> None:
    df = pd.DataFrame(providers)
    df["is_new_roofer"] = df["reviewCount"].apply(
        lambda x: True if (
            x is None or x == "" or
            (str(x).replace(".", "").isdigit() and float(x) <= 10)
        ) else False
    )

    RESULTS_DIR.mkdir(exist_ok=True)
    df.to_csv(RESULTS_DIR / f"all_{CITY}_roofing.csv", index=False)
    df[df["is_new_roofer"]].to_csv(RESULTS_DIR / f"new_roofers_{CITY}.csv", index=False)

    total = len(df)
    new_count = int(df["is_new_roofer"].sum())
    print(f"[DONE] Total: {total} | New roofers (<=10 reviews): {new_count}")

    webhook_url = os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        print("[INFO] No WEBHOOK_URL, skipping")
        return

    records = df.where(pd.notnull(df), None).to_dict(orient="records")
    payload = {
        "city": CITY,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "total": total,
        "records": records,
    }
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=60)
        print(f"[DONE] Webhook: {resp.status_code}")
    except Exception as e:
        print(f"[ERROR] Webhook failed: {e}")


def main():
    print(f"[START] Houzz scraper for {CITY.title()}, OH")
    providers = scrape_city()
    if not providers:
        print("[WARN] No data collected")
        sys.exit(0)
    save_and_send(providers)


if __name__ == "__main__":
    main()
