# main.py
import os
import re
from datetime import datetime, timezone

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

MOVIE_TERMS = [
    term.strip().lower()
    for term in os.getenv(
        "MOVIE_TERMS",
        "The Amazing Digital Circus|The Amazing Digital Circus: The Last Act|TADC",
    ).split("|")
    if term.strip()
]

URLS = [
    url.strip()
    for url in os.getenv(
        "ODEON_URLS",
        "https://www.odeon.co.uk/odeon-scene/|https://www.odeon.co.uk/films/",
    ).split("|")
    if url.strip()
]

WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip()
EXIT_ON_ALERT = os.getenv("EXIT_ON_ALERT", "1").strip() == "1"

CLOUDFLARE_MARKERS = [
    "attention required! | cloudflare",
    "just a moment...",
    "cloudflare",
]

def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()

def snippets(text: str, terms: list[str], max_hits: int = 5) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    out = []
    for line in lines:
        low = line.lower()
        if any(term in low for term in terms):
            out.append(line[:220])
            if len(out) >= max_hits:
                break
    return out

def send_webhook1(message: str) -> None:
    if not WEBHOOK_URL:
        return
    try:
        requests.post(WEBHOOK_URL, json={
            "content": message,
            "allowed_mentions": {
                "parse": ["everyone"]
            }
        }, timeout=15)
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")

def send_webhook2(message: str) -> None:
    if not WEBHOOK_URL:
        return
    try:
        requests.post(WEBHOOK_URL, json={"content": message}, timeout=15)
    except Exception as e:
        print(f"[WEBHOOK ERROR] {e}")

def check_url(page, url: str) -> dict:
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:
        pass

    title = page.title() or ""
    body = page.locator("body").inner_text(timeout=20000)

    title_low = title.lower()
    body_low = norm(body)

    blocked = any(marker in title_low for marker in CLOUDFLARE_MARKERS) or any(
        marker in body_low for marker in CLOUDFLARE_MARKERS
    )

    hits = [term for term in MOVIE_TERMS if term in body_low]
    snips = snippets(body, MOVIE_TERMS)

    return {
        "url": url,
        "title": title,
        "blocked": blocked,
        "hits": hits,
        "snips": snips,
    }

def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n[{stamp}] Starting movie mention check")
    print("Watching for:", " | ".join(MOVIE_TERMS))
    print("Pages:")
    for url in URLS:
        print(" -", url)

    found_any = False
    blocked_any = False

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

                print(f"\n[{url}]")
                print(f"Title: {result['title'] or '(no title)'}")

                if result["blocked"]:
                    blocked_any = True
                    print("Blocked by Cloudflare or similar protection.")
                    continue

                if result["hits"]:
                    found_any = True
                    print("Movie mention found:", ", ".join(result["hits"]))
                    if result["snips"]:
                        print("Snippets:")
                        for s in result["snips"]:
                            print("  -", s)
                else:
                    print("Movie mention: none")

            except Exception as e:
                print(f"[ERROR] {url} -> {e}")

        browser.close()

    print("\nSummary:")
    print("  Movie found:", found_any)
    print("  Blocked pages:", blocked_any)

    if found_any:
        msg = "ALERT: ODEON page mentions the movie: " + " / ".join(MOVIE_TERMS)
        print("\n" + "=" * 72)
        print(msg)
        print("=" * 72 + "\n")
        send_webhook1(msg)
        if EXIT_ON_ALERT:
            return 0
    else:
        msg = "Nothing found for: " + " / ".join(MOVIE_TERMS)
        send_webhook2(msg)
        return 0

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
