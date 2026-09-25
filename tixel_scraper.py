"""Olivia Dean resale monitor: Tixel + Ticketek Marketplace -> Telegram.

Run every few minutes by GitHub Actions (triggered from cron-job.org).
Each listing is announced once: what has already been announced is kept in
state.json, which the workflow carries from one run to the next using the
GitHub Actions cache.
"""
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import json
import os
import re
import time

import requests

SHOW_TZ = ZoneInfo("Australia/Sydney")  # Melbourne keeps the same clock

# Each show is checked until STOP_CHECKING_AT (local time) on the night of the show.
SHOWS = [
    {
        "name": "Olivia Dean - Sydney Night 1",
        "date": "2026-10-09",
        "tixel_url": "https://tixel.com/au/music-tickets/2026/10/09/olivia-dean-qudos-bank-arena-syd",
    },
    {
        "name": "Olivia Dean - Sydney Night 2",
        "date": "2026-10-10",
        "tixel_url": "https://tixel.com/au/music-tickets/2026/10/10/olivia-dean-qudos-bank-arena-syd",
    },
    {
        "name": "Olivia Dean - Melbourne Night 1",
        "date": "2026-10-05",
        "tixel_url": "https://tixel.com/au/music-tickets/2026/10/05/olivia-dean-rod-laver-arena-melb",
    },
    {
        "name": "Olivia Dean - Melbourne Night 2",
        "date": "2026-10-06",
        "tixel_url": "https://tixel.com/au/music-tickets/2026/10/06/olivia-dean-rod-laver-arena-melb",
    },
]
STOP_CHECKING_AT = "21:00"

# One page lists every Olivia Dean date on the Ticketek Marketplace.
TICKETEK_URL = "https://marketplace.ticketek.com.au/purchase/searchlist/products?keyword=Olivia%20Dean&content_id=OLYBTHB26"

# Tell the user if a site keeps failing to load for this long (e.g. it has started blocking us).
WARN_AFTER_FAILING_FOR = timedelta(minutes=30)

STATE_FILE = os.environ.get("STATE_FILE", "state.json")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"

# Ticketek rows look like "9 Oct Fri 4:00 PM / <venue> / None Available" or "... / 1 ticket left".
TICKETEK_ROW = re.compile(
    r"\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]* \d{1,2}:\d{2} ?[AP]M",
    re.IGNORECASE,
)
TICKETEK_LEFT = re.compile(r"(\d[\d,]*)\s+tickets?\s+left", re.IGNORECASE)
TICKETEK_NONE = re.compile(r"none available|sold out", re.IGNORECASE)


class CheckFailed(Exception):
    """The page didn't load properly, so we can't say whether there are tickets."""


def now():
    return datetime.now(SHOW_TZ)


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def show_is_over(show, at):
    stop = datetime.strptime(f"{show['date']} {STOP_CHECKING_AT}", "%Y-%m-%d %H:%M")
    return at >= stop.replace(tzinfo=SHOW_TZ)


def ticketek_label(show):
    """The date as Ticketek shows it, e.g. "9 Oct"."""
    d = datetime.strptime(show["date"], "%Y-%m-%d")
    return f"{d.day} {d:%b}"


# --- Telegram ---------------------------------------------------------------

class Telegram:
    def __init__(self, token, chat_id, prefix=""):
        self.token = token
        self.chat_id = chat_id
        self.prefix = prefix

    @classmethod
    def from_env(cls, prefix=""):
        token = os.environ.get("TELEGRAM_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not token:
            with open("keys/telegram_token.txt") as f:
                token = f.read().strip()
        if not chat_id:
            with open("keys/telegram_chat_id.txt") as f:
                chat_id = f.read().strip()
        return cls(token, chat_id, prefix)

    def send(self, message):
        """Returns True if Telegram accepted the message."""
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": (self.prefix + message)[:4000],
                    "link_preview_options": {"is_disabled": True},
                },
                timeout=20,
            )
            result = response.json()
        except Exception as e:
            print(f"  Failed to send Telegram message: {e}")
            return False
        if result.get("ok"):
            print("  Telegram message sent.")
            return True
        print(f"  Telegram error: {result}")
        return False


# --- State ------------------------------------------------------------------

def load_state():
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        print(f"Loaded state: {len(state.get('seen', {}))} Tixel listing(s) already announced.")
    except FileNotFoundError:
        print("No saved state yet, starting fresh.")
        state = {}
    except json.JSONDecodeError as e:
        print(f"State file unreadable ({e}), starting fresh.")
        state = {}
    state.setdefault("seen", {})       # Tixel listing -> when it was announced
    state.setdefault("ticketek", {})   # Ticketek date -> tickets left at last check
    state.setdefault("failing", {})    # site -> {"since": when it started failing, "warned": bool}
    state.setdefault("alerts", [])     # alerts sent, for the weekly report
    return state


def save_state(state):
    cutoff = now() - timedelta(days=60)
    state["alerts"] = [a for a in state["alerts"] if datetime.fromisoformat(a["at"]) >= cutoff]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)


def log_alert(state, source, show_names):
    state["alerts"].append({"at": now().isoformat(timespec="seconds"), "source": source, "shows": show_names})


# --- Tixel ------------------------------------------------------------------

def get_tixel_listings(page, url):
    response = page.goto(url, wait_until="load", timeout=45000)
    if response is None or response.status >= 400:
        raise CheckFailed(f"HTTP {response.status if response else 'no response'}")
    time.sleep(3)  # let the listings render
    listings = []
    for btn in page.query_selector_all("button"):
        text = btn.inner_text().strip()
        if "$" in text and "Face Value" not in text:
            listings.append(text)
    return listings


def check_tixel(page, name, url, state, telegram):
    """Announces listings on this Tixel page that haven't been announced before."""
    listings = get_tixel_listings(page, url)

    new = []
    occurrences = Counter()
    for text in listings:
        normalised = " ".join(text.split())
        occurrences[normalised] += 1
        # Two identical listings on the page count as two separate listings.
        key = f"{url}|{normalised}|{occurrences[normalised]}"
        if key not in state["seen"]:
            new.append((key, text))

    if not new:
        note = f" ({plural(len(listings), 'listing')} already announced)" if listings else ""
        print(f"  No new listings{note}.")
        return 0

    print(f"  {plural(len(new), 'new listing')}:")
    for _, text in new:
        print(f"    -> {' '.join(text.split())}")
    message = f"TICKETS AVAILABLE on Tixel!\n{name}\n\n" + "\n\n".join(f"* {text}" for _, text in new)
    message += f"\n\nBuy now: {url}"
    already = len(listings) - len(new)
    if already:
        message += f"\n\n(Also still showing: {plural(already, 'listing')} you've already been told about.)"

    if telegram.send(message):
        stamp = now().isoformat(timespec="seconds")
        for key, _ in new:
            state["seen"][key] = stamp
        log_alert(state, "Tixel", [name])
    return len(new)


# --- Ticketek Marketplace ---------------------------------------------------

def get_ticketek_counts(page, url):
    """Returns tickets left per date, e.g. {"9 Oct": 0, "10 Oct": 2}."""
    response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
    if response is None or response.status >= 400:
        raise CheckFailed(f"HTTP {response.status if response else 'no response'}")
    try:
        page.wait_for_function(
            "() => /none available|sold out|tickets? left/i.test(document.body.innerText)",
            timeout=30000,
        )
    except PlaywrightTimeout:
        raise CheckFailed(f"event list never appeared (page title {page.title()!r}, url {page.url})")

    text = page.inner_text("body")
    rows = list(TICKETEK_ROW.finditer(text))
    counts = {}
    for i, row in enumerate(rows):
        label = f"{int(row.group(1))} {row.group(2).title()}"
        end = rows[i + 1].start() if i + 1 < len(rows) else len(text)
        details = text[row.end():end]
        left = TICKETEK_LEFT.search(details)
        if left:
            counts[label] = int(left.group(1).replace(",", ""))
        elif TICKETEK_NONE.search(details):
            counts[label] = 0
        else:
            print(f"  Couldn't read availability for {label}: {' '.join(details.split())[:120]!r}")
    if not counts:
        raise CheckFailed(f"no event rows found (page starts {' '.join(text.split())[:200]!r})")
    return counts


def check_ticketek(page, url, watching, state, telegram):
    """Announces dates whose "tickets left" went up since the last check.

    `watching` maps Ticketek date labels to show names; None means every date on the page.
    """
    counts = get_ticketek_counts(page, url)
    print("  " + ", ".join(f"{label}: {n}" for label, n in counts.items()))

    rises = []
    for label, n in counts.items():
        if watching is not None and label not in watching:
            continue
        key = f"{url}|{label}"
        before = state["ticketek"].get(key, 0)
        if n > before:
            name = watching[label] if watching else label
            rises.append((key, name, n, before))
        elif n != before:
            state["ticketek"][key] = n  # tickets sold or delisted, nothing to announce

    if not rises:
        print("  No new tickets.")
        return 0

    lines = []
    for _, name, n, before in rises:
        was = f" (was {before})" if before else ""
        lines.append(f"* {name}: {plural(n, 'ticket')} left{was}")
    message = "TICKETS AVAILABLE on Ticketek Marketplace!\n\n" + "\n".join(lines) + f"\n\nBuy now: {url}"
    for line in lines:
        print(f"    -> {line[2:]}")

    if telegram.send(message):
        for key, _, n, _ in rises:
            state["ticketek"][key] = n
        log_alert(state, "Ticketek", [name for _, name, _, _ in rises])
    return len(rises)


# --- Main -------------------------------------------------------------------

def record_health(state, site, error, telegram):
    """Warns once if a site keeps failing to load, and says when it recovers."""
    failing = state["failing"]
    if error is None:
        entry = failing.pop(site, None)
        if entry and entry["warned"]:
            telegram.send(f"{site} is loading properly again. Back to normal monitoring.")
        return

    entry = failing.setdefault(site, {"since": now().isoformat(timespec="seconds"), "warned": False})
    down_for = now() - datetime.fromisoformat(entry["since"])
    if not entry["warned"] and down_for >= WARN_AFTER_FAILING_FOR:
        minutes = int(down_for.total_seconds() // 60)
        if telegram.send(
            f"Heads up: {site} hasn't loaded properly for {minutes} minutes, so I can't see new "
            f"listings there right now.\n\nLatest error: {error}\n\n"
            "I'll keep trying and let you know when it's working again."
        ):
            entry["warned"] = True


def run_checks(page, shows, extra_tixel, extra_ticketek, state, telegram, test_mode):
    found = 0
    errors = {"Ticketek Marketplace": [], "Tixel": []}

    ticketek_pages = [(TICKETEK_URL, {ticketek_label(s): s["name"] for s in shows})]
    if extra_ticketek:
        ticketek_pages.append((extra_ticketek, None))
    for url, watching in ticketek_pages:
        print(f"Checking Ticketek Marketplace: {url}")
        try:
            found += check_ticketek(page, url, watching, state, telegram)
        except Exception as e:
            print(f"  Error: {e}")
            errors["Ticketek Marketplace"].append(str(e))

    tixel_pages = [(s["name"], s["tixel_url"]) for s in shows]
    if extra_tixel:
        tixel_pages.append(("Test event", extra_tixel))
    for name, url in tixel_pages:
        print(f"Checking Tixel: {name}...")
        try:
            found += check_tixel(page, name, url, state, telegram)
        except Exception as e:
            print(f"  Error: {e}")
            errors["Tixel"].append(f"{name}: {e}")

    if not test_mode:
        for site, messages in errors.items():
            record_health(state, site, "; ".join(messages)[:300] or None, telegram)
    return found, errors


def main():
    test_mode = os.environ.get("TEST_MODE") == "true"
    extra_tixel = os.environ.get("TEST_TIXEL_URL") if test_mode else None
    extra_ticketek = os.environ.get("TEST_TICKETEK_URL") if test_mode else None

    telegram = Telegram.from_env(prefix="[TEST] " if test_mode else "")
    state = load_state()
    state_before = json.dumps(state, sort_keys=True)

    try:
        shows = [s for s in SHOWS if not show_is_over(s, now())]
        if not shows and not test_mode:
            print("All shows have started. Nothing left to check.")
            if not state.get("finished_notice_sent"):
                if telegram.send(
                    "All the Olivia Dean shows have now started, so I've stopped checking for tickets. "
                    "You can pause both cron-job.org jobs."
                ):
                    state["finished_notice_sent"] = True
            return

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=USER_AGENT.format(major=browser.version.split(".")[0]),
                locale="en-AU",
                timezone_id="Australia/Sydney",
                viewport={"width": 1280, "height": 900},
            )
            # Skip images, fonts and video: faster page loads, and we only read text.
            context.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font")
                else route.continue_(),
            )
            page = context.new_page()

            # In test mode, check everything twice: the second pass should find nothing new.
            passes = []
            for n in range(2 if test_mode else 1):
                if test_mode:
                    print(f"\n=== Test pass {n + 1} ===")
                passes.append(run_checks(page, shows, extra_tixel, extra_ticketek, state, telegram, test_mode))

            browser.close()

        if test_mode:
            (first, errors), (second, _) = passes
            problems = [f"{site}: {'; '.join(msgs)}" for site, msgs in errors.items() if msgs]
            summary = (
                f"Test run complete.\n\nFirst pass: {first} new (announced above).\n"
                f"Second pass: {second} new (should be 0 - repeats are suppressed)."
            )
            summary += "\n\nProblems:\n" + "\n".join(problems) if problems else "\n\nAll pages loaded fine."
            telegram.send(summary)
    finally:
        save_state(state)
        changed = json.dumps(state, sort_keys=True) != state_before
        print(f"State {'changed' if changed else 'unchanged'}.")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"state_changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()
