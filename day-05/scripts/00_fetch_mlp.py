#!/usr/bin/env python3
"""
Day 5 (00): Fetch Mountain Legacy Project (MLP) station and location JSON records.

Fetches station metadata records for the surveyed stations (Bridgland 1914 stations 84..89
and duplicate nodes Wheeler 1915 stn 1099 and Avion Ridge stn 2413) from the public
Mountain Legacy Project Explorer API (https://explore.mountainlegacy.ca), then fetches
every modern visit location record referenced by those stations.

Outputs:
  $MC26_DAY05_DIR/mlp_locations/station_<id>.json
  $MC26_DAY05_DIR/mlp_locations/loc_<id>.json

Environment:
  MC26_DAY05_DIR   input data root directory (defaults to <repo_root>/../in if unset)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("MC26_DAY05_DIR", str(ROOT.parent / "in"))).resolve()
MLP_DIR = Path(os.environ.get("MC26_MLP_LOCATIONS_DIR", str(DATA_DIR / "mlp_locations"))).resolve()

BASE_URL = "https://explore.mountainlegacy.ca"
USER_AGENT = "mapchallenge2026-day05"
RATE_LIMIT_SEC = 1.0

# Station IDs used by 01_stations.py:
# Bridgland 1914 (84..89), Wheeler 1915 duplicate (1099), Avion Ridge duplicate (2413)
STATION_IDS = [2081, 1992, 2020, 2054, 2021, 2067, 1099, 2413]


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    MLP_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Target directory for MLP JSON records: {MLP_DIR}")

    location_ids = []

    # 1. Fetch station records
    for stn_id in STATION_IDS:
        stn_file = MLP_DIR / f"station_{stn_id}.json"
        if stn_file.exists():
            print(f"Station {stn_id}: already exists ({stn_file.name}), skipping download.")
            with open(stn_file, "r", encoding="utf-8") as f:
                sdata = json.load(f)
        else:
            url = f"{BASE_URL}/api/stations/show/{stn_id}"
            print(f"Fetching station {stn_id} from {url}...")
            try:
                sdata = fetch_json(url)
                with open(stn_file, "w", encoding="utf-8") as f:
                    json.dump(sdata, f, indent=2)
                print(f"  Saved {stn_file.name}")
                time.sleep(RATE_LIMIT_SEC)
            except Exception as e:
                print(f"  Error fetching station {stn_id}: {e}", file=sys.stderr)
                continue

        # Collect location IDs from station dependents -> modern_visits -> locations
        for dep in sdata.get("data", {}).get("dependents", []):
            if dep.get("type") == "modern_visits":
                for ldep in dep.get("dependents", []):
                    if ldep.get("type") == "locations":
                        lid = ldep.get("node", {}).get("id")
                        if lid and lid not in location_ids:
                            location_ids.append(lid)

    print(f"\nDiscovered {len(location_ids)} location records across all surveyed stations.")

    # 2. Fetch location records
    for lid in sorted(location_ids):
        loc_file = MLP_DIR / f"loc_{lid}.json"
        if loc_file.exists():
            print(f"Location {lid}: already exists ({loc_file.name}), skipping download.")
            continue

        url = f"{BASE_URL}/api/locations/show/{lid}"
        print(f"Fetching location {lid} from {url}...")
        try:
            ldata = fetch_json(url)
            with open(loc_file, "w", encoding="utf-8") as f:
                json.dump(ldata, f, indent=2)
            print(f"  Saved {loc_file.name}")
            time.sleep(RATE_LIMIT_SEC)
        except Exception as e:
            print(f"  Error fetching location {lid}: {e}", file=sys.stderr)

    print("\nFetch complete.")


if __name__ == "__main__":
    main()
