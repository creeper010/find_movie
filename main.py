import os
import re
import sys
from datetime import datetime, timezone

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Watch for these terms. Add/remove variants as needed.
MOVIE_TERMS = [
    term.strip().lower()
    for term in os.getenv(
        "MOVIE_TERMS",
        "The Super Mario Galaxy Movie|The Amazing Digital Circus: The Last Act|TADC",
    ).split("|")
    if term.strip()
]

# Watch ODEON’s public pages. Add a specific cinema page if you have one.
URLS = [
    url.strip()
    for url in os.getenv(
        "ODEON_URLS",
        "https://www.odeon.co.uk/|https://www.odeon.co.uk/films/",
    ).split("|")
    if url.strip()
]

# Phrases that usually mean tickets are live.
SALE_TERMS = [
    "book now",
    "book tickets",
    "buy tickets",
    "tickets available",
    "tickets on sale",
    "on sale now",
    "pre-book now",
    "pre-book",
    "presale",
    "pre-sale",
]

WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()
EXIT_ON_ALERT = os.getenv("EXIT_ON_ALERT", "1").strip() == "1"

def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()

def find_snippets(text: str, terms: list[str], max_hits: int = 6) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    hits = []
    for line in lines:
        low = line.lower()
        if any(term in low for term in terms):
            hits.append(line[:220])
            if len(hits) >= max_hits:
                break
    return hits

def send_webhook(message: str) -> None:
    if not WEBHOOK_URL:
        return
    try:
        requests.post(WEBHOOK_URL, json={"content": message}, timeout=15)
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")

def check_url(page, url: str) -> dict:
    result = {
        "url": url,
        "movie_hits": [],
        "sale_hits": [],
        "title": "",
    }

    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:
        pass

    result["title"] = page.title() or ""
    body_text = page.locator("body").inner_text(timeout=20000)
    text = norm(body_text)

    result["movie_hits"] = [term for term in MOVIE_TERMS if term in text]
    result["sale_hits"] = [term for term in SALE_TERMS if term in text]

    result["movie_snips"] = find_snippets(body_text, MOVIE_TERMS)
    result["sale_snips"] = find_snippets(body_text, SALE_TERMS)

    return result

def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{stamp}] Starting ODEON check")
    print("Watching for:", " | ".join(MOVIE_TERMS))
    print("Pages:")
    for url in URLS:
        print(" -", url)

    any_movie = False
    any_sale = False
    details = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )

        for url in URLS:
            try:
                result = check_url(page, url)
                details.append(result)

                print(f"\n[{url}]")
                print(f"Title: {result['title'] or '(no title)'}")

                if result["movie_hits"]:
                    any_movie = True
                    print("Movie match:", ", ".join(result["movie_hits"]))
                else:
                    print("Movie match: none")

                if result["sale_hits"]:
                    any_sale = True
                    print("Sale wording:", ", ".join(result["sale_hits"]))
                else:
                    print("Sale wording: none")

                if result["movie_snips"]:
                    print("Movie snippets:")
                    for s in result["movie_snips"]:
                        print("  -", s)

                if result["sale_snips"]:
                    print("Sale snippets:")
                    for s in result["sale_snips"]:
                        print("  -", s)

            except Exception as e:
                print(f"[ERROR] {url} -> {e}")

        browser.close()

    print("\nSummary:")
    print("  Movie found:", any_movie)
    print("  Sale wording found:", any_sale)

    if any_movie and any_sale:
        msg = (
            "ALERT: ODEON page looks live for "
            + " / ".join(MOVIE_TERMS)
            + " — ticket-sale wording detected."
        )
        print("\n" + "=" * 72)
        print(msg)
        print("=" * 72 + "\n")
        send_webhook(msg)

        if EXIT_ON_ALERT:
            return 2

    return 0

if __name__ == "__main__":
    raise SystemExit(main())