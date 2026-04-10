#!/usr/bin/env python3
"""Poll Claude subscription usage and push sensors to Home Assistant."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone

import requests
from playwright.sync_api import sync_playwright

# ─── Configuration ───────────────────────────────────────────────────────────
HA_URL = os.environ.get("HA_URL", "http://192.168.10.104:8123")
HA_TOKEN = os.environ.get(
    "HA_TOKEN",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJpc3MiOiJmODliNDk2MTUyZWQ0NTY2OGEwNGI4NDFhNGE0NmUwMiIsImlhdCI6MTc3NTg1OTE3MiwiZXhwIjoyMDkxMjE5MTcyfQ"
    ".AUJ5R6Oog9UD7q85gqZBxW7fcTdL8dYDRZ_S1tGSkw4",
)

SESSION_KEY = os.environ.get(
    "CLAUDE_SESSION_KEY",
    "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",
)
ORG_ID = os.environ.get("CLAUDE_ORG_ID", "deee6eb3-19dd-4f4b-92c7-dd8c0fc68424")

USAGE_URL = f"https://claude.ai/api/organizations/{ORG_ID}/usage"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ─── Fetch usage via headless browser ────────────────────────────────────────
def fetch_usage() -> dict:
    """Fetch usage data from claude.ai using a real browser to bypass Cloudflare."""
    with sync_playwright() as p:
        # Use installed Chrome in headed mode to pass Cloudflare
        browser = p.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context()

        # Set the sessionKey cookie
        context.add_cookies([{
            "name": "sessionKey",
            "value": SESSION_KEY,
            "domain": "claude.ai",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "Lax",
        }])

        page = context.new_page()

        # First visit claude.ai to pass the Cloudflare challenge
        log.info("Navigating to claude.ai to pass Cloudflare challenge...")
        page.goto("https://claude.ai/", wait_until="domcontentloaded", timeout=60000)

        # Wait for Cloudflare challenge to clear (page title changes)
        log.info("Waiting for Cloudflare to clear...")
        try:
            page.wait_for_function(
                "document.title !== 'Just a moment...'",
                timeout=30000,
            )
        except Exception:
            pass  # Title may have already changed

        # Wait for any redirect to settle
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        log.info("Cloudflare cleared — page title: %s", page.title())

        # Fetch the usage API from within the page (same origin, cookies included)
        log.info("Fetching usage data...")
        result = page.evaluate("""async (url) => {
            try {
                const resp = await fetch(url, { credentials: 'include' });
                if (!resp.ok) return { error: resp.status, text: await resp.text() };
                return { ok: true, data: await resp.json() };
            } catch (e) {
                return { error: 0, text: e.message };
            }
        }""", USAGE_URL)

        browser.close()

        if "error" in result:
            log.error("API request failed (status %s): %s", result["error"], result.get("text", "")[:200])
            sys.exit(1)

        return result["data"]


# ─── HA helpers ──────────────────────────────────────────────────────────────
def push_sensor(entity_id: str, state, attributes: dict, dry_run: bool) -> None:
    """POST a sensor state to Home Assistant."""
    payload = {"state": state, "attributes": attributes}

    if dry_run:
        log.info("[DRY RUN] %s → %s  attr=%s", entity_id, state, attributes)
        return

    url = f"{HA_URL.rstrip('/')}/api/states/{entity_id}"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {HA_TOKEN}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    log.info("Pushed %s → %s", entity_id, state)


def minutes_until(iso_ts: str) -> int:
    """Return whole minutes from now until the given ISO-8601 timestamp."""
    target = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    delta = target - datetime.now(timezone.utc)
    return max(0, int(delta.total_seconds() // 60))


# ─── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads without pushing to HA",
    )
    args = parser.parse_args()

    if not SESSION_KEY:
        log.error("No session key — set CLAUDE_SESSION_KEY env var or edit the script")
        sys.exit(1)

    usage = fetch_usage()

    # --- Five-hour (session) window ---
    five = usage.get("five_hour", {})
    push_sensor(
        "sensor.claude_session_utilization",
        five.get("utilization", 0),
        {
            "unit_of_measurement": "%",
            "icon": "mdi:gauge",
            "friendly_name": "Claude Session Utilization",
            "resets_at": five.get("resets_at", ""),
            "minutes_until_reset": minutes_until(five["resets_at"])
            if five.get("resets_at")
            else None,
        },
        args.dry_run,
    )
    push_sensor(
        "sensor.claude_session_resets_at",
        five.get("resets_at", ""),
        {
            "icon": "mdi:timer-sand",
            "friendly_name": "Claude Session Resets At",
            "device_class": "timestamp",
        },
        args.dry_run,
    )

    # --- Seven-day (weekly) window ---
    week = usage.get("seven_day", {})
    push_sensor(
        "sensor.claude_weekly_utilization",
        week.get("utilization", 0),
        {
            "unit_of_measurement": "%",
            "icon": "mdi:chart-line",
            "friendly_name": "Claude Weekly Utilization",
            "resets_at": week.get("resets_at", ""),
            "minutes_until_reset": minutes_until(week["resets_at"])
            if week.get("resets_at")
            else None,
        },
        args.dry_run,
    )
    push_sensor(
        "sensor.claude_weekly_resets_at",
        week.get("resets_at", ""),
        {
            "icon": "mdi:calendar-clock",
            "friendly_name": "Claude Weekly Resets At",
            "device_class": "timestamp",
        },
        args.dry_run,
    )

    # --- Extra usage (only if enabled) ---
    extra = usage.get("extra_usage")
    if extra and extra.get("is_enabled"):
        push_sensor(
            "sensor.claude_extra_usage_credits_used",
            extra.get("used_credits", 0),
            {
                "unit_of_measurement": "credits",
                "icon": "mdi:currency-usd",
                "friendly_name": "Claude Extra Usage Credits Used",
                "monthly_limit": extra.get("monthly_limit"),
            },
            args.dry_run,
        )
        push_sensor(
            "sensor.claude_extra_usage_utilization",
            extra.get("utilization", 0),
            {
                "unit_of_measurement": "%",
                "icon": "mdi:credit-card-clock",
                "friendly_name": "Claude Extra Usage Utilization",
                "monthly_limit": extra.get("monthly_limit"),
                "used_credits": extra.get("used_credits"),
            },
            args.dry_run,
        )
    else:
        log.info("Extra usage not enabled or absent — skipping those sensors")

    log.info("Done")


if __name__ == "__main__":
    main()
