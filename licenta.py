# =========================
# IMPORTURI
# =========================
import requests
import time
import json
import warnings
from pathlib import Path
import os
import re
import unicodedata
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from urllib.parse import urlparse

import google.generativeai as genai
import pandas as pd
import cloudinary
import cloudinary.uploader

warnings.filterwarnings("ignore", category=FutureWarning)

# =========================
# LOAD .env (OBLIGATORIU)
# =========================
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_PATH, override=True)

# =========================
# CONFIGURĂRI API
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

genai.configure(api_key=GEMINI_API_KEY)


# =========================
# DIRECTOARE
# =========================
BASE_DIR = Path(__file__).parent


# =========================
# MODELE GEMINI
# =========================
model_vision = genai.GenerativeModel("models/gemini-2.5-flash")
model_text = genai.GenerativeModel("models/gemini-2.5-flash")


def lens(image_path: str) -> dict:
    upload = cloudinary.uploader.upload(
        image_path,
        folder="lens_products",
        resource_type="image"
    )

    image_url = upload["secure_url"]

    params = {
        "engine": "google_lens",
        "url": image_url,
        "api_key": SERPAPI_KEY,
        "hl": "ro",
        "country": "RO",   # SerpAPI folosește RO (în exemplul tău)
        "num": 100
    }

    r = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
    data = r.json()

    # ia DOAR visual_matches din răspunsul standard
    results = data.get("visual_matches", [])

    return {
        "cloudinary_url": image_url,     # ✅ ca să verifici
        "raw": data,                     # opțional: debug complet
        "visual_matches": results
    }


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.7,en;q=0.6",
}

PRICE_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*|\d+)(?:[.,](\d{2}))?\s*(lei|ron|eur|€|usd|\$|gbp|£)\b",
    re.IGNORECASE
)


def _normalize_number(int_part: str, dec_part: str | None):
    cleaned = int_part.replace(".", "").replace(" ", "")
    if dec_part:
        return float(f"{cleaned}.{dec_part}")
    return float(cleaned)


def _extract_price_from_text(text: str):
    # Iterăm prin toate potrivirile pentru a evita pragurile de transport (ex: 250 RON)
    for m in PRICE_RE.finditer(text or ""):
        # Verificăm contextul (30 caractere înainte)
        start = m.start()
        context = text[max(0, start - 30):start].lower()

        # Ignorăm dacă e legat de transport/comenzi minime
        if any(x in context for x in ["peste", "comenzi", "transport", "livrare", "gratuit"]):
            continue

        val = _normalize_number(m.group(1), m.group(2))
        cur = m.group(3).upper()
        cur = {"LEI": "RON", "RON": "RON", "€": "EUR", "EUR": "EUR",
               "$": "USD", "USD": "USD", "£": "GBP", "GBP": "GBP"}.get(cur, cur)

        return {"value": val, "currency": cur, "raw": m.group(0)}

    return None


# =========================================================
# 🔥 JSON-LD (PREȚ + STOCK)
# =========================================================
def _extract_price_from_jsonld(soup: BeautifulSoup):
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for sc in scripts:
        if not sc.string:
            continue
        try:
            data = json.loads(sc.string.strip())
        except Exception:
            continue

        candidates = data if isinstance(data, list) else [data]

        for obj in candidates:
            if not isinstance(obj, dict):
                continue

            offers = obj.get("offers")
            if not offers:
                continue

            offers_list = offers if isinstance(offers, list) else [offers]

            for off in offers_list:
                if not isinstance(off, dict):
                    continue

                price = off.get("price")
                currency = off.get("priceCurrency")
                availability = off.get("availability")

                if price is None:
                    continue

                try:
                    val = float(str(price).replace(",", "."))
                except Exception:
                    continue

                # 🔥 STOCK
                in_stock = None
                if availability:
                    # Handle case where availability might be a list
                    if isinstance(availability, list):
                        availability = availability[0] if availability else ""
                    availability = str(availability).lower()
                    if "instock" in availability:
                        in_stock = True
                    elif "outofstock" in availability:
                        in_stock = False

                return {
                    "value": val,
                    "currency": (currency or "").upper() or None,
                    "raw": f"{price} {currency or ''}".strip(),
                    "in_stock": in_stock
                }

    return None


# =========================================================
# 🔥 META (PREȚ + STOCK)
# =========================================================
def _extract_price_from_meta(soup: BeautifulSoup):
    for prop in ["product:price:amount", "og:price:amount"]:
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            try:
                val = float(tag["content"].replace(",", "."))
                cur_tag = soup.find("meta", attrs={"property": "product:price:currency"}) \
                       or soup.find("meta", attrs={"property": "og:price:currency"})
                cur = cur_tag["content"].upper() if cur_tag and cur_tag.get("content") else None

                # 🔥 availability meta
                stock_tag = soup.find("meta", attrs={"property": "product:availability"})
                in_stock = None
                if stock_tag and stock_tag.get("content"):
                    stock_val = stock_tag["content"].lower()
                    if "instock" in stock_val:
                        in_stock = True
                    elif "outofstock" in stock_val:
                        in_stock = False

                return {
                    "value": val,
                    "currency": cur,
                    "raw": tag["content"],
                    "in_stock": in_stock
                }

            except Exception:
                pass

    return None


# =========================================================
# 🔥 FUNCȚIE PRINCIPALĂ PAGINĂ PRODUS
# =========================================================
def get_price_from_product_page(url: str, timeout: int = 20):
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
    except Exception as e:
        return {"error": str(e)}

    text = soup.get_text(" ", strip=True)
    text_lower = text.lower()

    # 1️⃣ JSON-LD
    p = _extract_price_from_jsonld(soup)
    if p:
        if p.get("currency") == "EUR" and re.search(r'\b(lei|ron)\b', text_lower):
            p["currency"] = "RON"
        return p

    # 2️⃣ META
    p = _extract_price_from_meta(soup)
    if p:
        if p.get("currency") == "EUR" and re.search(r'\b(lei|ron)\b', text_lower):
            p["currency"] = "RON"
        return p

    # 3️⃣ FALLBACK TEXT (stock mai inteligent)
    price_data = _extract_price_from_text(text)

    if price_data:
        text_lower = text.lower()

        in_stock = None

        if any(x in text_lower for x in [
            "în stoc",
            "in stoc",
            "disponibil",
            "livrare rapidă",
            "livrare in 24",
            "adaugă în coș",    
        ]):
            in_stock = True

        elif any(x in text_lower for x in [
            "indisponibil",
            "stoc epuizat",
            "epuizat",
            "momentan indisponibil",
            "nu este disponibil",
            "produsul nu este disponibil",
            "acest produs este momentan indisponibil",
            "out of stock",
        ]):
            in_stock = False

        price_data["in_stock"] = in_stock
        return price_data

    return None


# =========================================================
# ✅ DETECTARE PAGINĂ DE CATEGORIE (filtru)
# =========================================================
def is_category_page(link: str | None) -> bool:
    if not link:
        return False
    
    try:
        url = urlparse(link)
        host = url.netloc.lower()
        path = url.path.lower()
        query = url.query.lower()
    except Exception:
        return False

    if "google." in host and "search" in path:
        return False

    category_patterns = [
        "/categorie/", "/category/", "/catalog/", "/cautare", "/search",
        "/tag/"
    ]
    
    # 1. Path matches
    if any(pattern in path for pattern in category_patterns):
        return True
        
    # 2. Query matches (indicating filters, pagination)
    if any(q in query for q in ["sort=", "page=", "filter=", "price=", "order="]):
        return True

    return False


# =========================================================
# ✅ DETECTARE “REZULTAT RO” (NU DOAR TLD .ro)
#    - acceptă ro.tommy.com
#    - acceptă trendyol.com/ro/...
#    - acceptă fallback din source (eMAG.ro etc.)
# =========================================================
def is_ro_result(link: str | None, source: str | None = None) -> bool:
    if not link:
        return False

    try:
        u = urlparse(link)
        host = (u.netloc or "").lower()
        path = (u.path or "").lower()
    except Exception:
        return False

    host_no_www = host[4:] if host.startswith("www.") else host

    # 1) domeniu .ro (emag.ro, fashiondays.ro etc.)
    if host_no_www.endswith(".ro"):
        return True

    # 2) subdomeniu "ro." (ro.tommy.com)
    if host_no_www.startswith("ro."):
        return True

    # 3) locale în path (/ro/...) (trendyol.com/ro/...)
    if path.startswith("/ro") or "/ro" in path:
        return True

    # 4) fallback din source (de ex. "eMAG.ro", "STYLEWISH.RO")
    s = (source or "").lower()
    if ".ro" in s or s.endswith("ro") or " ro" in s:
        return True

    return False


# =========================================================
# 🔥 ENRICH CU STOCK INCLUS
# =========================================================
def enrich_visual_matches_with_prices(visual_matches: list[dict],
                                      sleep_s: float = 1.0,
                                      only_ro: bool = False):

    out = []

    for item in visual_matches:
        link = item.get("link") or ""

        if only_ro and not is_ro_result(link, item.get("source")):
            continue

        if is_category_page(link):
            continue

        # Prioritize scraping from the product page if a link exists
        page_price = None
        if link:
            page_price = get_price_from_product_page(link)
            time.sleep(sleep_s)  # Sleep after each request to be polite

        # 1. If scraping was successful, use that data.
        # The scraped data already includes price and stock.
        if page_price and "value" in page_price:
            item["_price_final"] = {
                **page_price,
                "via": "page"  # Source is the page itself
            }
        # 2. If scraping failed, fall back to the price from SerpAPI.
        else:
            serp_price = item.get("price") or {}
            extracted_value = serp_price.get("extracted_value")

            if isinstance(extracted_value, (int, float)):
                item["_price_final"] = {
                    "value": float(extracted_value),
                    "currency": serp_price.get("currency") or "RON",
                    "via": "serpapi",
                    "in_stock": item.get("in_stock")  # SerpAPI stock
                }
            elif isinstance(page_price, dict) and "error" in page_price:
                item["_price_final"] = {"error": page_price["error"], "via": "request"}
            else:
                item["_price_final"] = None

        out.append(item)

    return out


# =========================================================
# 2️⃣ SERPAPI – GOOGLE SHOPPING
# =========================================================
def serpapi_search(query: str, num_results: int = 20, return_stats: bool = False):

    stats = {
        "total_received": 0,
        "eliminated_no_price": 0,
        "eliminated_statistical": 0,
        "eliminated_category": 0,
        "eliminated_non_ro": 0,
        "eliminated_blacklist": 0
    }

    if not query:
        return (pd.DataFrame(), stats) if return_stats else pd.DataFrame()

    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": SERPAPI_KEY,
        "gl": "ro",
        "hl": "ro",
        "google_domain": "google.ro",
        "location": "Romania",
        "num": num_results
    }

    try:
        r = requests.get("https://serpapi.com/search.json", params=params, timeout=20)
        data = r.json()
    except Exception:
        return (pd.DataFrame(), stats) if return_stats else pd.DataFrame()

    rows = []

    detected_category = extract_category_from_text(query)

    inline_results = data.get("inline_shopping_results", []) or []
    shopping_results = data.get("shopping_results", []) or []

    if inline_results:
        results = inline_results
    else:
        results = shopping_results

    stats["total_received"] = len(results)

    for it in results:

        title = it.get("title")
        source = it.get("source")
        product_link = it.get("product_link")
        price = it.get("extracted_price")
        raw_price = (it.get("price") or "").lower()
        currency = "RON"

        # 🔴 Elimină dacă apare valută străină
        foreign_currencies = ["eur", "usd", "$", "€", "gbp", "£"]

        if any(cur in raw_price for cur in foreign_currencies):
            stats["eliminated_non_ro"] += 1
            continue

        # 🔴 FILTRU ROMÂNIA MANUAL
        # folosim source + link (product_link este google.com)
        if not is_ro_result(product_link, source):
            stats["eliminated_non_ro"] += 1
            continue

        # 🔴 FILTRU BLACKLIST
        if is_blacklisted(product_link, source):
            stats["eliminated_blacklist"] += 1
            continue

        # 🔴 FILTRU PAGINĂ DE CATEGORIE
        if is_category_page(product_link):
            stats["eliminated_category"] += 1
            continue

        # 🔴 FILTRU PREȚ VALID
        if not isinstance(price, (int, float)):
            stats["eliminated_no_price"] += 1
            continue

        # 🔴 FILTRU CATEGORIE (dacă există)
        if detected_category and detected_category != "general" and title:
            synonyms = PRODUCT_CATEGORIES.get(detected_category, [detected_category])
            norm_title = normalize_text(title)
            if not any(normalize_text(syn) in norm_title for syn in synonyms):
                stats["eliminated_category"] += 1
                continue

        rows.append({
            "title": title,
            "price": float(price),
            "currency": currency,
            "source": source,
            "link": product_link,
            "image": it.get("thumbnail")
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return (df, stats) if return_stats else df

    df = df.reset_index(drop=True)

    return (df, stats) if return_stats else df
# =========================================================
# 3️⃣ ANALIZĂ AI
# =========================================================
def agent_analist(product: str, df: pd.DataFrame) -> str:
    if df.empty:
        return "Nu au fost găsite oferte reale."

    offers = "\n".join(
        f"- {r.title} | {r.price} lei"
        for r in df.itertuples()
    )

    prompt = f"""
Ești un asistent expert de cumpărături.
Produs căutat: {product}

Oferte disponibile (extrase din piață):
{offers}

Sarcina ta:
1. Identifică clar cel mai bun preț (minim).
2. Evaluează dacă există diferențe mari de preț între magazine (oportunitate de economisire sau posibilă eroare).
3. Oferă o scurtă concluzie (max 3 fraze) pentru utilizator: este un moment bun să cumpere? Există multe opțiuni?

Răspunsul trebuie să fie direct, util și în limba română.
"""

    return model_text.generate_content(prompt).text.strip()

PRODUCT_CATEGORIES = {
    "tricou": ["tricou", "t-shirt", "tshirt", "tee", "maieu", "top", "shirt"],
    "blugi": ["blugi", "jeans", "denim"],
    "hanorac": ["hanorac", "hoodie", "sweatshirt", "crewneck"],
    "geaca": ["geaca", "jacket", "coat", "parka", "bomber", "palton", "puffer"],
    "rochie": ["rochie", "dress", "gown"],
    "pantaloni": ["pantaloni", "pants", "trousers", "chinos", "cargo", "joggers", "leggings"],
    "pantofi": ["pantofi", "shoes", "sneakers", "adidasi", "incaltaminte", "cizme", "boots"]
}

def normalize_text(text: str) -> str:
    """Elimină diacriticele și transformă în litere mici pentru potrivire universală."""
    if not text:
        return ""
    text = str(text).lower().strip()
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

def extract_category_from_text(title: str, default: str = "general") -> str:
    """Detectează inteligent categoria bazat pe limite de cuvinte (regex)."""
    normalized_title = normalize_text(title)
    
    for category, synonyms in PRODUCT_CATEGORIES.items():
        for syn in synonyms:
            pattern = r'\b' + re.escape(normalize_text(syn)) + r'\b'
            if re.search(pattern, normalized_title):
                return category
                
    return default


def is_blacklisted(link: str | None, source: str | None = None) -> bool:
    blacklist_domains = [
        "olx.ro",
        "publi24.ro",
        "lajumate.ro",
        "okazii.ro",
        "ebay",
        "vinted",
        "facebook",
        "marketplace",
        "aliexpress",
        "etsy",
        "amazon.com",
        "remixshop.com",
        "Haine-second-hand.ro"
    ]

    link = (link or "").lower()
    source = (source or "").lower()

    return any(domain in link or domain in source for domain in blacklist_domains)