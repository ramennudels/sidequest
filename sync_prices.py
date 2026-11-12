import sqlite3
import time
from datetime import datetime
from sidequest_backend import (
    DB_NAME,
    init_db,
    log_full_game_snapshot,
    auto_discover_steam_games,
)

LOG_FILE = "sync_log.txt"


def write_log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_scheduled_sync():
    write_log("Starting Sidequest automated price sync...")
    init_db()

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT app_id, title FROM games")
    tracked_games = cursor.fetchall()
    conn.close()

    write_log(f"Refreshing {len(tracked_games)} tracked games across Steam & 25+ key stores...")
    for app_id, title in tracked_games:
        res = log_full_game_snapshot(app_id)
        if res:
            write_log(f"  Updated: {title} (App ID {app_id})")
        else:
            write_log(f"  Skipped/Unavailable: {title} (App ID {app_id})")
        time.sleep(0.5)

    write_log("Discovering new Steam Specials & Top Sellers...")
    new_titles = auto_discover_steam_games(limit_per_category=6)
    write_log(f"Auto-discovery finished. Synced {len(new_titles)} trending titles.")
    write_log("Sidequest sync complete!\n")


if __name__ == "__main__":
    run_scheduled_sync()
