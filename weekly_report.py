"""Weekly Telegram check-in: scraper runs per day, alerts sent, and what's still being watched."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os

import requests

from tixel_scraper import SHOWS, STOP_CHECKING_AT, Telegram, load_state, now, plural, show_is_over

AWST = ZoneInfo("Australia/Perth")
EXPECTED_RUNS_PER_DAY = 480  # cron-job.org fires every 3 minutes


def count_runs(start, end, status):
    """Number of scraper runs created between start and end with the given result."""
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    response = requests.get(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/workflows/scrape.yml/runs",
        params={
            "status": status,
            "per_page": 1,
            "created": f"{start.astimezone(timezone.utc):{fmt}}..{end.astimezone(timezone.utc):{fmt}}",
        },
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["total_count"]


def run_counts():
    """One line per day for the 7 full days (AWST) before today."""
    today = datetime.now(AWST).replace(hour=0, minute=0, second=0, microsecond=0)
    lines = []
    for days_ago in range(7, 0, -1):
        start = today - timedelta(days=days_ago)
        end = start + timedelta(days=1)
        try:
            ok = count_runs(start, end, "success")
            failed = count_runs(start, end, "failure")
        except Exception as e:
            print(f"GitHub API error for {start:%Y-%m-%d}: {e}")
            lines.append(f"{start:%a %d %b}: unavailable")
            continue
        line = f"{start:%a %d %b}: {ok} runs"
        if failed:
            line += f", {failed} failed"
        lines.append(line)
    return lines


def main():
    state = load_state()
    week_ago = now() - timedelta(days=7)
    alerts = [a for a in state["alerts"] if datetime.fromisoformat(a["at"]) >= week_ago]

    parts = [f"Weekly check-in — {datetime.now(AWST):%A %-d %B %Y}"]
    parts.append(
        "Scraper runs per day (AWST):\n" + "\n".join(run_counts())
        + f"\n(About {EXPECTED_RUNS_PER_DAY} a day is normal: one run every 3 minutes.)"
    )

    if alerts:
        lines = []
        for a in alerts[-10:]:
            at = datetime.fromisoformat(a["at"]).astimezone(AWST)
            lines.append(f"* {at:%a %d %b %H:%M} {a['source']}: {', '.join(a['shows'])}")
        more = f"\n(+{len(alerts) - 10} earlier)" if len(alerts) > 10 else ""
        parts.append(f"Ticket alerts sent this week: {len(alerts)}\n" + "\n".join(lines) + more)
    else:
        parts.append("No ticket alerts this week.")

    for site, entry in state["failing"].items():
        since = datetime.fromisoformat(entry["since"]).astimezone(AWST)
        parts.append(f"Warning: {site} has not been loading properly since {since:%a %d %b %H:%M}.")

    active = [s for s in SHOWS if not show_is_over(s, now())]
    if active:
        last = max(active, key=lambda s: s["date"])
        last_day = datetime.strptime(last["date"], "%Y-%m-%d")
        parts.append(
            f"Watching {plural(len(active), 'Olivia Dean show')} on Tixel and Ticketek Marketplace. "
            f"Checks stop automatically at {STOP_CHECKING_AT} Sydney time on {last_day:%a %-d %b}."
        )
    else:
        parts.append("All shows have passed and the scraper has stopped checking. You can pause both cron-job.org jobs.")

    message = "\n\n".join(parts)
    print(message)
    Telegram.from_env().send(message)


if __name__ == "__main__":
    main()
