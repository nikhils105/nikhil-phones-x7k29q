#!/usr/bin/env python3
"""
Phone price tracker (Amazon.in + Flipkart). Alerts ONLY on price drops, via ntfy push.
Runs on GitHub Actions every 10 min; checks every run during the sale window,
and roughly once an hour otherwise. History is saved in prices.csv.
"""
import csv
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")  # stored as a GitHub secret
CSV_FILE = "prices.csv"
DIP_PERCENT = 2.0  # alert when price falls by at least this % since last check

IST = timezone(timedelta(hours=5, minutes=30))
# Check every run (10 min) inside this window; hourly outside it.
SALE_START = datetime(2026, 10, 7, 0, 0, tzinfo=IST)
SALE_END = datetime(2026, 10, 20, 23, 59, tzinfo=IST)

PRODUCTS = [
    {"name": "iPhone 17 256GB (Flipkart)", "url": "PASTE_URL", "target": 75000},
    {"name": "iPhone 17 256GB (Amazon)", "url": "PASTE_URL", "target": 75000},
    {"name": "Galaxy S25 Ultra 256GB (Flipkart)", "url": "PASTE_URL", "target": 80000},
    {"name": "Galaxy S25 Ultra 256GB (Amazon)", "url": "PASTE_URL", "target": 80000},
    {"name": "Galaxy S25 256GB", "url": "PASTE_URL", "target": 60000},
    {"name": "Pixel 11 256GB", "url": "PASTE_URL", "target": 75000},
    {"name": "OnePlus 15 256GB", "url": "PASTE_URL", "target": 65000},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
}


def get_price(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}")
        return None
    soup = BeautifulSoup(r.text, "html.parser")

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        for item in data if isinstance(data, list) else [data]:
            offers = item.get("offers") if isinstance(item, dict) else None
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict) and offers.get("price"):
                try:
                    return int(float(str(offers["price"]).replace(",", "")))
                except ValueError:
                    pass

    el = soup.select_one("span.a-price span.a-offscreen")
    if el:
        digits = re.sub(r"[^\d]", "", el.get_text().split(".")[0])
        if digits:
            return int(digits)

    for m in re.finditer(r"₹\s?([\d,]{5,9})", r.text):
        val = int(m.group(1).replace(",", ""))
        if 15000 <= val <= 250000:
            return val
    return None


def notify(title, body, url):
    print(f"ALERT: {title} | {body}")
    if not NTFY_TOPIC:
        print("  NTFY_TOPIC not set, skipping push")
        return
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={"Title": title, "Click": url, "Priority": "high", "Tags": "rotating_light"},
            timeout=15,
        )
    except Exception as e:
        print("  ntfy failed:", e)


def last_prices():
    last = {}
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, newline="") as f:
            for row in csv.reader(f):
                last[row[1]] = int(row[3])
    return last


def save(name, url, price):
    with open(CSV_FILE, "a", newline="") as f:
        csv.writer(f).writerow([name, url, datetime.now(IST).isoformat(timespec="minutes"), price])


def should_run_now():
    now = datetime.now(IST)
    if SALE_START <= now <= SALE_END:
        return True
    return now.minute < 10  # off-sale: about once an hour


def main():
    if "--scheduled" in sys.argv and not should_run_now():
        print("Off-sale hour slot, skipping this run")
        return
    last = last_prices()
    for p in PRODUCTS:
        if "PASTE" in p["url"]:
            continue
        print(f"Checking {p['name']}")
        try:
            price = get_price(p["url"])
        except Exception as e:
            print("  error:", e)
            price = None
        if price is None:
            print("  could not read price (blocked or layout changed)")
            continue

        prev = last.get(p["url"])
        save(p["name"], p["url"], price)
        print(f"  Rs {price:,} (prev {prev})")

        if prev is not None and price < prev:  # drops only, never rises
            crossed_target = price <= p["target"] < prev
            big_dip = price <= prev * (1 - DIP_PERCENT / 100)
            if crossed_target:
                notify("TARGET HIT: " + p["name"], f"Now Rs {price:,} (was Rs {prev:,})", p["url"])
            elif big_dip:
                notify("Price drop: " + p["name"], f"Rs {prev:,} -> Rs {price:,}", p["url"])
        time.sleep(random.uniform(3, 7))


if __name__ == "__main__":
    main()
