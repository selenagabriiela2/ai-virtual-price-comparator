"""
database.py — Logica SQLite pentru Comparatorul de Preturi
=============================================================
Stocheaza primele 5 oferte din fiecare sesiune de cautare,
descarca imaginile local, si ofera query-uri flexibile.
"""

import sqlite3
import hashlib
import requests
import pandas as pd
from pathlib import Path

DB_PATH   = "comparator.db"
SCHEMA    = "schema.sql"
IMAGES_DIR = Path("db_images")
IMAGES_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────
# CONEXIUNE & INITIALIZARE
# ─────────────────────────────────────────────────────────────

def get_connection() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    """Creaza tabelele daca nu exista (ruleaza la pornirea aplicatiei)."""
    schema_path = Path(SCHEMA)
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema SQL negasita: {SCHEMA}")
    con = get_connection()
    con.executescript(schema_path.read_text(encoding="utf-8"))
    con.commit()
    con.close()


# ─────────────────────────────────────────────────────────────
# IMAGINI LOCALE
# ─────────────────────────────────────────────────────────────

def _url_to_filename(url: str) -> str:
    """Genereaza un nume de fisier unic bazat pe hash-ul URL-ului."""
    h = hashlib.md5(url.encode()).hexdigest()[:12]
    return f"{h}.jpg"


def download_image(url: str) -> str | None:
    """
    Descarca imaginea de la URL si o salveaza local in db_images/.
    Returneaza calea locala sau None daca esueaza.
    Evita descarcarea duplicatelor (verifica daca fisierul exista deja).
    """
    if not url or not url.startswith("http"):
        return None

    local_path = IMAGES_DIR / _url_to_filename(url)

    # Evitam re-descarcarea daca imaginea exista deja
    if local_path.exists():
        return str(local_path)

    try:
        r = requests.get(url, timeout=8, headers={
            "User-Agent": "Mozilla/5.0"
        })
        if r.status_code == 200 and r.content:
            local_path.write_bytes(r.content)
            return str(local_path)
    except Exception:
        pass

    return None


def _save_image_record(con: sqlite3.Connection,
                       local_path: str, original_url: str) -> int | None:
    """Salveaza sau reutilizeaza un record existent de imagine."""
    if not local_path:
        return None

    # Verifica daca imaginea cu acelasi path local exista deja
    row = con.execute(
        "SELECT id FROM images WHERE local_path = ?", (local_path,)
    ).fetchone()

    if row:
        return row["id"]

    cur = con.execute(
        "INSERT INTO images (local_path, original_url) VALUES (?, ?)",
        (local_path, original_url or "")
    )
    return cur.lastrowid


# ─────────────────────────────────────────────────────────────
# CATEGORII
# ─────────────────────────────────────────────────────────────

def _get_or_create_category(con: sqlite3.Connection, name: str | None) -> int | None:
    if not name:
        return None
    row = con.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = con.execute("INSERT INTO categories (name) VALUES (?)", (name,))
    return cur.lastrowid


# ─────────────────────────────────────────────────────────────
# PRODUSE
# ─────────────────────────────────────────────────────────────

def _get_or_create_product(con: sqlite3.Connection,
                            title: str, category_id: int | None) -> int | None:
    row = con.execute("SELECT id FROM products WHERE title = ?", (title,)).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO products (title, category_id) VALUES (?, ?)",
        (title, category_id)
    )
    return cur.lastrowid


# ─────────────────────────────────────────────────────────────
# CAUTARI
# ─────────────────────────────────────────────────────────────

def save_search(search_type: str,
                query_text: str | None = None,
                image_path: str | None = None,
                detected_category: str | None = None) -> int:
    """
    Creeaza o inregistrare de cautare si returneaza ID-ul ei.

    Args:
        search_type: "image" sau "text"
        query_text: textul cautat (pt cautare text)
        image_path: calea locala a imaginii (pt cautare imagine)
        detected_category: categoria detectata automat

    Returns:
        ID-ul cautarii nou create
    """
    con = get_connection()
    cur = con.execute(
        """INSERT INTO searches
           (search_type, query_text, image_path, detected_category)
           VALUES (?, ?, ?, ?)""",
        (search_type, query_text, image_path, detected_category)
    )
    search_id = cur.lastrowid
    con.commit()
    con.close()
    return search_id


# ─────────────────────────────────────────────────────────────
# OFERTE — SALVARE PRIMELE 5
# ─────────────────────────────────────────────────────────────

def save_top5_offers(search_id: int,
                     df: pd.DataFrame,
                     detected_category: str | None = None):
    """
    Salveaza primele 5 oferte (dupa pret crescator) din DataFrame.
    Descarca imaginile thumbnail local.

    Args:
        search_id: ID-ul cautarii (din save_search)
        df: DataFrame cu coloanele standard (title/Denumire, price/Pret,
            source/Magazin, link/Link oferta, image/Imagine, etc.)
        detected_category: categoria detectata (pentru normalizare)
    """
    if df is None or df.empty:
        return

    # Sortam dupa pret si luam primele 5
    col_price = "price" if "price" in df.columns else "Preț"
    df_sorted = df.sort_values(col_price).head(5).reset_index(drop=True)

    con = get_connection()

    category_id = _get_or_create_category(con, detected_category)

    for rank, (_, row) in enumerate(df_sorted.iterrows(), start=1):

        # ── Titlu
        title = (row.get("title") or row.get("Denumire") or "").strip()
        if not title:
            continue

        # ── Produs
        product_id = _get_or_create_product(con, title, category_id)

        # ── Imagine (descarca local)
        img_url = (row.get("image") or row.get("Imagine") or "")
        # Curatam HTML daca imaginea e deja formatata pt tabel
        if img_url and img_url.startswith("<"):
            img_url = ""

        local_img = download_image(img_url) if img_url else None
        img_id = _save_image_record(con, local_img, img_url) if local_img else None

        # ── Disponibilitate
        avail_raw = row.get("in_stock") or row.get("Disponibilitate", "")
        avail_str = str(avail_raw).lower()
        if avail_raw is True or "stoc" in avail_str and "epuizat" not in avail_str:
            availability = "in_stock"
        elif avail_raw is False or "indisponibil" in avail_str or "epuizat" in avail_str:
            availability = "out_of_stock"
        else:
            availability = "unknown"

        # ── Pret
        price_val = row.get("price") or row.get("Preț") or 0
        try:
            price_val = float(price_val)
        except (ValueError, TypeError):
            continue

        # ── Sursa pret
        price_source = row.get("via") or row.get("price_source") or "unknown"

        # ── Duplication Check (Upsert logic)
        url_val = row.get("link") or row.get("Link ofertă") or ""
        source_val = row.get("source") or row.get("Magazin") or ""
        
        existing_offer_id = None
        if url_val:
            existing = con.execute("SELECT id FROM offers WHERE url = ?", (url_val,)).fetchone()
            if existing:
                existing_offer_id = existing["id"]
        else:
            # Fallback daca nu are URL (rar)
            existing = con.execute(
                "SELECT id FROM offers WHERE product_id = ? AND source = ? AND price = ?", 
                (product_id, source_val, price_val)
            ).fetchone()
            if existing:
                existing_offer_id = existing["id"]

        if existing_offer_id:
            # Actualizam pretul, disponibilitatea, timpul si sesiunea curenta
            con.execute(
                """UPDATE offers
                   SET price = ?, availability = ?, search_id = ?, rank_in_search = ?, scraped_at = datetime('now')
                   WHERE id = ?""",
                (price_val, availability, search_id, rank, existing_offer_id)
            )
        else:
            # Inseram ca oferta noua
            con.execute(
                """INSERT INTO offers
                   (search_id, product_id, price, currency, source, url,
                    image_id, availability, price_source, rank_in_search)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    search_id,
                    product_id,
                    price_val,
                    row.get("currency", "RON"),
                    source_val,
                    url_val,
                    img_id,
                    availability,
                    price_source,
                    rank,
                )
            )

    con.commit()
    con.close()


# ─────────────────────────────────────────────────────────────
# QUERY-URI
# ─────────────────────────────────────────────────────────────

def query_offers(
    category:     str | None   = None,
    source:       str | None   = None,
    min_price:    float | None = None,
    max_price:    float | None = None,
    availability: str | None   = None,
    limit:        int   = 200,
) -> pd.DataFrame:
    """
    Query flexibil cu filtre optionale.
    Returneaza un DataFrame gata de afisat in Streamlit.
    """
    con = get_connection()

    sql = """
        SELECT
            p.title            AS "Denumire",
            o.price            AS "Preț",
            o.currency         AS "Monedă",
            o.source           AS "Magazin",
            o.url              AS "Link",
            o.availability      AS "Disponibilitate",
            c.name              AS "Categorie",
            i.local_path        AS "Imagine locală",
            o.scraped_at        AS "Data"
        FROM   offers  o
        JOIN   products p  ON o.product_id = p.id
        LEFT JOIN categories c ON p.category_id = c.id
        LEFT JOIN images i     ON o.image_id    = i.id
        WHERE 1=1
    """
    params: list = []

    if category:
        sql += " AND LOWER(c.name) = LOWER(?)"
        params.append(category)
    if source:
        sql += " AND LOWER(o.source) LIKE LOWER(?)"
        params.append(f"%{source}%")
    if min_price is not None:
        sql += " AND o.price >= ?"
        params.append(min_price)
    if max_price is not None:
        sql += " AND o.price <= ?"
        params.append(max_price)
    if availability:
        sql += " AND o.availability = ?"
        params.append(availability)

    sql += f" ORDER BY o.price ASC LIMIT {int(limit)}"

    df = pd.read_sql_query(sql, con, params=params)
    con.close()
    return df


def get_stats() -> dict:
    """Statistici generale pentru dashboard-ul bazei de date."""
    con = get_connection()
    stats = {}

    stats["total_offers"]   = con.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    stats["total_searches"] = con.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
    stats["total_products"] = con.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    stats["total_images"]   = con.execute(
        "SELECT COUNT(*) FROM images WHERE local_path IS NOT NULL"
    ).fetchone()[0]

    row = con.execute("SELECT MIN(price), MAX(price), AVG(price) FROM offers").fetchone()
    stats["price_min"] = round(row[0] or 0, 2)
    stats["price_max"] = round(row[1] or 0, 2)
    stats["price_avg"] = round(row[2] or 0, 2)

    con.close()
    return stats


def get_categories() -> list[str]:
    """Returneaza lista categoriilor disponibile in baza de date."""
    con = get_connection()
    rows = con.execute(
        "SELECT DISTINCT c.name FROM categories c "
        "JOIN products p ON p.category_id = c.id "
        "JOIN offers o ON o.product_id = p.id "
        "ORDER BY c.name"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def get_sources() -> list[str]:
    """Returneaza lista magazinelor din baza de date."""
    con = get_connection()
    rows = con.execute(
        "SELECT DISTINCT source FROM offers WHERE source != '' ORDER BY source"
    ).fetchall()
    con.close()
    return [r[0] for r in rows]


def delete_old_offers(days: int = 30):
    """Sterge ofertele mai vechi de N zile."""
    con = get_connection()
    con.execute(
        "DELETE FROM offers WHERE scraped_at < datetime('now', ?)",
        (f"-{days} days",)
    )
    con.commit()
    con.close()
