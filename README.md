# ✈️ Arkia Flight Monitor Bot

Monitors Arkia Airlines (IZ) flights from Tel Aviv (TLV) to European destinations and sends Discord notifications the moment a bookable flight appears.

Runs on a Raspberry Pi (or any Linux box) via Docker.

---

## How it works

1. Every few minutes the bot calls Arkia's internal flight search API directly
2. [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr) solves the Cloudflare challenge once on startup, then the session cookie is cached for 1 hour
3. Each sweep queries all monitored destinations across a 30-day window (3 paginated API calls per destination)
4. When a new bookable flight appears, a Discord `@here` notification is sent with flight details and a direct booking link
5. Already-notified flights are remembered in `data/notified_flights.json` so you only get pinged once per flight

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) + [Docker Compose](https://docs.docker.com/compose/)
- A Discord server with a webhook URL

---

## Setup

### 1. Clone / copy the files

You need these files in a directory:

```
arkia-bot/
├── arkia_monitor.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

### 2. Create a Discord webhook

In your Discord server: **Server Settings → Integrations → Webhooks → New Webhook**

Copy the webhook URL — it looks like:
```
https://discord.com/api/webhooks/123456789/abcdefgh...
```

### 3. Configure `.env`

Edit `.env` and fill in your webhook:

```env
# How often to sweep all destinations (minutes). 5 is recommended.
SCRAPE_INTERVAL_MIN=5

# How many days ahead to monitor
DAYS_AHEAD=30

# Page load timeout for FlareSolverr (seconds) — don't lower this
SELENIUM_TIMEOUT=60

# FlareSolverr sidecar URL — no need to change
FLARESOLVERR_URL=http://flaresolverr:8191/v1

# Your Discord webhook URL
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR/WEBHOOK
```

### 4. Deploy

```bash
docker compose up -d --build
```

The bot starts immediately. On first launch it waits 10 seconds for FlareSolverr to initialize, then runs the first sweep.

---

## Monitored destinations

| Airport | City |
|---------|------|
| CDG | Paris Charles de Gaulle |
| ORY | Paris Orly |
| ATH | Athens |
| FCO | Rome Fiumicino |
| CIA | Rome Ciampino |
| LHR | London Heathrow |
| LGW | London Gatwick |
| AMS | Amsterdam |

Destinations are configured in `destinations.json` — no code changes or rebuilds needed.

**To change which destinations are monitored**, edit the `active` list in `destinations.json`:

```json
{
  "active": [
    "CDG",
    "ATH",
    "AMS"
  ]
}
```

Then restart the bot:

```bash
docker compose restart arkia-bot
```

The `candidates` dictionary in the same file contains all supported airports with their required city codes. Arkia's API uses city codes (`PAR`, `ROM`, `LON`) in the search payload — the mapping is already handled for you. Just pick any IATA code from the candidates list and add it to `active`.

If you want to monitor an airport not in the candidates list, add it following the same format:

```json
"XYZ": { "city_code": "XYZ", "name": "My City", "flag": "🏳️" }
```

The city code is often the same as the airport IATA code, except for cities with multiple airports (London → `LON`, Paris → `PAR`, Rome → `ROM`, Milan → `MIL`, Stockholm → `STO`).

---

## Useful commands

```bash
# Start the bot
docker compose up -d --build

# View live logs
docker compose logs -f

# Stop the bot
docker compose down

# Restart without rebuilding (e.g. after changing .env)
docker compose restart arkia-bot

# Test Discord notifications (sends 2 fake messages, no real API calls)
docker compose run --rm arkia-test

# Debug: inspect Arkia's API endpoints via the JS bundle
docker compose run --rm arkia-debug

# Clear notified flights cache (re-notifies all known flights on next sweep)
rm data/notified_flights.json

# View the activity log
tail -f data/arkia_monitor.log
```

---

## Discord notifications

Each notification looks like this:

> **@here 🚨 Arkia flight found — book NOW!**
>
> ✈️ **Arkia flight available! TLV → Amsterdam 🇳🇱**  
> 👉 Click here to book _(link opens Arkia search pre-filtered for that route and date)_
>
> | Flight | Date | Terminal |
> |--------|------|----------|
> | IZ513 | 2026-04-03 | 3 |
> | Departure | Arrival | Price |
> | 13:25 | 17:30 | $587 |

A daily status report is also sent at midnight Israel time.

---

## Data files

All state is stored in `./data/` (mounted as a Docker volume, persists across restarts):

| File | Purpose |
|------|---------|
| `notified_flights.json` | UIDs of already-notified flights — prevents duplicate pings |
| `arkia_monitor.log` | Full activity log with timestamps |

---

## Troubleshooting

**Bot starts but no Discord messages**
- Check `docker compose logs` for errors
- Run `docker compose run --rm arkia-test` to verify the webhook URL works
- Arkia may simply have no available flights right now — sold-out flights are filtered out

**FlareSolverr keeps failing**
- Check that port 8191 is not in use: `ss -tlnp | grep 8191`
- Try pulling the latest image: `docker compose pull flaresolverr`

**First destination always skipped on startup**
- On slow machines FlareSolverr may need more than 10 seconds. Increase the `time.sleep(10)` in the `run()` function in `arkia_monitor.py`

**"Session expired" warnings**
- Normal — the bot automatically refreshes the Cloudflare session every hour. No action needed.

**Flight appears on website but bot didn't notify**
- Check `data/notified_flights.json` — the flight may have already been notified
- The bot queries 30 days ahead. Flights beyond that window are filtered (adjust `DAYS_AHEAD` in `.env`)
- The API paginates in batches of ~12. The bot makes 3 calls (today, today+10, today+20). If a flight falls outside this coverage, increase `DAYS_AHEAD`

---

## How the API works

The bot calls Arkia's internal REST API directly:

```
POST https://www.arkia.co.il/api/forward/Search/GetSearchResults?CULTURE_ID=1
```

Key details discovered through reverse engineering:
- `CULTURE_ID=1` is Hebrew — the API requires this regardless of language preference
- `OB_ARV_CITY` takes a **city code** (`PAR`, `ROM`, `LON`) not the airport IATA code
- `OB_ARV_STATION` takes the **airport IATA code** (`CDG`, `FCO`, `LHR`)
- `IS_AVAILABLE=true` in the response means the flight is bookable (maps to the website's non-sold-out state)
- The API returns ~12 results per call starting from `OB_DATE` — pagination is required to cover 30 days
- Cloudflare blocks direct requests; FlareSolverr solves the JS challenge and provides a `cf_clearance` cookie that's then used for all subsequent API calls directly (no browser needed)
