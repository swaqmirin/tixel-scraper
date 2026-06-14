from playwright.sync_api import sync_playwright
import requests
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

EVENTS = [
    {
        "name": "Olivia Dean - Melbourne Night 1",
        "url": "https://tixel.com/au/music-tickets/2026/10/05/olivia-dean-rod-laver-arena-melb",
    },
    {
        "name": "Olivia Dean - Melbourne Night 2",
        "url": "https://tixel.com/au/music-tickets/2026/10/06/olivia-dean-rod-laver-arena-melb",
    },
    {
        "name": "Olivia Dean - Sydney Night 1",
        "url": "https://tixel.com/au/music-tickets/2026/10/09/olivia-dean-qudos-bank-arena-syd",
    },
    {
        "name": "Olivia Dean - Sydney Night 2",
        "url": "https://tixel.com/au/music-tickets/2026/10/10/olivia-dean-qudos-bank-arena-syd",
    },
]

SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def is_active_time():
    now = datetime.now(SYDNEY_TZ)
    t = now.hour * 60 + now.minute
    in_main_window = t >= 6 * 60 + 30 or t < 120  # 6:30am to 2:00am Sydney time
    in_4am_window = 4 * 60 <= t < 4 * 60 + 5     # one check at 4:00am
    return in_main_window or in_4am_window


def get_credentials():
    token = os.environ.get("TELEGRAM_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token:
        with open("keys/telegram_token.txt") as f:
            token = f.read().strip()
    if not chat_id:
        with open("keys/telegram_chat_id.txt") as f:
            chat_id = f.read().strip()
    return token, chat_id


def send_telegram_message(token, chat_id, message):
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message},
        )
        result = response.json()
        if result.get("ok"):
            print("  Telegram notification sent.")
        else:
            print(f"  Telegram error: {result}")
    except Exception as e:
        print(f"  Failed to send notification: {e}")


def check_event(page, event):
    try:
        page.goto(event["url"])
        page.wait_for_load_state("load")
        time.sleep(3)
        buttons = page.query_selector_all("button")
        return [
            btn.inner_text().strip()
            for btn in buttons
            if "$" in btn.inner_text() and "Face Value" not in btn.inner_text()
        ]
    except Exception as e:
        print(f"  Error loading page: {e}")
        return []


def main():
    test_mode = os.environ.get("TEST_MODE") == "true"
    test_url = os.environ.get("TEST_URL")

    events = EVENTS
    if test_url:
        events = [{"name": "Test event", "url": test_url}]
        test_mode = True

    if not test_mode and not is_active_time():
        now = datetime.now(SYDNEY_TZ)
        print(f"Outside active hours ({now.strftime('%H:%M %Z')}). Skipping.")
        sys.exit(0)

    token, chat_id = get_credentials()
    total_tickets_found = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for event in events:
            print(f"Checking: {event['name']}...")
            tickets = check_event(page, event)

            if tickets:
                total_tickets_found += len(tickets)
                print(f"  {len(tickets)} ticket(s) found!")
                for t in tickets:
                    print(f"    -> {t}")
                ticket_list = "\n".join(f"* {t}" for t in tickets)
                send_telegram_message(
                    token,
                    chat_id,
                    f"TICKETS AVAILABLE!\n{event['name']}\n\n{ticket_list}\n\nBuy now: {event['url']}",
                )
            else:
                print("  No tickets.")

            time.sleep(2)

        browser.close()

    if test_mode:
        send_telegram_message(
            token,
            chat_id,
            f"Test run complete. Checked {len(events)} event(s). Found {total_tickets_found} ticket(s). Scraper is configured correctly.",
        )


main()
