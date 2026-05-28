from playwright.sync_api import sync_playwright
import time

URLS = [
    "https://tixel.com/au/music-tickets/2026/10/05/olivia-dean-rod-laver-arena-melb",
    "https://tixel.com/au/music-tickets/2026/10/09/olivia-dean-qudos-bank-arena-syd",
    "https://tixel.com/au/music-tickets/2026/04/29/mumford-sons-qudos-bank-arena-sy",
]

def check_buttons(url):
    print(f"\n{'='*60}")
    print(f"Checking: {url}")
    print('='*60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headless=False so you can SEE the page
        page = browser.new_page()
        page.goto(url)
        page.wait_for_load_state("load")
        time.sleep(3)  # Give JS a moment to fully render
        
        # Find all buttons on the page and print their text
        buttons = page.query_selector_all("button")
        print(f"Found {len(buttons)} buttons. Their text:")
        for i, btn in enumerate(buttons):
            text = btn.inner_text().strip()
            if text:  # Only print buttons that have text
                print(f"  [{i}] '{text}'")
        
        input("Press Enter to close the browser and continue...")
        browser.close()

for url in URLS:
    check_buttons(url)