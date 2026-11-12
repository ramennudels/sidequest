import csv
import io
import json
import sqlite3
import time
import requests
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_NAME = "sidequest.db"

ALLOWED_DELIVERY_TYPES = {"key", "gift"}
BLOCKED_KEYWORDS = {"account", "steam account", "shared account", "offline activation", "login"}

STEAM_SEASONAL_SALES = [
    (3, 14),   # Steam Spring Sale
    (6, 27),   # Steam Summer Sale
    (11, 27),  # Steam Autumn Sale
    (12, 19),  # Steam Winter Sale
]

CHEAPSHARK_STORES = {
    "1": "Steam",
    "2": "GamersGate",
    "3": "Green Man Gaming",
    "7": "GOG",
    "11": "Humble Store",
    "13": "Uplay",
    "15": "Fanatical",
    "21": "WinGameStore",
    "23": "GameBillet",
    "24": "Voidu",
    "25": "Epic Games Store",
    "27": "Gamesplanet",
    "28": "Gamesload",
    "29": "2Game",
    "30": "IndieGala",
    "31": "Blizzard Shop",
    "33": "DLGamer",
    "34": "Noctre",
    "35": "DreamGame",
}


class StoreOfferInput(BaseModel):
    app_id: int
    store: str
    store_type: str = "Key Reseller"
    title: str
    price: float
    discount_percent: int
    delivery_type: str
    region: str = "GLOBAL"
    store_url: Optional[str] = ""
    raw_listing_name: Optional[str] = ""


class VoucherInput(BaseModel):
    store: str
    code: str
    discount_percent: int
    min_spend: float = 0.0


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            app_id INTEGER PRIMARY KEY,
            title TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id INTEGER,
            store TEXT,
            store_type TEXT DEFAULT 'Official Store',
            delivery_type TEXT DEFAULT 'key',
            region TEXT DEFAULT 'GLOBAL',
            price REAL,
            discount_percent INTEGER,
            store_url TEXT DEFAULT '',
            recorded_at TEXT,
            FOREIGN KEY (app_id) REFERENCES games (app_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store TEXT,
            code TEXT,
            discount_percent INTEGER,
            min_spend REAL DEFAULT 0.0,
            active INTEGER DEFAULT 1
        )
    """)
    # Seed default store vouchers if empty
    cursor.execute("SELECT COUNT(*) FROM store_vouchers")
    if cursor.fetchone()[0] == 0:
        sample_vouchers = [
            ("Fanatical", "FANATICAL10", 10, 5.0, 1),
            ("Green Man Gaming", "GMG5", 5, 10.0, 1),
            ("Eneba", "SIDEQUEST8", 8, 5.0, 1),
            ("Gamivo", "GAMIVO10", 10, 5.0, 1),
        ]
        cursor.executemany(
            "INSERT INTO store_vouchers (store, code, discount_percent, min_spend, active) VALUES (?, ?, ?, ?, ?)",
            sample_vouchers,
        )
    conn.commit()
    conn.close()


def validate_listing(delivery_type: str, raw_listing_name: str = "") -> Optional[str]:
    """Allows 'key' and 'gift' formats. Strictly blocks game accounts."""
    normalized_type = delivery_type.strip().lower()
    combined_text = f"{normalized_type} {raw_listing_name.strip().lower()}"

    if any(keyword in combined_text for keyword in BLOCKED_KEYWORDS):
        return None

    if normalized_type in ALLOWED_DELIVERY_TYPES:
        return normalized_type

    return None


def fetch_steam_price(app_id: int):
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&cc=us&filters=basic,price_overview"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
    except Exception:
        return None

    if not data or not data.get(str(app_id), {}).get("success"):
        return None

    game_data = data[str(app_id)]["data"]

    if game_data.get("is_free") or not game_data.get("price_overview"):
        return None

    title = game_data.get("name", f"App {app_id}")
    price_info = game_data["price_overview"]

    return {
        "title": title,
        "price": price_info["final"] / 100.0,
        "discount_percent": price_info["discount_percent"],
        "delivery_type": "key",
        "store_url": f"https://store.steampowered.com/app/{app_id}/",
    }


def fetch_cheapshark_deals(app_id: int):
    """Fetches live prices across 25+ authorized key stores via CheapShark."""
    url = f"https://www.cheapshark.com/api/1.0/deals?steamAppID={app_id}"
    try:
        response = requests.get(url, timeout=10)
        deals = response.json()
    except Exception:
        return []

    if not isinstance(deals, list):
        return []

    results = []
    for item in deals:
        store_id = str(item.get("storeID", ""))
        store_name = CHEAPSHARK_STORES.get(store_id)
        if not store_name or store_name == "Steam":
            continue
        try:
            sale_price = float(item.get("salePrice", 0))
            savings = round(float(item.get("savings", 0)))
            deal_id = item.get("dealID", "")
            redirect_url = f"https://www.cheapshark.com/redirect?dealID={deal_id}" if deal_id else ""
            if sale_price > 0:
                results.append({
                    "store": store_name,
                    "store_type": "Official Store",
                    "price": sale_price,
                    "discount_percent": savings,
                    "delivery_type": "key",
                    "region": "GLOBAL",
                    "store_url": redirect_url,
                })
        except (ValueError, TypeError):
            continue
    return results


def save_price_snapshot(
    app_id: int,
    title: str,
    store: str,
    price: float,
    discount_percent: int,
    delivery_type: str = "key",
    store_type: str = "Official Store",
    region: str = "GLOBAL",
    store_url: str = "",
    raw_listing_name: str = "",
) -> bool:
    valid_type = validate_listing(delivery_type, raw_listing_name)
    if not valid_type:
        return False

    now_iso = datetime.utcnow().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT OR IGNORE INTO games (app_id, title) VALUES (?, ?)",
        (app_id, title),
    )

    cursor.execute(
        """
        SELECT id FROM price_history
        WHERE app_id = ? AND store = ? AND delivery_type = ? AND region = ? AND recorded_at = ?
        """,
        (app_id, store, valid_type, region, now_iso),
    )
    existing = cursor.fetchone()

    if not existing:
        cursor.execute(
            """
            INSERT INTO price_history
            (app_id, store, store_type, delivery_type, region, price, discount_percent, store_url, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (app_id, store, store_type, valid_type, region, price, discount_percent, store_url, now_iso),
        )
    else:
        cursor.execute(
            """
            UPDATE price_history
            SET price = ?, discount_percent = ?, store_type = ?, store_url = ?
            WHERE id = ?
            """,
            (price, discount_percent, store_type, store_url, existing[0]),
        )

    conn.commit()
    conn.close()
    return True


def log_full_game_snapshot(app_id: int):
    latest_steam = fetch_steam_price(app_id)
    if not latest_steam:
        return None

    title = latest_steam["title"]
    save_price_snapshot(
        app_id=app_id,
        title=title,
        store="Steam",
        price=latest_steam["price"],
        discount_percent=latest_steam["discount_percent"],
        delivery_type="key",
        store_type="Official Store",
        region="GLOBAL",
        store_url=latest_steam["store_url"],
    )

    official_deals = fetch_cheapshark_deals(app_id)
    for deal in official_deals:
        save_price_snapshot(
            app_id=app_id,
            title=title,
            store=deal["store"],
            price=deal["price"],
            discount_percent=deal["discount_percent"],
            delivery_type=deal["delivery_type"],
            store_type=deal["store_type"],
            region=deal["region"],
            store_url=deal["store_url"],
        )

    return latest_steam


def auto_discover_steam_games(limit_per_category: int = 8):
    url = "https://store.steampowered.com/api/featuredcategories/?cc=us"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
    except Exception:
        return []

    discovered_ids = set()
    for category in ["specials", "top_sellers", "new_releases"]:
        items = data.get(category, {}).get("items", [])
        for item in items[:limit_per_category]:
            app_id = item.get("id")
            if app_id and item.get("type") == 0:
                discovered_ids.add(app_id)

    added_titles = []
    for app_id in discovered_ids:
        res = log_full_game_snapshot(app_id)
        if res:
            added_titles.append(res["title"])
        time.sleep(0.4)

    return added_titles


from urllib.parse import quote_plus

def get_next_seasonal_sale(from_date: datetime) -> str:
    year = from_date.year
    upcoming = []
    for month, day in STEAM_SEASONAL_SALES:
        candidate = datetime(year, month, day)
        if candidate < from_date:
            candidate = datetime(year + 1, month, day)
        upcoming.append(candidate)
    next_sale = min(upcoming)
    return next_sale.strftime("%Y-%m-%d")


def apply_best_voucher(store: str, base_price: float, vouchers: list):
    best_price = base_price
    applied_code = None
    voucher_discount = 0

    for v_store, v_code, v_pct, v_min in vouchers:
        if v_store.strip().lower() == store.strip().lower() and base_price >= v_min:
            candidate_price = round(base_price * (1 - v_pct / 100.0), 2)
            if candidate_price < best_price:
                best_price = candidate_price
                applied_code = v_code
                voucher_discount = v_pct

    return best_price, applied_code, voucher_discount


def build_store_url(store: str, title: str, app_id: int, raw_url: str) -> str:
    if raw_url and raw_url.startswith("http"):
        return raw_url

    q = quote_plus(title)
    store_key = (store or "").strip().lower()

    templates = {
        "steam": f"https://steampowered.com{app_id}/",
        "fanatical": f"https://fanatical.com{q}",
        "green man gaming": f"https://greenmangaming.com{q}",
        "humble store": f"https://humblebundle.com{q}",
        "gog": f"https://gog.com{q}",
        "gamesplanet": f"https://gamesplanet.com{q}",
        "gamebillet": f"https://gamebillet.com{q}",
        "cdkeys": f"https://cdkeys.com{q}",
        "eneba": f"https://eneba.com{q}",
        "kinguin": f"https://kinguin.net{q}",
        "g2a": f"https://g2a.com{q}",
        "gamivo": f"https://gamivo.com{q}",
        "instant gaming": f"https://instant-gaming.com{q}",
    }

    return templates.get(store_key, f"https://steampowered.com{app_id}/")


def analyze_game_deals(app_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT title FROM games WHERE app_id = ?", (app_id,))
    game_row = cursor.fetchone()
    if not game_row:
        conn.close()
        return {"error": "Game not tracked yet"}

    title = game_row[0]

    cursor.execute(
        "SELECT store, code, discount_percent, min_spend FROM store_vouchers WHERE active = 1"
    )
    active_vouchers = cursor.fetchall()

    cursor.execute(
        """
        SELECT p.store, p.store_type, p.delivery_type, p.region, p.price, p.discount_percent, p.store_url, p.recorded_at
        FROM price_history p
        INNER JOIN (
            SELECT store, delivery_type, region, MAX(recorded_at) AS max_date
            FROM price_history
            WHERE app_id = ? AND delivery_type IN ('key', 'gift')
            GROUP BY store, delivery_type, region
        ) latest
        ON p.store = latest.store
           AND p.delivery_type = latest.delivery_type
           AND p.region = latest.region
           AND p.recorded_at = latest.max_date
        WHERE p.app_id = ?
        """,
        (app_id, app_id),
    )
    raw_offers = cursor.fetchall()

    enriched_offers = []
    for store, store_type, delivery_type, region, base_price, discount_pct, store_url, recorded_at in raw_offers:
        final_price, coupon_code, coupon_pct = apply_best_voucher(store, base_price, active_vouchers)
        resolved_url = build_store_url(store, title, app_id, store_url)
        enriched_offers.append({
            "store": store,
            "store_type": store_type or "Official Store",
            "delivery_type": delivery_type,
            "region": region or "GLOBAL",
            "base_price": base_price,
            "price": final_price,
            "discount_percent": discount_pct,
            "coupon_code": coupon_code,
            "coupon_discount_percent": coupon_pct,
            "url": resolved_url,
            "store_url": resolved_url,
            "last_checked": recorded_at,
        })


    enriched_offers.sort(key=lambda x: x["price"])
    cheapest_current = enriched_offers[0] if enriched_offers else None

    cursor.execute(
        """
        SELECT price, store, delivery_type, recorded_at
        FROM price_history
        WHERE app_id = ? AND delivery_type IN ('key', 'gift')
        ORDER BY price ASC, recorded_at ASC
        LIMIT 1
        """,
        (app_id,),
    )
    hist_low = cursor.fetchone()

    cursor.execute(
        """
        SELECT recorded_at, discount_percent
        FROM price_history
        WHERE app_id = ? AND store = 'Steam'
        ORDER BY recorded_at ASC
        """,
        (app_id,),
    )
    history = cursor.fetchall()
    conn.close()

    sale_start_dates = []
    was_on_sale = False
    for date_str, discount in history:
        is_on_sale = discount > 0
        if is_on_sale and not was_on_sale:
            sale_start_dates.append(datetime.strptime(date_str, "%Y-%m-%d"))
        was_on_sale = is_on_sale

    today = datetime.utcnow()
    if cheapest_current and cheapest_current["discount_percent"] > 0:
        next_sale_estimate = "On Sale Now"
        confidence = "Active"
    elif len(sale_start_dates) >= 2:
        gaps = [
            (sale_start_dates[i] - sale_start_dates[i - 1]).days
            for i in range(1, len(sale_start_dates))
        ]
        avg_cycle_days = round(sum(gaps) / len(gaps))
        predicted_date = sale_start_dates[-1] + timedelta(days=avg_cycle_days)
        while predicted_date < today:
            predicted_date += timedelta(days=avg_cycle_days)
        next_sale_estimate = predicted_date.strftime("%Y-%m-%d")
        confidence = f"Based on ~{avg_cycle_days}-day publisher sale cycle"
    else:
        next_sale_estimate = get_next_seasonal_sale(today)
        confidence = "Estimated via next major Steam Seasonal Sale"

    return {
        "app_id": app_id,
        "title": title,
        "header_image": f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg",
        "cheapest_current": cheapest_current,
        "active_offers": enriched_offers,
        "historical_low": {
            "price": hist_low[0] if hist_low else None,
            "store": hist_low[1] if hist_low else None,
            "delivery_type": hist_low[2] if hist_low else None,
            "date_hit": hist_low[3] if hist_low else None,
        },
        "next_sale_prediction": {
            "estimated_date": next_sale_estimate,
            "method": confidence,
        },
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM games")
    count = cursor.fetchone()[0]
    conn.close()

    if count == 0:
        for sample_id in [1091500, 1245620, 1145360]:
            log_full_game_snapshot(sample_id)
        auto_discover_steam_games(limit_per_category=5)
    yield


app = FastAPI(title="Sidequest Steam Key & Deal Tracker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/deals")
def list_all_deals():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT app_id FROM games")
    app_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    return [analyze_game_deals(app_id) for app_id in app_ids]


@app.get("/api/deals/{app_id}/history")
def get_price_history(app_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT recorded_at, MIN(price)
        FROM price_history
        WHERE app_id = ? AND delivery_type IN ('key', 'gift')
        GROUP BY recorded_at
        ORDER BY recorded_at ASC
        """,
        (app_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"date": r[0], "price": r[1]} for r in rows]


@app.post("/api/track/{app_id}")
def track_new_game(app_id: int):
    result = log_full_game_snapshot(app_id)
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"Could not find paid Steam game for App ID {app_id}",
        )
    return analyze_game_deals(app_id)


@app.post("/api/discover")
def trigger_discovery():
    added = auto_discover_steam_games(limit_per_category=6)
    return {"status": "completed", "synced_count": len(added), "titles": added}


@app.get("/api/vouchers")
def list_vouchers():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, store, code, discount_percent, min_spend FROM store_vouchers WHERE active = 1")
    rows = cursor.fetchall()
    conn.close()
    return [
        {"id": r[0], "store": r[1], "code": r[2], "discount_percent": r[3], "min_spend": r[4]}
        for r in rows
    ]


@app.post("/api/vouchers")
def add_voucher(voucher: VoucherInput):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO store_vouchers (store, code, discount_percent, min_spend, active) VALUES (?, ?, ?, ?, 1)",
        (voucher.store.strip(), voucher.code.strip().upper(), voucher.discount_percent, voucher.min_spend),
    )
    conn.commit()
    conn.close()
    return {"status": "saved", "code": voucher.code.strip().upper()}


@app.post("/api/offers/ingest")
def ingest_single_offer(offer: StoreOfferInput):
    saved = save_price_snapshot(
        app_id=offer.app_id,
        title=offer.title,
        store=offer.store,
        price=offer.price,
        discount_percent=offer.discount_percent,
        delivery_type=offer.delivery_type,
        store_type=offer.store_type,
        region=offer.region,
        store_url=offer.store_url or "",
        raw_listing_name=offer.raw_listing_name or "",
    )
    if not saved:
        raise HTTPException(
            status_code=400,
            detail="Listing rejected: Sidequest only accepts official Steam keys and gifts (accounts are blocked).",
        )
    return {"status": "accepted", "deal": analyze_game_deals(offer.app_id)}


@app.post("/api/resellers/import-feed")
async def import_reseller_feed(file: UploadFile = File(...)):
    """Parses CSV or JSON reseller partner feeds; accepts key/gift and rejects accounts."""
    content = (await file.read()).decode("utf-8", errors="ignore")
    filename = (file.filename or "").lower()

    records = []
    if filename.endswith(".json"):
        parsed = json.loads(content)
        records = parsed if isinstance(parsed, list) else parsed.get("offers", [])
    else:
        reader = csv.DictReader(io.StringIO(content))
        records = list(reader)

    accepted = 0
    rejected = 0

    for row in records:
        try:
            app_id = int(row.get("app_id", 0))
            title = str(row.get("title", f"App {app_id}")).strip()
            store = str(row.get("store", "Key Reseller")).strip()
            store_type = str(row.get("store_type", "Key Reseller")).strip()
            price = float(row.get("price", 0))
            discount_percent = int(float(row.get("discount_percent", 0)))
            delivery_type = str(row.get("delivery_type", "key")).strip()
            region = str(row.get("region", "GLOBAL")).strip()
            store_url = str(row.get("store_url", "")).strip()
            raw_name = str(row.get("raw_listing_name", title)).strip()

            if app_id <= 0 or price <= 0:
                rejected += 1
                continue

            saved = save_price_snapshot(
                app_id=app_id,
                title=title,
                store=store,
                price=price,
                discount_percent=discount_percent,
                delivery_type=delivery_type,
                store_type=store_type,
                region=region,
                store_url=store_url,
                raw_listing_name=raw_name,
            )
            if saved:
                accepted += 1
            else:
                rejected += 1
        except Exception:
            rejected += 1

    return {
        "status": "completed",
        "accepted_offers": accepted,
        "rejected_accounts_or_invalid": rejected,
    }
