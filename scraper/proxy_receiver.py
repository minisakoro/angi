import base64
import io
import json
import os
import sys
from pathlib import Path

import pandas as pd

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)


def decode_csv_payload(payload: dict) -> pd.DataFrame:
    csv_b64 = payload.get("data", "")
    city = payload.get("city", "unknown")
    decoded = base64.b64decode(csv_b64).decode("utf-8")
    df = pd.read_csv(io.StringIO(decoded))
    df["source_city"] = city
    return df


def deduplicate(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop_duplicates(subset=["businessName", "phoneNumber"], keep="first")


def merge_masters(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    master_path = RESULTS_DIR / "ohio_all_cities_master.csv"
    new_roofer_path = RESULTS_DIR / "ohio_new_roofers_master.csv"

    if master_path.exists():
        existing = pd.read_csv(master_path)
        combined = pd.concat([existing, df], ignore_index=True)
        combined = deduplicate(combined)
    else:
        combined = deduplicate(df)

    combined = combined.reset_index(drop=True)
    new_roofers = combined[combined["is_new_roofer"] == True].reset_index(drop=True)

    combined.to_csv(master_path, index=False)
    new_roofers.to_csv(new_roofer_path, index=False)

    return combined, new_roofers


def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not input_path:
        print("Usage: python proxy_receiver.py <webhook_payload.json>")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    df = decode_csv_payload(payload)
    print(f"Decoded {len(df)} records for city: {payload.get('city')}")

    all_df, new_df = merge_masters(df)
    print(f"Master now has {len(all_df)} total unique contractors")
    print(f"New roofers master has {len(new_df)} records")


if __name__ == "__main__":
    main()
