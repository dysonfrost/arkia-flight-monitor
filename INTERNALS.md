# Internals

Technical notes on how the bot works under the hood.

---

## Overview

Arkia's website is a React SPA protected by Cloudflare. The frontend makes authenticated calls to an internal REST API to fetch flight data. The bot replicates those calls directly.

### Why not scrape the HTML?

The page is rendered client-side, the initial HTML is just a React shell with no flight data. The flights only appear after the browser executes JavaScript and makes API calls. Waiting for the page to fully render (even with a headless browser) proved unreliable and slow.

### Why FlareSolverr?

Cloudflare's managed challenge requires a real browser to solve. FlareSolverr runs a real Chrome instance, solves the challenge, and returns the resulting `cf_clearance` cookie. The bot uses that cookie for all subsequent API calls, no browser needed for the actual flight queries.

---

## Authentication flow

1. On startup (and every hour), the bot asks FlareSolverr to load `arkia.co.il`
2. FlareSolverr's Chrome solves the Cloudflare JS challenge (~12 seconds)
3. The resulting cookies (especially `cf_clearance`) are cached for 1 hour
4. All flight API calls include these cookies in the `Cookie` header

---

## Flight search API

```
POST https://www.arkia.co.il/api/forward/Search/GetSearchResults?CULTURE_ID=1
Content-Type: application/json
Cookie: cf_clearance=...; <other cookies>
```

Request body:
```json
{
  "OBJECT": {
    "CATEGORY_CODE": "FL",
    "IS_BACK_N_FORTH": false,
    "OB_DEP_CITY": "TLV",
    "OB_DEP_STATION": null,
    "OB_ARV_CITY": "PAR",
    "OB_ARV_STATION": "CDG",
    "OB_DATE": "20260404",
    "IB_DEP_CITY": null,
    "IB_DEP_STATION": null,
    "IB_ARV_CITY": null,
    "IB_ARV_STATION": null,
    "IB_DATE": null,
    "ADULTS": 1,
    "CHILDREN": 0,
    "INFANTS": 0,
    "YOUTH": 0,
    "CURRENCY_CODE": "ILS",
    "ETICKETSN": null,
    "IS_ETICKETSN_MATCH_ONLY": false,
    "IS_EILAT_RESIDENT": false,
    "SEARCH_RESULTS_QUANTITY": 50
  }
}
```

Non-obvious details:
- `CULTURE_ID=1` is Hebrew, the API requires this regardless of UI language
- `OB_ARV_CITY` takes a **city code** (`PAR`, `ROM`, `LON`), not the airport IATA
- `OB_ARV_STATION` takes the **airport IATA** (`CDG`, `FCO`, `LHR`)
- The API returns ~12 results per call starting from `OB_DATE`
- Three paginated calls are made per destination: today, today+10, today+20

---

## Response structure

The response contains a `PRODUCTS` array. Each product represents one flight option:

```json
{
  "IS_AVAILABLE": true,
  "IS_BY_PHONE_ONLY": false,
  "FROM_DATE": "2026-04-04 17:15:00",
  "PRICES": {
    "ADULT_PRICE_IN_NO_PARTY_PRD": 759,
    "CURRENCY_SYMBOLE": "$"
  },
  "FLIGHTS": {
    "OB_FLIGHT": {
      "DEP_DATE": "2026-04-04 17:15:00",
      "ARR_DATE": "2026-04-04 21:15:00",
      "FLIGHT_CARRIER_INFO": { "NO": 741, "CARRIER_CODE": "IZ" },
      "DEP_STATION": { "STATION_CODE": "TLV", "TERMINAL": "3" }
    }
  }
}
```

`IS_AVAILABLE=true` maps directly to the non-sold-out state on the website. Products with `IS_AVAILABLE=false` show as "Sold out" and are filtered out. `IS_BY_PHONE_ONLY=true` products are also skipped.

---

## City code mapping

Arkia groups airports by city in their API. Airports sharing a city use the same `OB_ARV_CITY`:

| City code | Airports |
|-----------|---------|
| `PAR` | CDG, ORY |
| `LON` | LHR, LGW |
| `ROM` | FCO, CIA |
| `MIL` | MXP, LIN |
| `STO` | ARN |

All other airports use their own IATA code as the city code.

---

## Deduplication

Each notified flight gets a UID: `flight:{flight_id}:{dep_date}` stored in `data/notified_flights.json`. The bot never sends the same flight twice unless the cache is cleared.

Within a sweep, products are deduplicated by `PRODUCT_KEY` before filtering, the paginated calls have overlapping date ranges that return the same product multiple times.
