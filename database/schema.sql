-- ============================================================
-- Schema SQLite — Comparator de Preturi
-- ============================================================

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE   -- ex: "tricou", "blugi", "geaca"
);

CREATE TABLE IF NOT EXISTS searches (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    search_type       TEXT NOT NULL,       -- "image" sau "text"
    query_text        TEXT,                -- textul cautat (NULL daca e imagine)
    image_path        TEXT,                -- calea locala imaginii (NULL daca e text)
    detected_category TEXT,               -- categoria detectata automat
    created_at        DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS products (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    title         TEXT NOT NULL UNIQUE,
    category_id   INTEGER REFERENCES categories(id),
    first_seen_at DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS images (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    local_path     TEXT NOT NULL,         -- ex: "db_images/abc123.jpg"
    original_url   TEXT,                  -- URL-ul original
    mime_type      TEXT DEFAULT 'image/jpeg',
    downloaded_at  DATETIME DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS offers (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id    INTEGER NOT NULL REFERENCES searches(id),
    product_id   INTEGER REFERENCES products(id),
    price        REAL NOT NULL,
    currency     TEXT DEFAULT 'RON',
    source       TEXT,
    url          TEXT,
    image_id     INTEGER REFERENCES images(id),
    availability TEXT,               -- "in_stock", "out_of_stock", "unknown"
    price_source TEXT,               -- "page", "serpapi", "lens_imagine"
    rank_in_search INTEGER,          -- pozitia ofertei (1-5) din sesiunea respectiva
    scraped_at   DATETIME DEFAULT (datetime('now'))
);

-- Index pentru query-uri frecvente
CREATE INDEX IF NOT EXISTS idx_offers_price    ON offers(price);
CREATE INDEX IF NOT EXISTS idx_offers_source   ON offers(source);
CREATE INDEX IF NOT EXISTS idx_offers_search   ON offers(search_id);
CREATE INDEX IF NOT EXISTS idx_offers_scraped  ON offers(scraped_at);
