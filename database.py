import sqlite3
from datetime import datetime, timezone


DB_NAME = "price_hawk.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def initialize_database():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_chat_id INTEGER UNIQUE NOT NULL,
            name TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            retailer TEXT NOT NULL,
            url TEXT NOT NULL,
            product_id TEXT,
            product_name TEXT,
            target_price REAL NOT NULL,
            current_price REAL,
            currency TEXT,
            available INTEGER,
            alert_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_checked TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_intervals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watch_id INTEGER NOT NULL,
            price REAL NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            FOREIGN KEY (watch_id) REFERENCES watches(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watch_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            lowest_price REAL NOT NULL,
            highest_price REAL NOT NULL,
            closing_price REAL NOT NULL,
            UNIQUE(watch_id, date),
            FOREIGN KEY (watch_id) REFERENCES watches(id)
        )
    """)

    connection.commit()
    connection.close()


if __name__ == "__main__":
    initialize_database()
    print("🟢 Price Hawk database initialized.")