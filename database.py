import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional
from config import DATABASE_PATH

logger = logging.getLogger(__name__)


def get_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database with required tables."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id TEXT PRIMARY KEY,
            account_id TEXT,
            amount REAL,
            date TEXT,
            merchant_name TEXT,
            category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id TEXT UNIQUE,
            original_amount REAL,
            adjusted_amount REAL,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (transaction_id) REFERENCES transactions(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_synced TIMESTAMP,
            cursor TEXT
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully")


def upsert_transaction(transaction_id: str, account_id: str, amount: float,
                       date: str, merchant_name: str, category: str):
    """Insert or update a transaction."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO transactions (id, account_id, amount, date, merchant_name, category)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            amount = excluded.amount,
            merchant_name = excluded.merchant_name,
            category = excluded.category
    """, (transaction_id, account_id, amount, date, merchant_name, category))

    conn.commit()
    conn.close()


def get_effective_amount(transaction_id: str) -> float:
    """Returns adjusted amount if exists, else original amount."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.amount, a.adjusted_amount
        FROM transactions t
        LEFT JOIN adjustments a ON t.id = a.transaction_id
        WHERE t.id = ?
    """, (transaction_id,))

    row = cursor.fetchone()
    conn.close()

    if row is None:
        return 0.0

    return row['adjusted_amount'] if row['adjusted_amount'] is not None else row['amount']


def get_spend_totals() -> dict:
    """Returns dict with day/week/month totals using effective amounts."""
    conn = get_connection()
    cursor = conn.cursor()

    today = datetime.now().date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    def get_total_for_period(start_date: str, end_date: str) -> float:
        cursor.execute("""
            SELECT SUM(
                CASE
                    WHEN a.adjusted_amount IS NOT NULL THEN a.adjusted_amount
                    ELSE t.amount
                END
            ) as total
            FROM transactions t
            LEFT JOIN adjustments a ON t.id = a.transaction_id
            WHERE t.date >= ? AND t.date <= ? AND t.amount > 0
        """, (start_date, end_date))
        row = cursor.fetchone()
        return row['total'] or 0.0

    totals = {
        'day': get_total_for_period(str(today), str(today)),
        'week': get_total_for_period(str(week_start), str(today)),
        'month': get_total_for_period(str(month_start), str(today)),
        'last_synced': get_last_synced()
    }

    conn.close()
    return totals


def add_adjustment(transaction_id: str, new_amount: float, reason: str) -> bool:
    """Add or update an adjustment for a transaction."""
    conn = get_connection()
    cursor = conn.cursor()

    # Get original amount
    cursor.execute("SELECT amount FROM transactions WHERE id = ?", (transaction_id,))
    row = cursor.fetchone()

    if row is None:
        conn.close()
        return False

    original_amount = row['amount']

    cursor.execute("""
        INSERT INTO adjustments (transaction_id, original_amount, adjusted_amount, reason)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(transaction_id) DO UPDATE SET
            adjusted_amount = excluded.adjusted_amount,
            reason = excluded.reason,
            created_at = CURRENT_TIMESTAMP
    """, (transaction_id, original_amount, new_amount, reason))

    conn.commit()
    conn.close()
    logger.info(f"Adjustment added: {transaction_id} from {original_amount} to {new_amount}")
    return True


def find_transaction_by_merchant(merchant_name: str, date_hint: Optional[str] = None) -> list:
    """Find transactions by merchant name with optional date hint."""
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT t.id, t.account_id, t.amount, t.date, t.merchant_name, t.category,
               a.adjusted_amount
        FROM transactions t
        LEFT JOIN adjustments a ON t.id = a.transaction_id
        WHERE LOWER(t.merchant_name) LIKE LOWER(?)
    """
    params = [f"%{merchant_name}%"]

    if date_hint:
        # Parse date hint like "yesterday", "last week", or specific date
        hint_date = parse_date_hint(date_hint)
        if hint_date:
            query += " AND t.date = ?"
            params.append(hint_date)

    query += " ORDER BY t.date DESC LIMIT 10"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def parse_date_hint(hint: str) -> Optional[str]:
    """Parse natural language date hints."""
    today = datetime.now().date()
    hint_lower = hint.lower().strip()

    if hint_lower in ['today', 'now']:
        return str(today)
    elif hint_lower == 'yesterday':
        return str(today - timedelta(days=1))
    elif hint_lower == 'last week':
        return str(today - timedelta(days=7))
    else:
        # Try to parse as a date
        for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y']:
            try:
                return str(datetime.strptime(hint, fmt).date())
            except ValueError:
                continue
    return None


def get_recent_transactions(limit: int = 10) -> list:
    """Get the most recent transactions."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.id, t.account_id, t.amount, t.date, t.merchant_name, t.category,
               a.adjusted_amount
        FROM transactions t
        LEFT JOIN adjustments a ON t.id = a.transaction_id
        ORDER BY t.date DESC, t.created_at DESC
        LIMIT ?
    """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_transaction_by_id(transaction_id: str) -> Optional[dict]:
    """Get a single transaction by ID."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT t.id, t.account_id, t.amount, t.date, t.merchant_name, t.category,
               a.adjusted_amount, a.reason as adjustment_reason
        FROM transactions t
        LEFT JOIN adjustments a ON t.id = a.transaction_id
        WHERE t.id = ?
    """, (transaction_id,))

    row = cursor.fetchone()
    conn.close()

    return dict(row) if row else None


def update_sync_state(cursor_value: Optional[str] = None):
    """Update the last sync timestamp and cursor."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO sync_state (id, last_synced, cursor)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            last_synced = excluded.last_synced,
            cursor = excluded.cursor
    """, (datetime.now().isoformat(), cursor_value))

    conn.commit()
    conn.close()


def get_sync_cursor() -> Optional[str]:
    """Get the Plaid sync cursor."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT cursor FROM sync_state WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    return row['cursor'] if row else None


def get_last_synced() -> Optional[str]:
    """Get the last sync timestamp."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT last_synced FROM sync_state WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    return row['last_synced'] if row else None
