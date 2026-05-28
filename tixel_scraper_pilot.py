from playwright.sync_api import sync_playwright
import requests
import time

# === YOUR SETTINGS — EDIT THESE ===
EVENTS = [
    {
        "name": "Olivia Dean – Melbourne Night 1",
        "url": "https://tixel.com/au/music-tickets/2026/10/05/olivia-dean-rod-laver-arena-melb",
    },
    {
        "name": "Olivia Dean – Melbourne Night 2",
        "url": "https://tixel.com/au/music-tickets/2026/10/06/olivia-dean-rod-laver-arena-melb",
    },
    {
        "name": "Olivia Dean – Sydney Night 1",
        "url": "https://tixel.com/au/music-tickets/2026/10/09/olivia-dean-qudos-bank-arena-syd",
    },
    {
        "name": "Olivia Dean – Sydney Night 2",
        "url": "https://tixel.com/au/music-tickets/2026/10/10/olivia-dean-qudos-bank-arena-syd",
    },
]

CHECK_INTERVAL_SECONDS = 20
# ==================================

token_file_path = 'keys/telegram_token.txt'
chat_id_file_path = 'keys/telegram_chat_id.txt'

with open(token_file_path, 'r') as file:
    token = file.read().strip()

with open(chat_id_file_path, 'r') as file:
    chat_id = file.read().strip()


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{token}/sendMessage?chat_id={chat_id}&text={message}"
    try:
        response = requests.get(url)
        result = response.json()
        if result.get("ok"):
            print("  ✅ Telegram notification sent.")
        else:
            print(f"  ⚠️ Telegram error: {result}")
    except Exception as e:
        print(f"  ❌ Failed to send notification: {e}")


def check_event(page, event):
    """Returns list of ticket descriptions found, or empty list if none."""
    try:
        page.goto(event["url"])
        page.wait_for_load_state("load")
        time.sleep(3)  # Let JS render fully

        buttons = page.query_selector_all("button")
        tickets_found = []

        for btn in buttons:
            text = btn.inner_text().strip()
            # Ticket listing buttons contain a '$' price — that's our signal
            if "$" in text and "Face Value" not in text:
                tickets_found.append(text)

        return tickets_found

    except Exception as e:
        print(f"  ❌ Error loading page: {e}")
        return []


def run_continuously():
    print("🔍 Tixel scraper started — checking all Olivia Dean events every 20 seconds...")
    print("Press Ctrl+C to stop.\n")

    # Track which events we've already notified about to avoid spam
    notified_events = set()

    while True:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            for event in EVENTS:
                print(f"Checking: {event['name']}...")
                tickets = check_event(page, event)

                if tickets:
                    print(f"  🎟️  {len(tickets)} ticket(s) found!")
                    for t in tickets:
                        print(f"    → {t}")

                    # Build a clean notification message
                    ticket_list = "\n".join(f"• {t}" for t in tickets)
                    message = (
                        f"🎟️ TICKETS AVAILABLE!\n"
                        f"{event['name']}\n\n"
                        f"{ticket_list}\n\n"
                        f"👉 Buy now: {event['url']}"
                    )

                    # Only notify if this is a new batch (avoid re-notifying every 20s)
                    ticket_signature = "|".join(sorted(tickets))
                    event_key = f"{event['name']}:{ticket_signature}"

                    if event_key not in notified_events:
                        send_telegram_message(message)
                        notified_events.add(event_key)
                    else:
                        print("  (Already notified about these exact tickets — skipping.)")

                else:
                    print("  No tickets listed yet.")
                    # Clear any old notification memory for this event
                    # so we notify fresh when new tickets appear
                    keys_to_remove = {k for k in notified_events if k.startswith(event['name'])}
                    notified_events -= keys_to_remove

                time.sleep(2)  # Small pause between events

            browser.close()

        print(f"\nSleeping {CHECK_INTERVAL_SECONDS}s before next check...\n")
        time.sleep(CHECK_INTERVAL_SECONDS)


run_continuously()