"""Temporary: find a browser setup the Ticketek Marketplace accepts from GitHub Actions."""
from playwright.sync_api import sync_playwright
import requests
import time

URLS = [
    "https://marketplace.ticketek.com.au/purchase/searchlist/products?keyword=Olivia%20Dean&content_id=OLYBTHB26",
    "https://marketplace.ticketek.com.au/purchase/searchlist/products?content_id=WASFSECG26",
    "https://tixel.com/au/music-tickets/2026/10/09/olivia-dean-qudos-bank-arena-syd",
]
LINUX_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"

print("=== plain requests ===")
for url in URLS[:1]:
    try:
        r = requests.get(url, headers={"User-Agent": LINUX_UA.format(major=145), "Accept-Language": "en-AU"}, timeout=20)
        print(r.status_code, len(r.text), " ".join(r.text.split())[:300])
    except Exception as e:
        print("error", e)

with sync_playwright() as p:
    for channel in (None, "chromium"):
        for custom_ua in (False, True):
            label = f"channel={channel or 'headless-shell'} custom_ua={custom_ua}"
            print(f"\n=== {label} ===")
            try:
                browser = p.chromium.launch(headless=True, channel=channel)
            except Exception as e:
                print("launch failed:", e)
                continue
            kwargs = dict(locale="en-AU", timezone_id="Australia/Sydney")
            if custom_ua:
                kwargs["user_agent"] = LINUX_UA.format(major=browser.version.split(".")[0])
            context = browser.new_context(**kwargs)
            for url in URLS:
                page = context.new_page()
                first = {}
                page.on("request", lambda req: first.setdefault("h", req.headers) if req.resource_type == "document" else None)
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(6)
                    text = " ".join(page.inner_text("body").split())
                    buttons = [b.inner_text() for b in page.query_selector_all("button") if "$" in b.inner_text()]
                    print(f"{url[:70]} -> HTTP {resp.status if resp else None}, title {page.title()!r}, final {page.url[:80]}")
                    print(f"   text: {text[:700]!r}")
                    print(f"   $-buttons: {len(buttons)}")
                except Exception as e:
                    print(f"{url[:70]} -> ERROR {str(e).splitlines()[0]}")
                h = first.get("h", {})
                print(f"   sent UA: {h.get('user-agent')}\n   sent sec-ch-ua: {h.get('sec-ch-ua')}")
                page.close()
            browser.close()
