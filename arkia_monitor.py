#!/usr/bin/env python3
"""
Arkia Flight Monitor Bot
========================
Monitors Arkia (IZ) flights from TLV to target European destinations.
Calls Arkia's internal REST API directly, using FlareSolverr to solve
the Cloudflare challenge once and cache the session cookie for 1 hour.

Runs every SCRAPE_INTERVAL_MIN minutes (default: 10).
"""

import os
import sys
import json
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "YOUR_DISCORD_WEBHOOK")
SCRAPE_INTERVAL_MIN = int(os.environ.get("SCRAPE_INTERVAL_MIN", "10"))
SELENIUM_TIMEOUT = int(os.environ.get("SELENIUM_TIMEOUT", "60"))
FLARE_URL = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191/v1")
DAYS_AHEAD = int(os.environ.get("DAYS_AHEAD", "30"))

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
DEP_IATA = "TLV"
AIRLINE_IATA = "IZ"
IL_TZ = ZoneInfo("Asia/Jerusalem")

# Destinations are loaded from destinations.json at startup.
# Edit that file to add/remove destinations — no rebuild needed.
DESTINATIONS_FILE = os.environ.get("DESTINATIONS_FILE", "destinations.json")


def _load_destinations() -> tuple[dict, dict]:
    """Load active destinations and city codes from destinations.json."""
    paths_to_try = [
        DESTINATIONS_FILE,
        os.path.join(os.path.dirname(__file__), DESTINATIONS_FILE),
        "/app/destinations.json",
    ]
    for path in paths_to_try:
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            candidates = data.get("candidates", {})
            active = data.get("active", [])
            dests, cities = {}, {}
            for iata in active:
                if iata not in candidates:
                    print(
                        f"WARNING: {iata} in active list but not in candidates — skipping"
                    )
                    continue
                c = candidates[iata]
                dests[iata] = f"{c['name']} {c['flag']}"
                cities[iata] = c["city_code"]
            print(f"Loaded {len(dests)} destination(s) from {path}")
            return dests, cities
    print(f"WARNING: {DESTINATIONS_FILE} not found — using built-in defaults")
    dests = {
        "CDG": "Paris CDG 🇫🇷",
        "ORY": "Paris Orly 🇫🇷",
        "ATH": "Athens 🇬🇷",
        "FCO": "Rome FCO 🇮🇹",
        "CIA": "Rome Ciampino 🇮🇹",
        "LHR": "London Heathrow 🇬🇧",
        "LGW": "London Gatwick 🇬🇧",
        "AMS": "Amsterdam 🇳🇱",
    }
    cities = {
        "CDG": "PAR",
        "ORY": "PAR",
        "ATH": "ATH",
        "FCO": "ROM",
        "CIA": "ROM",
        "LHR": "LON",
        "LGW": "LON",
        "AMS": "AMS",
    }
    return dests, cities


DESTINATIONS, CITY_CODES = _load_destinations()

ARKIA_API_URL = "https://www.arkia.co.il/api/forward/Search/GetSearchResults"
ARKIA_HOME_URL = "https://www.arkia.co.il/en/"
ARKIA_CULTURE_ID = "1"  # Hebrew (required by the API)

NOTIFIED_FILE = os.environ.get("NOTIFIED_FILE", "notified_flights.json")
LOG_FILE = os.environ.get("LOG_FILE", "arkia_monitor.log")

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# STATE
# ──────────────────────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        log.debug("load_json %s: %s", path, e)
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_notified() -> set:
    return set(load_json(NOTIFIED_FILE, []))


def save_notified(s: set):
    save_json(NOTIFIED_FILE, list(s))


# ──────────────────────────────────────────────────────────────────────────────
# DISCORD
# ──────────────────────────────────────────────────────────────────────────────
def discord_post(payload: dict):
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("Discord webhook failed: %s", e)


def notify_status(msg: str):
    discord_post({"username": "Arkia Flight Bot", "content": msg})


def notify_flight(flight: dict):
    dest = DESTINATIONS.get(flight["arr_iata"], flight["arr_iata"])
    dep_date = flight["dep_date"].replace("-", "")  # YYYYMMDD for URL
    book_url = (
        f"https://www.arkia.co.il/en/flights-results"
        f"?CC=FL&IS_BACK_N_FORTH=false"
        f"&OB_DEP_CITY={DEP_IATA}&OB_ARV_CITY={flight['arr_iata']}"
        f"&OB_DATE={dep_date}&ADULTS=1"
    )
    embed = {
        "title": f"\u2708\ufe0f  Arkia flight available! TLV \u2192 {dest}",
        "description": f"**[\U0001f449 Click here to book]({book_url})**",
        "color": 0x6A0DAD,
        "url": book_url,
        "fields": [
            {"name": "Flight", "value": f"`{flight['flight_id']}`", "inline": True},
            {"name": "Date", "value": flight["dep_date"], "inline": True},
            {
                "name": "Terminal \U0001f3e2",
                "value": flight.get("terminal", "N/A"),
                "inline": True,
            },
            {
                "name": "Departure \U0001f6eb",
                "value": flight["dep_time"],
                "inline": True,
            },
            {"name": "Arrival \U0001f6ec", "value": flight["arr_time"], "inline": True},
            {
                "name": "Price \U0001f4b0",
                "value": flight.get("price", "N/A"),
                "inline": True,
            },
        ],
        "footer": {"text": "Arkia Monitor Bot \u2022 Direct API"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    discord_post(
        {
            "username": "Arkia Flight Bot",
            "avatar_url": "https://airlabs.co/img/airline/m/IZ.png",
            "content": "@here 🚨 **Arkia flight found — book NOW!**",
            "embeds": [embed],
        }
    )
    log.info(
        "Notified: %s → %s on %s at %s",
        flight["flight_id"],
        flight["arr_iata"],
        flight["dep_date"],
        flight["dep_time"],
    )


def send_daily_report():
    now = datetime.now(IL_TZ)
    discord_post(
        {
            "username": "Arkia Flight Bot",
            "content": (
                f"📊 **Daily Report** — {now.strftime('%Y-%m-%d %H:%M')} IL\n"
                f"• Sweep every `{SCRAPE_INTERVAL_MIN}min` | "
                f"Monitoring next `{DAYS_AHEAD}` days\n"
                f"• Destinations: {', '.join(DESTINATIONS.keys())}"
            ),
        }
    )


# ──────────────────────────────────────────────────────────────────────────────
# SESSION (FlareSolverr → cf_clearance cookie)
# ──────────────────────────────────────────────────────────────────────────────
_arkia_session: dict = {}


def _refresh_arkia_session() -> bool:
    """Use FlareSolverr to load Arkia homepage and cache the cf_clearance cookie."""
    global _arkia_session
    log.info("Refreshing Arkia session via FlareSolverr...")
    try:
        sr = requests.post(FLARE_URL, json={"cmd": "sessions.create"}, timeout=30)
        session_id = sr.json().get("session")

        resp = requests.post(
            FLARE_URL,
            json={
                "cmd": "request.get",
                "url": ARKIA_HOME_URL,
                "maxTimeout": SELENIUM_TIMEOUT * 1000,
                "session": session_id,
            },
            timeout=SELENIUM_TIMEOUT + 15,
        )

        if session_id:
            requests.post(
                FLARE_URL,
                json={"cmd": "sessions.destroy", "session": session_id},
                timeout=10,
            )

        data = resp.json()
        if data.get("status") != "ok":
            log.error("FlareSolverr failed: %s", data.get("message"))
            return False

        cookies = data["solution"]["cookies"]
        ua = data["solution"]["userAgent"]
        _arkia_session = {
            "cookies": "; ".join(f"{c['name']}={c['value']}" for c in cookies),
            "user_agent": ua,
            "expires_at": time.time() + 3600,
        }
        log.info(
            "Session refreshed. Cookies: %s", ", ".join(c["name"] for c in cookies)
        )
        return True

    except Exception as e:
        log.error("Session refresh error: %s", e)
        return False


def _get_headers() -> dict | None:
    """Return HTTP headers with valid Arkia cookies, refreshing if needed."""
    if not _arkia_session or time.time() > _arkia_session.get("expires_at", 0):
        if not _refresh_arkia_session():
            return None
    return {
        "User-Agent": _arkia_session["user_agent"],
        "Cookie": _arkia_session["cookies"],
        "Content-Type": "application/json",
        "Origin": "https://www.arkia.co.il",
        "Referer": "https://www.arkia.co.il/en/flights-results",
    }


# ──────────────────────────────────────────────────────────────────────────────
# ARKIA API
# ──────────────────────────────────────────────────────────────────────────────
def search_flights(arr_iata: str) -> list[dict]:
    """Call Arkia's search API for one destination. Returns available flights."""
    headers = _get_headers()
    if not headers:
        log.warning("Session not ready for %s, retrying in 5s...", arr_iata)
        time.sleep(5)
        headers = _get_headers()
    if not headers:
        log.error("No valid session — skipping %s", arr_iata)
        return []

    today = datetime.now(IL_TZ).date()
    city_code = CITY_CODES.get(arr_iata, arr_iata)
    url = f"{ARKIA_API_URL}?CULTURE_ID={ARKIA_CULTURE_ID}"

    def _payload(ob_date: str) -> dict:
        return {
            "OBJECT": {
                "CATEGORY_CODE": "FL",
                "IS_BACK_N_FORTH": False,
                "OB_DEP_CITY": DEP_IATA,
                "OB_DEP_STATION": None,
                "OB_ARV_CITY": city_code,
                "OB_ARV_STATION": arr_iata,
                "OB_DATE": ob_date,
                "IB_DEP_CITY": None,
                "IB_DEP_STATION": None,
                "IB_ARV_CITY": None,
                "IB_ARV_STATION": None,
                "IB_DATE": None,
                "ADULTS": 1,
                "CHILDREN": 0,
                "INFANTS": 0,
                "YOUTH": 0,
                "CURRENCY_CODE": "ILS",
                "ETICKETSN": None,
                "IS_ETICKETSN_MATCH_ONLY": False,
                "IS_EILAT_RESIDENT": False,
                "SEARCH_RESULTS_QUANTITY": 50,
            }
        }

    # Paginate: 3 calls covering the full DAYS_AHEAD window
    # Each call returns ~12 results starting from the given date
    search_dates = [
        today.strftime("%Y%m%d"),
        (today + timedelta(days=10)).strftime("%Y%m%d"),
        (today + timedelta(days=20)).strftime("%Y%m%d"),
    ]
    log.info(
        "Calling API: TLV → %s (%d pages, covering %d days)",
        arr_iata,
        len(search_dates),
        DAYS_AHEAD,
    )

    try:
        all_products = []
        for ob_date in search_dates:
            resp = requests.post(
                url, json=_payload(ob_date), headers=headers, timeout=30
            )

            if resp.status_code in (401, 403):
                log.warning(
                    "Session expired (HTTP %d), refreshing...", resp.status_code
                )
                _arkia_session.clear()
                headers = _get_headers()
                if not headers:
                    break
                resp = requests.post(
                    url, json=_payload(ob_date), headers=headers, timeout=30
                )

            if resp.status_code == 500:
                log.warning(
                    "HTTP 500 for TLV → %s page %s. Body: %s",
                    arr_iata,
                    ob_date,
                    resp.text[:200],
                )
                continue

            if not resp.ok:
                log.warning("HTTP %d for TLV → %s", resp.status_code, arr_iata)
                continue

            data = resp.json()
            if data.get("ERROR"):
                log.warning("API error for %s: %s", arr_iata, data["ERROR"])
                continue

            page = (data.get("RESPONSE") or {}).get("PRODUCTS") or []
            all_products.extend(page)

        # Deduplicate by PRODUCT_KEY
        seen, products = set(), []
        for p in all_products:
            key = p.get("PRODUCT_KEY") or p.get("SERIAL_KEY")
            if key not in seen:
                seen.add(key)
                products.append(p)

        log.info("%d unique product(s) for TLV → %s", len(products), arr_iata)

        flights = []
        for p in products:
            if not p.get("IS_AVAILABLE", True):
                continue
            if p.get("IS_BY_PHONE_ONLY"):
                continue

            ob = (p.get("FLIGHTS") or {}).get("OB_FLIGHT") or {}
            prices = p.get("PRICES") or {}
            dep_raw = ob.get("DEP_DATE") or p.get("FROM_DATE", "")
            arr_raw = ob.get("ARR_DATE", "")
            price = (
                prices.get("ADULT_PRICE_IN_NO_PARTY_PRD")
                or prices.get("TOTAL_PRICE")
                or prices.get("AVG_REDUCED_PRICE_PP")
            )
            curr = prices.get("CURRENCY_SYMBOLE", "$")
            fnum = (ob.get("FLIGHT_CARRIER_INFO") or {}).get("NO", "")

            try:
                dep_dt = datetime.strptime(dep_raw[:16], "%Y-%m-%d %H:%M")
                dep_date = dep_dt.strftime("%Y-%m-%d")
                dep_time = dep_dt.strftime("%H:%M")
            except (ValueError, TypeError) as e:
                log.debug("Dep date parse error for %s: %s", arr_iata, e)
                continue

            if not (today <= dep_dt.date() <= today + timedelta(days=DAYS_AHEAD)):
                continue

            try:
                arr_time = datetime.strptime(arr_raw[:16], "%Y-%m-%d %H:%M").strftime(
                    "%H:%M"
                )
            except (ValueError, TypeError) as e:
                log.debug("Arr time parse skipped: %s", e)
                arr_time = "N/A"

            flights.append(
                {
                    "flight_id": f"IZ{fnum}" if fnum else f"IZ-{arr_iata}-{dep_date}",
                    "arr_iata": arr_iata,
                    "dep_date": dep_date,
                    "dep_time": dep_time,
                    "arr_time": arr_time,
                    "price": f"{curr}{price}" if price else "N/A",
                    "terminal": (ob.get("DEP_STATION") or {}).get("TERMINAL") or "N/A",
                }
            )

        log.info("%d available flight(s) for TLV → %s", len(flights), arr_iata)
        return flights

    except requests.RequestException as e:
        log.error("API request error for %s: %s", arr_iata, e)
        return []


def run_sweep(notified: set) -> set:
    log.info("Starting sweep (%d destinations)", len(DESTINATIONS))
    new_count = 0
    for arr_iata in DESTINATIONS:
        try:
            flights = search_flights(arr_iata)
        except Exception as e:
            log.error("Unexpected error for %s: %s", arr_iata, e)
            flights = []

        for f in flights:
            uid = f"flight:{f['flight_id']}:{f['dep_date']}"
            if uid not in notified:
                notify_flight(f)
                notified.add(uid)
                new_count += 1

        time.sleep(1)

    save_notified(notified)
    log.info("Sweep done. %d new flight(s) found.", new_count)
    return notified


# ──────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ──────────────────────────────────────────────────────────────────────────────
def run():
    log.info("=" * 62)
    log.info("  Arkia Monitor Bot")
    log.info("  Sweep every %dmin | Next %d days", SCRAPE_INTERVAL_MIN, DAYS_AHEAD)
    log.info("  Destinations: %s", ", ".join(DESTINATIONS.keys()))
    log.info("=" * 62)

    notified = load_notified()
    last_report_day = None
    last_sweep_run = None

    # Wait for FlareSolverr to be ready before first sweep
    log.info("Waiting 10s for FlareSolverr to start...")
    time.sleep(10)

    notified = run_sweep(notified)
    last_sweep_run = datetime.now(IL_TZ)

    while True:
        now = datetime.now(IL_TZ)
        today = now.date()

        if last_report_day != today:
            last_report_day = today
            send_daily_report()

        if (
            last_sweep_run is None
            or (now - last_sweep_run).total_seconds() >= SCRAPE_INTERVAL_MIN * 60
        ):
            notified = run_sweep(notified)
            last_sweep_run = datetime.now(IL_TZ)

        time.sleep(5)


# ──────────────────────────────────────────────────────────────────────────────
# TEST MODE
# ──────────────────────────────────────────────────────────────────────────────
def run_test():
    log.info("=" * 62)
    log.info("  TEST MODE — no real API calls, no state written")
    log.info("=" * 62)

    fake = {
        "flight_id": "IZ215",
        "arr_iata": "ATH",
        "dep_date": "2026-04-04",
        "dep_time": "20:50",
        "arr_time": "23:00",
        "price": "$489",
        "terminal": "3",
    }
    log.info("[TEST] Sending fake flight notification...")
    notify_flight(fake)
    time.sleep(1)

    log.info("[TEST] Sending fake daily report...")
    send_daily_report()

    log.info("[TEST] Done. You should see 2 Discord messages.")


# ──────────────────────────────────────────────────────────────────────────────
# DEBUG MODE
# ──────────────────────────────────────────────────────────────────────────────
def run_debug_api():
    """Fetch Arkia JS bundle via FlareSolverr and search for API endpoints."""
    import re

    log.info("=== DEBUG: Finding Arkia internal API ===")
    session_id = None
    sr = requests.post(FLARE_URL, json={"cmd": "sessions.create"}, timeout=30)
    if sr.ok:
        session_id = sr.json().get("session")

    home = requests.post(
        FLARE_URL,
        json={
            "cmd": "request.get",
            "url": ARKIA_HOME_URL,
            "maxTimeout": 60000,
            "session": session_id,
        },
        timeout=90,
    )
    home_html = home.json()["solution"]["response"]
    js_files = re.findall(r'src="(/app/site/[^"]+\.js[^"]*)"', home_html)
    log.info("JS bundles: %s", js_files)

    main_bundle = next(
        (f for f in js_files if "main" in f), js_files[-1] if js_files else None
    )
    if not main_bundle:
        log.error("No JS bundle found.")
        return

    br = requests.post(
        FLARE_URL,
        json={
            "cmd": "request.get",
            "url": f"https://www.arkia.co.il{main_bundle}",
            "maxTimeout": 60000,
            "session": session_id,
        },
        timeout=90,
    )
    js = br.json()["solution"]["response"]
    if session_id:
        requests.post(
            FLARE_URL,
            json={"cmd": "sessions.destroy", "session": session_id},
            timeout=10,
        )

    log.info("Bundle size: %d chars", len(js))
    for pattern, label in [
        (r"https?://[a-zA-Z0-9._-]*arkia[a-zA-Z0-9._/-]*", "arkia URL"),
        (r'"(/api/[a-zA-Z0-9/_-]{3,60})"', "api path"),
        (r'(?:apiUrl|baseUrl|apiBase)["\'\s:=]+["\'`]([^"\'`\s]{5,100})', "config key"),
    ]:
        matches = list(dict.fromkeys(re.findall(pattern, js, re.IGNORECASE)))[:10]
        if matches:
            log.info("[%s]: %s", label, matches)

    with open("/app/data/main_bundle_sample.txt", "w") as f:
        f.write(js[:10000])
    log.info("Bundle sample saved to /app/data/main_bundle_sample.txt")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test()
    elif "--debug-api" in sys.argv:
        run_debug_api()
    else:
        run()
