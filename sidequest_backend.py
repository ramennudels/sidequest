import csv
import io
import json
import sqlite3
import time
import requests
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_NAME = "sidequest.db"

ALLOWED_DELIVERY_TYPES = {"key", "gift"}
BLOCKED_KEYWORDS = {"account", "steam account", "shared account", "offline activation", "login"}

STEAM_SEASONAL_SALES = [
    (3, 14),
    (6, 27),
    (11, 27),
    (12, 19),
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
            title TEXT,
            header_image TEXT DEFAULT ''
        )
    """)
    try:
        cursor.execute("ALTER TABLE games ADD COLUMN header_image TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

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
    normalized_type = delivery_type.strip().lower()
    combined_text = f"{normalized_type} {raw_listing_name.strip().lower()}"

    if any(keyword in combined_text for keyword in BLOCKED_KEYWORDS):
        return None

    if normalized_type in ALLOWED_DELIVERY_TYPES:
        return normalized_type

    return None
def fetch_steam_price(app_id: int):
    url = f"https://steampowered.com{app_id}&cc=us&filters=basic,price_overview"
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
        "header_image": game_data.get("header_image", ""),
        "price": price_info["final"] / 100.0,
        "discount_percent": price_info["discount_percent"],
        "delivery_type": "key",
        "store_url": f"https://steampowered.com{app_id}/",
    }


def fetch_cheapshark_deals(app_id: int):
    url = f"https://cheapshark.com{app_id}"
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
            redirect_url = f"https://cheapshark.com{deal_id}" if deal_id else ""
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


def log_full_game_snapshot(app_id: int):
    steam_info = fetch_steam_price(app_id)
    if not steam_info:
        return None

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    title = steam_info["title"]
    header_image = steam_info.get("header_image", "")
    cursor.execute(
        "INSERT OR REPLACE INTO games (app_id, title, header_image) VALUES (?, ?, ?)",
        (app_id, title, header_image),
    )

    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        """
        INSERT INTO price_history
        (app_id, store, store_type, delivery_type, region, price, discount_percent, store_url, recorded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            app_id,
            "Steam",
            "Official Store",
            "key",
            "GLOBAL",
            steam_info["price"],
            steam_info["discount_percent"],
            steam_info["store_url"],
            now_iso,
        ),
    )

    cheapshark_offers = fetch_cheapshark_deals(app_id)
    for offer in cheapshark_offers:
        cursor.execute(
            """
            INSERT INTO price_history
            (app_id, store, store_type, delivery_type, region, price, discount_percent, store_url, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                app_id,
                offer["store"],
                offer["store_type"],
                offer["delivery_type"],
                offer["region"],
                offer["price"],
                offer["discount_percent"],
                offer["store_url"],
                now_iso,
            ),
        )

    conn.commit()
    conn.close()
    return {"app_id": app_id, "title": title, "stores_logged": 1 + len(cheapshark_offers)}


def auto_discover_steam_games(limit_per_category: int = 8):
    url = "https://steampowered.com"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
    except Exception:
        return []

    seen_ids = set()
    for section in ("specials", "top_sellers", "new_releases"):
        items = data.get(section, {}).get("items", [])
        for item in items[:limit_per_category]:
            app_id = item.get("id")
            if app_id and app_id not in seen_ids:
                seen_ids.add(app_id)

    logged = []
    for app_id in seen_ids:
        res = log_full_game_snapshot(app_id)
        if res:
            logged.append(res)
        time.sleep(0.25)
    return logged


def get_next_seasonal_sale(today: datetime) -> str:
    year = today.year
    upcoming_dates = []
    for month, day in STEAM_SEASONAL_SALES:
        sale_date = datetime(year, month, day)
        if sale_date < today:
            sale_date = datetime(year + 1, month, day)
        upcoming_dates.append(sale_date)
    return min(upcoming_dates).strftime("%Y-%m-%d")


def build_store_url(store: str, title: str, app_id: int) -> str:
    s = store.strip().lower()
    q = requests.utils.quote(title)
    if s == "steam":
        return f"https://steampowered.com{app_id}/"
    if "fanatical" in s:
        return f"https://fanatical.com{q}"
    if "green man gaming" in s or "gmg" in s:
        return f"https://greenmangaming.com{q}"
    if "humble" in s:
        return f"https://humblebundle.com{q}"
    if "gog" in s:
        return f"https://gog.com{q}"
    if "eneba" in s:
        return f"https://eneba.com{q}"
    if "cdkeys" in s or "loaded" in s:
        return f"https://cdkeys.com{q}"
    if "gamivo" in s:
        return f"https://gamivo.com{q}"
    if "kinguin" in s:
        return f"https://kinguin.net{q}"
    if "instant gaming" in s:
        return f"https://instant-gaming.com{q}"
    return f"https://google.com{q}+{requests.utils.quote(store)}+pc+key"
def analyze_game_deals(app_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("SELECT title, header_image FROM games WHERE app_id = ?", (app_id,))
    game_row = cursor.fetchone()
    if not game_row:
        conn.close()
        return {"error": "Game not tracked yet"}

     title = game_row[0]
    saved_header = game_row[1] if game_row[1] else f"https://steamstatic.com{app_id}/header.jpg"


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
        best_price = base_price
        applied_code = None
        applied_pct = 0

        for v_store, v_code, v_pct, v_min in active_vouchers:
            if v_store.strip().lower() == store.strip().lower() and base_price >= v_min:
                discounted = round(base_price * (1 - v_pct / 100.0), 2)
                if discounted < best_price:
                    best_price = discounted
                    applied_code = v_code
                    applied_pct = v_pct

        final_url = store_url if store_url else build_store_url(store, title, app_id)
        enriched_offers.append({
            "store": store,
            "store_type": store_type,
            "delivery_type": delivery_type,
            "region": region,
            "base_price": base_price,
            "price": best_price,
            "discount_percent": discount_pct,
            "coupon_code": applied_code,
            "coupon_discount_percent": applied_pct,
            "url": final_url,
            "store_url": final_url,
            "last_checked": recorded_at[:10],
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
    low_row = cursor.fetchone()
    conn.close()

    historical_low = (
        {
            "price": low_row[0],
            "store": low_row[1],
            "delivery_type": low_row[2],
            "date_hit": low_row[3][:10],
        }
        if low_row
        else {"price": 0.0, "store": "N/A", "delivery_type": "key", "date_hit": "N/A"}
    )


    today = datetime.now()
    if cheapest_current and cheapest_current["discount_percent"] > 0:
        next_sale_estimate = "On Sale Now"
        confidence = "Active"
    else:
        next_sale_estimate = get_next_seasonal_sale(today)
        confidence = "Estimated via next major Steam Seasonal Sale"

    return {
        "app_id": app_id,
        "title": title,
        "header_image": saved_header,
        "cheapest_current": cheapest_current,
        "active_offers": enriched_offers,
        "historical_low": historical_low,
        "next_sale_prediction": {
            "estimated_date": next_sale_estimate,
            "method": confidence,
        },
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Sidequest Steam Key & Deal Tracker API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root_status():
    return {"status": "Sidequest API is online", "deals_endpoint": "/api/deals"}


@app.get("/api/deals")
def list_all_deals():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT app_id FROM games ORDER BY title ASC")
    rows = cursor.fetchall()
    conn.close()
    return [analyze_game_deals(r[0]) for r in rows]



@app.get("/api/deals/{app_id}")
def get_game_deal(app_id: int):
    result = analyze_game_deals(app_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/api/history/{app_id}")
def get_price_history(app_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT store, store_type, delivery_type, price, recorded_at
        FROM price_history
        WHERE app_id = ?
        ORDER BY recorded_at ASC
        """,
        (app_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return {
        "app_id": app_id,
       "history": [
            {
                "store": r[0],
                "store_type": r[1],
                "delivery_type": r[2],
                "price": r[3],
                "date": r[4][:10],
            }
            for r in rows
        ],


@app.post("/api/track/{app_id}")
def track_new_game(app_id: int):
    logged = log_full_game_snapshot(app_id)
    if not logged:
        raise HTTPException(status_code=400, detail="Could not fetch Steam price (may be free-to-play or invalid ID).")
    return analyze_game_deals(app_id)


@app.post("/api/discover")
def trigger_discovery():
    discovered = auto_discover_steam_games(limit_per_category=8)
    return {"synced_games": len(discovered), "details": discovered}


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
    return {"status": "Voucher saved", "code": voucher.code.strip().upper()}


@app.post("/api/offers/upload")
async def upload_reseller_feed(file: UploadFile = File(...)):
    content = (await file.read()).decode("utf-8", errors="ignore")
    records = []

    if file.filename.lower().endswith(".json"):
        parsed = json.loads(content)
        records = parsed if isinstance(parsed, list) else parsed.get("offers", [])
    else:
        reader = csv.DictReader(io.StringIO(content))
        records = list(reader)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    imported = 0
    blocked = 0

    for row in records:
        delivery = str(row.get("delivery_type", ""))
        raw_name = str(row.get("raw_listing_name", row.get("title", "")))
        valid_type = validate_listing(delivery, raw_name)
        if not valid_type:
            blocked += 1
            continue

        try:
            app_id = int(row["app_id"])
            title = str(row.get("title", f"App {app_id}")).strip()
            store = str(row["store"]).strip()
            store_type = str(row.get("store_type", "Key Reseller")).strip()
            region = str(row.get("region", "GLOBAL")).strip().upper()
            price = float(row["price"])
            discount_pct = int(float(row.get("discount_percent", 0)))
            store_url = str(row.get("store_url", "")).strip()
        except (KeyError, ValueError, TypeError):
            continue

        cursor.execute(
            "INSERT OR IGNORE INTO games (app_id, title, header_image) VALUES (?, ?, ?)",
            (app_id, title, ""),
        )
        cursor.execute(
            """
            INSERT INTO price_history
            (app_id, store, store_type, delivery_type, region, price, discount_percent, store_url, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (app_id, store, store_type, valid_type, region, price, discount_pct, store_url, now_iso),
        )
        imported += 1

    conn.commit()
    conn.close()
    return {"imported": imported, "blocked_accounts": blocked}
