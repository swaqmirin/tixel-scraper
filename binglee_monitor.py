from playwright.sync_api import sync_playwright
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

BINGLEE_URL = "https://www.binglee.com.au/products/25k-laptop-pbank-100w-output-cy5128pbche"
PERTH_TZ = ZoneInfo("Australia/Perth")


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


def check_binglee():
    print(f"Fetching: {BINGLEE_URL}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(BINGLEE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            html = page.content().lower()
            print(f"  Page loaded, length: {len(html)} chars")

            has_backorder = "backorder" in html
            has_sold_out = "sold out" in html

            print(f"  'backorder' found: {has_backorder}")
            print(f"  'sold out' found: {has_sold_out}")

            if has_backorder:
                return "backorder", None
            elif has_sold_out:
                return "sold_out", None
            else:
                return "in_stock", None
        except Exception as e:
            print(f"  Error loading page: {e}")
            return None, str(e)
        finally:
            browser.close()


def main():
    now = datetime.now(PERTH_TZ)
    print(f"Bing Lee stock check — {now.strftime('%Y-%m-%d %H:%M %Z')}")

    token, chat_id = get_credentials()
    status, error = check_binglee()

    if error:
        # Notify on persistent errors so we know the monitor is broken
        send_telegram_message(
            token, chat_id,
            f"⚠️ Bing Lee monitor error — could not load page:\n{error}"
        )
        return

    if status == "in_stock":
        message = (
            "✅ IN STOCK: Cygnett VertPwr 25000mAh power bank is available at Bing Lee!\n\n"
            f"{BINGLEE_URL}\n\n"
            "Price match Harvey Norman and click & collect before Saturday."
        )
        send_telegram_message(token, chat_id, message)
        print("  IN STOCK — notification sent.")
    elif status == "sold_out":
        print("  Sold out. No notification sent.")
    else:
        print("  Still on backorder. No notification sent.")


if __name__ == "__main__":
    main()
