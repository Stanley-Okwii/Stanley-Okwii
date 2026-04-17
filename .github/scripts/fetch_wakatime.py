#!/usr/bin/env python3
"""Fetch WakaTime stats and write a compact JSON for docs/index.html to consume."""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_BASE = "https://wakatime.com/api/v1/users/current"
ENDPOINTS = {
    "all_time": f"{API_BASE}/all_time_since_today",
    "last_7_days": f"{API_BASE}/stats/last_7_days",
    "last_30_days": f"{API_BASE}/stats/last_30_days",
}
OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "data" / "wakatime.json"

LANG_LIMIT = 10
EDITOR_LIMIT = 5
OS_LIMIT = 5

# WakaTime returns 202 while it warms the cache for long-range endpoints
# (particularly /all_time_since_today). Retry with short backoff.
RETRY_ATTEMPTS = 6
RETRY_SLEEP_SECONDS = 5


def get_json(url: str, auth_header: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": auth_header, "Accept": "application/json"})
    last_status = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        with urllib.request.urlopen(req, timeout=30) as resp:
            last_status = resp.status
            body = resp.read().decode("utf-8")
            if resp.status == 200:
                return json.loads(body)
            if resp.status == 202:
                print(
                    f"{url} returned 202 (cache warming), attempt {attempt}/{RETRY_ATTEMPTS}",
                    file=sys.stderr,
                )
                if attempt < RETRY_ATTEMPTS:
                    time.sleep(RETRY_SLEEP_SECONDS)
                    continue
                try:
                    parsed = json.loads(body)
                    if parsed.get("data"):
                        return parsed
                except ValueError:
                    pass
            raise RuntimeError(f"{url} returned HTTP {resp.status}")
    raise RuntimeError(f"{url} never returned 200 (last status {last_status})")


def pick(items: list, limit: int) -> list:
    out = []
    for item in items or []:
        if (item.get("total_seconds") or 0) <= 0:
            continue
        out.append({
            "name": item.get("name"),
            "percent": round(float(item.get("percent", 0.0)), 2),
            "human_readable": item.get("text", ""),
        })
        if len(out) >= limit:
            break
    return out


def project_window(data: dict) -> dict:
    return {
        "total_seconds": data.get("total_seconds", 0),
        "human_readable_total": data.get("human_readable_total", ""),
        "daily_average_seconds": data.get("daily_average", 0),
        "daily_average_human": data.get("human_readable_daily_average", ""),
        "languages": pick(data.get("languages", []), LANG_LIMIT),
        "editors": pick(data.get("editors", []), EDITOR_LIMIT),
        "operating_systems": pick(data.get("operating_systems", []), OS_LIMIT),
    }


def main() -> int:
    api_key = os.environ.get("WAKATIME_API_KEY")
    if not api_key:
        print("WAKATIME_API_KEY is not set", file=sys.stderr)
        return 2

    token = base64.b64encode(f"{api_key}:".encode()).decode()
    auth_header = f"Basic {token}"

    try:
        raw = {key: get_json(url, auth_header) for key, url in ENDPOINTS.items()}
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
        print(f"WakaTime API error: {exc}", file=sys.stderr)
        return 1

    all_time = raw["all_time"].get("data", {})
    week = raw["last_7_days"].get("data", {})
    month = raw["last_30_days"].get("data", {})

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "username": week.get("username") or month.get("username") or "",
        "all_time": {
            "total_seconds": all_time.get("total_seconds", 0),
            "human_readable": all_time.get("text", ""),
        },
        "last_7_days": project_window(week),
        "last_30_days": project_window(month),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
