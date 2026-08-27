import sqlite3
from datetime import datetime, timezone


DB_NAME = "price_hawk.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def now():
    return datetime.now(timezone.utc).isoformat()


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


def get_or_create_user(telegram_chat_id, name=None):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id
        FROM users
        WHERE telegram_chat_id = ?
        """,
        (telegram_chat_id,)
    )

    user = cursor.fetchone()

    if user:
        connection.close()
        return user[0]

    cursor.execute(
        """
        INSERT INTO users (
            telegram_chat_id,
            name,
            created_at
        )
        VALUES (?, ?, ?)
        """,
        (telegram_chat_id, name, now())
    )

    user_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return user_id


def get_telegram_chat_id(user_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT telegram_chat_id
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    )

    result = cursor.fetchone()

    connection.close()

    if result is None:
        return None

    return result[0]


def create_watch(
    user_id,
    retailer,
    url,
    target_price,
    product_id=None,
    product_name=None,
    current_price=None,
    currency=None,
    available=None
):
    connection = get_connection()
    cursor = connection.cursor()

    timestamp = now()

    cursor.execute(
        """
        INSERT INTO watches (
            user_id,
            retailer,
            url,
            product_id,
            product_name,
            target_price,
            current_price,
            currency,
            available,
            created_at,
            last_checked
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            retailer,
            url,
            product_id,
            product_name,
            target_price,
            current_price,
            currency,
            available,
            timestamp,
            timestamp
        )
    )

    watch_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return watch_id


def get_watches_for_user(user_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            retailer,
            url,
            product_name,
            target_price,
            current_price,
            currency,
            available,
            alert_active,
            last_checked
        FROM watches
        WHERE user_id = ?
        ORDER BY id
        """,
        (user_id,)
    )

    watches = cursor.fetchall()

    connection.close()

    return watches


def get_watch_for_user(user_id, watch_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            retailer,
            url,
            product_name,
            target_price,
            current_price,
            currency,
            available,
            alert_active,
            last_checked
        FROM watches
        WHERE id = ? AND user_id = ?
        """,
        (watch_id, user_id)
    )

    watch = cursor.fetchone()

    connection.close()

    return watch


def delete_watch(user_id, watch_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM watches
        WHERE id = ? AND user_id = ?
        """,
        (watch_id, user_id)
    )

    deleted = cursor.rowcount > 0

    connection.commit()
    connection.close()

    return deleted


def get_all_active_watches():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            user_id,
            retailer,
            url,
            product_id,
            product_name,
            target_price,
            current_price,
            currency,
            available,
            alert_active,
            last_checked
        FROM watches
        ORDER BY id
        """
    )

    watches = cursor.fetchall()

    connection.close()

    return watches


def update_watch_price(
    watch_id,
    price,
    currency,
    available,
    checked_at
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE watches
        SET
            current_price = ?,
            currency = ?,
            available = ?,
            last_checked = ?
        WHERE id = ?
        """,
        (
            price,
            currency,
            available,
            checked_at,
            watch_id
        )
    )

    connection.commit()
    connection.close()


def set_alert_active(watch_id, active):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE watches
        SET alert_active = ?
        WHERE id = ?
        """,
        (1 if active else 0, watch_id)
    )

    connection.commit()
    connection.close()


def get_latest_price_interval(watch_id):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            price,
            started_at,
            ended_at
        FROM price_intervals
        WHERE watch_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (watch_id,)
    )

    interval = cursor.fetchone()

    connection.close()

    return interval

def get_price_history_for_user(user_id, watch_id, limit=50):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            pi.id,
            pi.price,
            pi.started_at,
            pi.ended_at
        FROM price_intervals pi
        INNER JOIN watches w
            ON pi.watch_id = w.id
        WHERE
            pi.watch_id = ?
            AND w.user_id = ?
        ORDER BY pi.started_at DESC
        LIMIT ?
        """,
        (
            watch_id,
            user_id,
            limit,
        )
    )

    history = cursor.fetchall()

    connection.close()

    return history

def create_price_interval(
    watch_id,
    price,
    started_at
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO price_intervals (
            watch_id,
            price,
            started_at,
            ended_at
        )
        VALUES (?, ?, ?, NULL)
        """,
        (
            watch_id,
            price,
            started_at
        )
    )

    connection.commit()
    connection.close()


def close_price_interval(
    interval_id,
    ended_at
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE price_intervals
        SET ended_at = ?
        WHERE id = ?
        """,
        (
            ended_at,
            interval_id
        )
    )

    connection.commit()
    connection.close()


def update_daily_summary(
    watch_id,
    date,
    price
):
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            lowest_price,
            highest_price
        FROM daily_summaries
        WHERE watch_id = ? AND date = ?
        """,
        (watch_id, date)
    )

    summary = cursor.fetchone()

    if summary is None:
        cursor.execute(
            """
            INSERT INTO daily_summaries (
                watch_id,
                date,
                lowest_price,
                highest_price,
                closing_price
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                watch_id,
                date,
                price,
                price,
                price
            )
        )

    else:
        lowest_price, highest_price = summary

        cursor.execute(
            """
            UPDATE daily_summaries
            SET
                lowest_price = ?,
                highest_price = ?,
                closing_price = ?
            WHERE watch_id = ? AND date = ?
            """,
            (
                min(lowest_price, price),
                max(highest_price, price),
                price,
                watch_id,
                date
            )
        )

    connection.commit()
    connection.close()


if __name__ == "__main__":
    initialize_database()
    print("🟢 Price Hawk database initialized.")