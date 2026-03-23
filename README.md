# ✈️ Arkia Flight Monitor Bot

Monitors Arkia Airlines (IZ) flights from Tel Aviv (TLV) to European destinations and sends Discord notifications the moment a bookable flight appears.

Runs on a Raspberry Pi (or any Linux box) via Docker.

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) + [Docker Compose](https://docs.docker.com/compose/)
- A Discord server with a webhook URL

---

## Setup

### 1. Get the files

```
arkia-bot/
├── arkia_monitor.py
├── destinations.json
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```

### 2. Create a Discord webhook

In your Discord server: **Server Settings → Integrations → Webhooks → New Webhook**

Copy the webhook URL, it looks like:
```
https://discord.com/api/webhooks/123456789/abcdefgh...
```

### 3. Configure `.env`

```env
# How often to sweep all destinations (minutes). 5 is recommended.
SCRAPE_INTERVAL_MIN=5

# How many days ahead to monitor
DAYS_AHEAD=30

# Page load timeout for FlareSolverr (seconds) ; don't lower this
SELENIUM_TIMEOUT=60

# FlareSolverr sidecar URL ; no need to change
FLARESOLVERR_URL=http://flaresolverr:8191/v1

# Your Discord webhook URL
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR/WEBHOOK
```

### 4. Deploy

```bash
docker compose up -d --build
docker compose logs -f
```

---

## Configuring destinations

Edit `destinations.json` no rebuild needed, just restart:

```json
{
  "active": [
    "CDG",
    "ATH",
    "AMS"
  ]
}
```

Then:
```bash
docker compose restart arkia-bot
```

The `candidates` dictionary in the same file lists all 53 supported airports. Add any IATA code from the candidates list to `active` to start monitoring it.

---

## Useful commands

```bash
# Start
docker compose up -d --build

# Live logs
docker compose logs -f

# Stop
docker compose down

# Restart after editing .env or destinations.json (no rebuild needed)
docker compose restart arkia-bot

# Test Discord notifications (2 fake messages, no real API calls)
docker compose run --rm arkia-test

# Clear notified flights cache (will re-notify all known flights on next sweep)
rm data/notified_flights.json

# View activity log
tail -f data/arkia_monitor.log
```

---

## Discord notifications

Each notification includes flight number, date, terminal, departure/arrival times, price, and a direct link that opens the Arkia booking page pre-filtered for that route and date.

A daily status report is sent at midnight Israel time.

---

## Data files

Stored in `./data/` (Docker volume, persists across restarts):

| File | Purpose |
|------|---------|
| `notified_flights.json` | Already-notified flights (prevents duplicate pings) |
| `arkia_monitor.log` | Full activity log |

---

## Troubleshooting

**No Discord messages after startup**
- Run `docker compose run --rm arkia-test` to verify the webhook works
- Check `docker compose logs` for errors
- Arkia may simply have no available flights right now (sold-out flights are filtered)

**FlareSolverr keeps failing**
- Check port 8191 is free: `ss -tlnp | grep 8191`
- Pull the latest image: `docker compose pull flaresolverr`

**First destination skipped on startup**
- On slow machines, FlareSolverr may need more than 10 seconds to initialize
- Increase the startup delay: edit `time.sleep(10)` in the `run()` function

**Flight visible on website but bot didn't notify**
- Check `data/notified_flights.json` it may have been notified in a previous session
- The bot monitors `DAYS_AHEAD` days ahead (default 30). Flights beyond that are ignored
- Clear the cache with `rm data/notified_flights.json` and restart to re-check everything

**"Session expired" warnings in logs**
- Normal. The Cloudflare session refreshes automatically every hour. No action needed.
