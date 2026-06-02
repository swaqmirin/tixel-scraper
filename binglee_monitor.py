import requests
import os
from datetime import datetime
from zoneinfo import ZoneInfo

BINGLEE_URL = "https://www.binglee.com.au/products/25k-laptop-pbank-100w-output-cy5128pbche"
PERTH_TZ = ZoneInfo("Australia/Perth")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}


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
    try:
        resp = requests.get(BINGLEE_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text.lower()
        print(f"  HTTP {resp.status_code}, page length: {len(html)} chars")

        in_stock = "backorder" not in html
        print(f"  'backorder' found: {not in_stock}")
        return in_stock, None
    except Exception as e:
        print(f"  Error fetching page: {e}")
        return None, str(e)


def main():
    now = datetime.now(PERTH_TZ)
    print(f"Bing Lee stock check — {now.strftime('%Y-%m-%d %H:%M %Z')}")

    token, chat_id = get_credentials()
    in_stock, error = check_binglee()

    if error:
        # Silent on transient errors — don't spam on network failures
        print(f"  Skipping notification due to error: {error}")
        return

    if in_stock:
        message = (
            "IN STOCK: Cygnett VertPwr 25000mAh power bank is now available at Bing Lee!\n\n"
            f"{BINGLEE_URL}\n\n"
            "Price match Harvey Norman now and click & collect before you leave Saturday."
        )
        send_telegram_message(token, chat_id, message)
        print("  IN STOCK — notification sent.")
    else:
        print("  Still showing backorder. No notification sent.")


if __name__ == "__main__":
    main()
