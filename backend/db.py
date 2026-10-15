"""SQLite storage. Everything lives in one file: data/paper_trading.db."""
import os
import sqlite3
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("PTA_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.path.join(DATA_DIR, "paper_trading.db")

STARTING_CASH = 100_000.00

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    starting_cash REAL NOT NULL,
    cash          REAL NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);

-- Current holdings. cost_basis is the total dollars paid for the shares still held.
CREATE TABLE IF NOT EXISTS positions (
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol     TEXT NOT NULL,
    shares     REAL NOT NULL,
    cost_basis REAL NOT NULL,
    PRIMARY KEY (user_id, symbol)
);

-- Every filled order. This is the source of truth for rebuilding performance history.
CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    shares       REAL NOT NULL,
    price        REAL NOT NULL,
    total        REAL NOT NULL,
    realized_pl  REAL,
    executed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS trades_user_time ON trades(user_id, executed_at);

-- Orders waiting to fill: limit orders, and market orders placed while the market was closed
-- (queued until the next open). Open buy orders reserve cash; open sell orders reserve shares.
CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type    TEXT NOT NULL DEFAULT 'limit' CHECK (order_type IN ('market', 'limit')),
    shares        REAL NOT NULL,   -- for a dollar-amount market order, an estimate until it fills
    amount        REAL,            -- dollar-amount market orders: the dollars to buy or sell
    limit_price   REAL,            -- limit orders only
    est_price     REAL,            -- market orders: the price when queued, used to hold cash
    time_in_force TEXT NOT NULL CHECK (time_in_force IN ('day', 'gtc')),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'filled', 'cancelled', 'expired')),
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    expires_at    TEXT,
    closed_at     TEXT,
    trade_id      INTEGER REFERENCES trades(id),
    note          TEXT
);
CREATE INDEX IF NOT EXISTS orders_open ON orders(status, user_id);

-- Stock splits and cash dividends applied to an account. Splits change share counts;
-- dividends add cash. ex_date is the exchange date (YYYY-MM-DD) the action took effect.
CREATE TABLE IF NOT EXISTS corporate_actions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol     TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('split', 'dividend')),
    ex_date    TEXT NOT NULL,
    ratio      REAL,            -- split: new shares per old share
    per_share  REAL,            -- dividend: cash per share
    shares     REAL NOT NULL,   -- shares held just before the action
    amount     REAL,            -- dividend: cash credited
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (user_id, symbol, kind, ex_date)
);

-- Quarterly deposits: 2% of the account value at the last close before each payout date.
CREATE TABLE IF NOT EXISTS deposits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    pay_date    TEXT NOT NULL,   -- YYYY-MM-DD, always the 1st of a month; credited at midnight US Eastern
    basis_date  TEXT NOT NULL,   -- the market close the amount was based on
    basis_value REAL NOT NULL,   -- account value at that close
    rate        REAL NOT NULL,
    amount      REAL NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (user_id, pay_date)
);

CREATE TABLE IF NOT EXISTS watchlist (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol   TEXT NOT NULL,
    added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (user_id, symbol)
);
"""


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        # Databases created before limit orders existed lack trades.order_type.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(trades)")}
        if "order_type" not in cols:
            conn.execute("ALTER TABLE trades ADD COLUMN order_type TEXT NOT NULL DEFAULT 'market'")
        # Orders created before queued market orders existed: rebuild with the new columns.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(orders)")}
        if "order_type" not in cols:
            conn.executescript("""
                ALTER TABLE orders RENAME TO orders_old;
                DROP INDEX IF EXISTS orders_open;
            """ + SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS orders"):SCHEMA.index("CREATE INDEX IF NOT EXISTS orders_open")] + """
                INSERT INTO orders (id, user_id, symbol, side, order_type, shares, limit_price, time_in_force,
                                    status, created_at, expires_at, closed_at, trade_id)
                    SELECT id, user_id, symbol, side, 'limit', shares, limit_price, time_in_force,
                           status, created_at, expires_at, closed_at, trade_id FROM orders_old;
                DROP TABLE orders_old;
                CREATE INDEX IF NOT EXISTS orders_open ON orders(status, user_id);
            """)
        # Dividend reinvesting (on by default), and the purchase each reinvested dividend made.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "reinvest_dividends" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN reinvest_dividends INTEGER NOT NULL DEFAULT 1")
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(corporate_actions)")}
        if "reinvest_trade_id" not in cols:
            conn.execute("ALTER TABLE corporate_actions ADD COLUMN reinvest_trade_id INTEGER REFERENCES trades(id)")
        # Price when a stock was added to the watchlist, for "since added" performance.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(watchlist)")}
        if "added_price" not in cols:
            conn.execute("ALTER TABLE watchlist ADD COLUMN added_price REAL")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
