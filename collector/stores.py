"""How to read each store's sitemap and product pages.

Every parser returns a "record": one product as one store sells it.
  sid        unique id: "<store>:<store product id>"
  store      store id
  nameAr, nameEn, brand, category (store's own category text)
  price, was (price before discount, or None), inStock
  url, image, barcode (GTIN/EAN when the store shows one), size (pack size text if separate)
  path       the store's category names from the page breadcrumb, top first (only some stores)
"""
from __future__ import annotations

import html as htmllib
import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Callable

LOC = re.compile(r"<loc>\s*(?:<!\[CDATA\[)?\s*([^<\s\]]+)\s*(?:\]\]>)?\s*</loc>")
LD_JSON = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)


def locs(xml: str | None) -> list[str]:
    return [htmllib.unescape(u) for u in LOC.findall(xml or "")]


def ld_products(html: str) -> list[dict]:
    """All schema.org Product objects in the page's JSON-LD blocks."""
    out = []
    for block in LD_JSON.findall(html):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "Product":
                out.append(it)
    return out


def num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def first_image(img) -> str | None:
    if isinstance(img, list):
        img = img[0] if img else None
    if isinstance(img, dict):
        img = img.get("url") or img.get("contentUrl")
    return img if isinstance(img, str) and img.startswith("http") else None


def brand_name(b) -> str:
    if isinstance(b, dict):
        return str(b.get("name") or "")
    return str(b or "")


def in_stock(offer: dict) -> bool:
    return "InStock" in str(offer.get("availability", "InStock"))


def slug_to_name(slug: str) -> str:
    """'almarai-full-fat-milk-1l' -> 'Almarai Full Fat Milk 1l' (English name when the page is Arabic)."""
    words = [w for w in re.split(r"[-_]+", slug) if w]
    return " ".join(w if re.search(r"\d", w) else w.capitalize() for w in words)


def english_slug_name(slug: str) -> str:
    """Only slugs written in English letters make a usable English name."""
    slug = urllib.parse.unquote(slug)
    return slug_to_name(slug) if re.fullmatch(r"[A-Za-z0-9._%-]+", slug) and re.search(r"[A-Za-z]{3}", slug) else ""


def _crumbs(html: str) -> list[tuple[str, str]]:
    """(name, link) of each step of the page's schema.org BreadcrumbList, top first."""
    for block in LD_JSON.findall(html):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "BreadcrumbList":
                els = sorted((e for e in it.get("itemListElement") or [] if isinstance(e, dict)),
                             key=lambda e: e.get("position") or 0)
                out = []
                for e in els:
                    item = e.get("item")
                    name = e.get("name") or (item.get("name") if isinstance(item, dict) else "") or ""
                    link = (item.get("@id") or item.get("url") or "") if isinstance(item, dict) else str(item or "")
                    out.append((htmllib.unescape(str(name)).strip(), str(link)))
                return out
    return []


def breadcrumb(html: str) -> list[str]:
    """Category names from the page's schema.org BreadcrumbList, without "home" and the product itself."""
    names = [n for n, _ in _crumbs(html)]
    return [n for n in names[1:-1] if n]


HOME_WORDS = {"home", "الرئيسية", "الصفحة الرئيسية", "الرئيسيه", "ايكيا", "ikea", "المنتجات", "products"}


def category_path(html: str, url: str, product_name: str = "") -> list[str]:
    """Like breadcrumb, for stores whose breadcrumb may or may not start with "home" and end with the product."""
    steps = _crumbs(html)
    if steps and steps[0][0].lower() in HOME_WORDS:
        steps = steps[1:]
    if steps and (steps[-1][1].rstrip("/") == url.rstrip("/") or "/p/" in steps[-1][1] or "/product" in steps[-1][1]
                  or (product_name and steps[-1][0] == product_name.strip())):
        steps = steps[:-1]
    return [n for n, _ in steps if n][:5]


def ld_record(store_id: str, url: str, html: str, pid_from_url: str, name_en: str = "") -> dict | None:
    """A record from a page's schema.org Product JSON-LD (used by most stores)."""
    prods = ld_products(html)
    if not prods:
        return None
    p = prods[0]
    offer = p.get("offers") or {}
    if isinstance(offer, list):
        offer = offer[0] if offer else {}
    price = num(offer.get("price") or offer.get("lowPrice"))
    if price is None:
        return None
    spec = offer.get("priceSpecification") or {}
    was = num(spec.get("price")) if isinstance(spec, dict) else None
    if not was and offer.get("@type") == "AggregateOffer":
        was = num(offer.get("highPrice"))
    pid = str(p.get("sku") or offer.get("sku") or pid_from_url)
    brand = brand_name(p.get("brand"))
    if "_" in brand:  # internal codes such as "nonfood_star", not real brands
        brand = ""
    return {
        "sid": f"{store_id}:{pid}", "store": store_id,
        "nameAr": htmllib.unescape(str(p.get("name") or "")).strip(), "nameEn": name_en,
        "brand": brand, "category": str(p.get("category") or ""),
        "price": price, "was": was if was and was > price else None, "inStock": in_stock(offer),
        "url": url, "image": first_image(p.get("image")), "barcode": gtin(p.get("gtin13") or p.get("gtin")),
    }


def rsc_text(html: str, key: str) -> str | None:
    """A text field from the page's embedded data (escaped or not), e.g. Nahdi's "promo_badge":"1 + 1 مجانا".
    For an object value, its label/title/name/text is used."""
    m = re.search(r'\\?"' + re.escape(key) + r'\\?"\s*:\s*(null|\\?"((?:[^"\\]|\\u[0-9a-fA-F]{4})*)\\?"|\{)', html)
    if not m or m.group(1) == "null":
        return None
    if m.group(2) is not None:
        val = m.group(2)
    else:
        m2 = re.search(r'\\?"(?:label|title|name|text|description)\\?"\s*:\s*\\?"((?:[^"\\]|\\u[0-9a-fA-F]{4})*)\\?"', html[m.end():m.end() + 600])
        if not m2:
            return None
        val = m2.group(1)
    try:
        val = json.loads('"' + val + '"')
    except ValueError:
        pass
    val = htmllib.unescape(val).strip()
    return val or None


def gtin(v) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    return d if 8 <= len(d) <= 14 else None


def sitemap_pages(f, index: str, keep: Callable[[str], bool] = lambda m: True,
                  url_ok: Callable[[str], bool] = lambda u: True, limit: int = 200) -> list[str]:
    """Product URLs from a sitemap index: each child sitemap that `keep` accepts, then each URL that `url_ok` accepts."""
    urls = []
    for m in [m for m in locs(f.get(index, timeout=120)) if keep(m)][:limit]:
        urls += [u for u in locs(f.get(m, timeout=120)) if url_ok(u)]
    return list(dict.fromkeys(urls))


@dataclass
class Store:
    id: str
    nameAr: str
    nameEn: str
    kind: str          # retailer | quick | pharmacy
    base: str          # https://host, no trailing slash
    website: str
    delay: float       # seconds between requests
    product_urls: Callable | None   # None: listed in the app, but its prices are read by another store's crawl
    parse: Callable | None
    priority: int = 1  # 1: groceries, pharmacy, q-commerce (always kept in full); 2: other shops
    listed: bool = True  # False: only a crawl that files its products under other stores; not shown in the app


# ---------------------------------------------------------------- Panda
def panda_urls(f) -> list[str]:
    maps = [u for u in locs(f.get("https://panda.sa/sitemap.xml")) if "/products-" in u]
    urls = []
    for m in maps:
        urls += [u for u in locs(f.get(m)) if "/ar/p/" in u]
    return urls


def panda_parse(url: str, html: str) -> dict | None:
    prods = ld_products(html)
    if not prods:
        return None
    p = prods[0]
    offer = p.get("offers") or {}
    if isinstance(offer, list):
        offer = offer[0] if offer else {}
    price = num(offer.get("price") or offer.get("lowPrice"))
    if price is None:
        return None
    spec = offer.get("priceSpecification") or {}
    was = num(spec.get("price")) if isinstance(spec, dict) else None
    slug = url.rstrip("/").split("/")[-1]
    pid = slug.rsplit("-", 1)[-1]
    return {
        "sid": f"panda:{pid}", "store": "panda",
        "nameAr": p.get("name", ""), "nameEn": slug_to_name(slug.rsplit("-", 1)[0]),
        "brand": brand_name(p.get("brand")), "category": str(p.get("category") or ""),
        "price": price, "was": was if was and was > price else None, "inStock": in_stock(offer),
        "url": url, "image": first_image(p.get("image")), "barcode": gtin(p.get("gtin") or p.get("gtin13")),
        "promo": rsc_text(html, "mix_match_promo"),  # e.g. "اشتر 2 واحصل على 1 مجاناً"
    }


# ---------------------------------------------------------------- Tamimi
def tamimi_urls(f) -> list[str]:
    maps = [u for u in locs(f.get("https://www.tamimimarkets.com/sitemap.xml")) if "/products-" in u]
    urls = []
    for m in maps:
        urls += locs(f.get(m))
    return urls


RSC_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)


def _balanced_json(text: str, start: int) -> dict | None:
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


def tamimi_parse(url: str, html: str) -> dict | None:
    parts = []
    for m in RSC_PUSH.findall(html):
        try:
            parts.append(json.loads('"' + m + '"'))
        except ValueError:
            continue
    stream = "".join(parts)
    i = stream.find('{"product":{"barcode"')
    if i < 0:
        i = stream.find('{"product":{')
    if i < 0:
        return None
    data = _balanced_json(stream, i)
    if not data:
        return None
    p, pr = data.get("product") or {}, data.get("pricing") or {}
    price = num(pr.get("price"))
    if price is None:
        return None
    was = num(pr.get("old_price"))
    variant = p.get("variant_id") or ""
    image = p.get("image_url")
    if not image and variant:
        m = re.search(r"https://ecommedia\.tamimimarkets\.com/ecom-prod/productimages/" + re.escape(variant) + r"_1\.\w+", html)
        image = m.group(0) if m else None
    size = p.get("variant_name") or ""
    name_en = (p.get("product_name") or "").strip()
    name_ar = (p.get("product_name_ar") or "").strip()
    return {
        "sid": f"tamimi:{variant or p.get('product_id')}", "store": "tamimi",
        "nameAr": f"{name_ar} {size}".strip() if size else name_ar,
        "nameEn": f"{name_en} {size}".strip() if size else name_en,
        "brand": p.get("brand") or "", "category": " / ".join(x for x in [p.get("department"), p.get("parent_category")] if x),
        "price": price, "was": was if was and was > price else None, "inStock": bool(p.get("in_stock", True)),
        "url": url, "image": image, "barcode": gtin(p.get("barcode")),
    }


# ---------------------------------------------------------------- Nahdi
def nahdi_urls(f) -> list[str]:
    maps = locs(f.get("https://www.nahdionline.com/sitemap_index_ar.xml"))
    urls = []
    for m in maps:
        urls += [u for u in locs(f.get(m)) if "/ar-sa/" in u and "/pdp/" in u]
    return list(dict.fromkeys(urls))


def nahdi_parse(url: str, html: str) -> dict | None:
    prods = ld_products(html)
    if not prods:
        return None
    p = prods[0]
    offer = p.get("offers") or {}
    if isinstance(offer, list):
        offer = offer[0] if offer else {}
    low, high = num(offer.get("lowPrice") or offer.get("price")), num(offer.get("highPrice"))
    if low is None:
        return None
    parts = url.rstrip("/").split("/")
    pid = parts[-1]
    slug = parts[-3] if len(parts) >= 3 else ""
    return {
        "sid": f"nahdi:{pid}", "store": "nahdi",
        "nameAr": p.get("name", ""), "nameEn": "" if slug.isdigit() else slug_to_name(slug),
        "brand": brand_name(p.get("brand")), "category": str(p.get("category") or ""),
        "price": low, "was": high if high and high > low else None, "inStock": in_stock(offer),
        "url": url, "image": first_image(p.get("image")), "barcode": gtin(p.get("gtin") or p.get("gtin13")),
        "path": breadcrumb(html),
        "promo": rsc_text(html, "promo_badge"),  # e.g. "1 + 1 مجانا"
    }


def nahdi_tree(f) -> list[dict]:
    """Nahdi's category tree, from the category pages (/plp/) listed in its Arabic and English sitemaps.
    Each entry: {"id": "69391", "ar": ["المكياج", "الشفاه", "أحمر-شفاه"], "en": ["makeup", "lips", "lip-stick"]}."""
    def plps(index: str) -> dict[str, list[str]]:
        out = {}
        for m in locs(f.get(index)):
            for u in locs(f.get(m)):
                if "/plp/" not in u:
                    continue
                path = urllib.parse.unquote(u).split(".com/", 1)[-1].split("/")[1:]  # drop "ar-sa"
                if len(path) >= 3 and path[-2] == "plp" and path[-1].isdigit():
                    out[path[-1]] = path[:-2]
        return out
    ar = plps("https://www.nahdionline.com/sitemap_index_ar.xml")
    en = plps("https://www.nahdionline.com/sitemap_index_en.xml") if ar else {}
    return [{"id": i, "ar": p, "en": en.get(i) or []} for i, p in ar.items() if p]


# ---------------------------------------------------------------- Al-Dawaa
def aldawaa_urls(f) -> list[str]:
    maps = [u for u in locs(f.get("https://www.al-dawaa.com/sitemap.xml")) if "/ar/Product-" in u]
    urls = []
    for m in maps:
        urls += locs(f.get(m))
    return urls


def aldawaa_parse(url: str, html: str) -> dict | None:
    prods = ld_products(html)
    if not prods:
        return None
    p = prods[0]
    offer = p.get("offers") or {}
    if isinstance(offer, list):
        offer = offer[0] if offer else {}
    price = num(offer.get("price"))
    if price is None:
        return None
    spec = offer.get("priceSpecification") or {}
    was = num(spec.get("price")) if isinstance(spec, dict) else None
    parts = url.rstrip("/").split("/")
    return {
        "sid": f"aldawaa:{parts[-2]}", "store": "aldawaa",
        "nameAr": p.get("name", ""), "nameEn": slug_to_name(parts[-1]),
        "brand": brand_name(p.get("brand")), "category": str(p.get("category") or ""),
        "price": price, "was": was if was and was > price else None, "inStock": in_stock(offer),
        "url": url, "image": first_image(p.get("image")), "barcode": gtin(p.get("gtin") or p.get("gtin13")),
    }


# ---------------------------------------------------------------- Whites
def whites_urls(f) -> list[str]:
    urls, page = [], 1
    while page <= 20:
        found = locs(f.get(f"https://www.whites.sa/ar-sa/sitemap/products-{page}"))
        if not found:
            break
        urls += found
        page += 1
    return list(dict.fromkeys(urls))


def whites_parse(url: str, html: str) -> dict | None:
    slug = url.rstrip("/").split("/")[-1]
    return ld_record("whites", url, html, slug, english_slug_name(slug))


# ---------------------------------------------------------------- Lemon
def lemon_urls(f) -> list[str]:
    maps = [u for u in locs(f.get("https://lemon.sa/index.php?route=feed/advanced_sitemap&lang=ar"))
            if "advanced_sitemap/product" in u]
    urls = []
    for m in maps:
        urls += locs(f.get(m))
    return list(dict.fromkeys(urls))


def lemon_parse(url: str, html: str) -> dict | None:
    m = re.search(r"product_id=(\d+)", url)
    slug = url.rstrip("/").split("/")[-1]
    return ld_record("lemon", url, html, m.group(1) if m else slug, "" if m else english_slug_name(slug))


# ---------------------------------------------------------------- United Pharmacy
URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.S)


def united_urls(f) -> list[str]:
    xml = f.get("https://unitedpharmacy.sa/sitemap_ar.xml", timeout=180) or ""
    # Product entries carry an image; category pages don't.
    return list(dict.fromkeys(locs(b)[0] for b in URL_BLOCK.findall(xml) if "<image:" in b and locs(b)))


def united_parse(url: str, html: str) -> dict | None:
    slug = url.rstrip("/").split("/")[-1].removesuffix(".html")
    return ld_record("united", url, html, slug, english_slug_name(slug))


# ---------------------------------------------------------------- Carrefour
def carrefour_urls(f) -> list[str]:
    maps = [u for u in locs(f.get("https://www.carrefourksa.com/sitemap.xml")) if re.search(r"/products\d+_ar\.xml$", u)]
    urls = []
    for m in maps:
        urls += [u for u in locs(f.get(m)) if "/mafsau/ar/" in u and "/p/" in u]
    return list(dict.fromkeys(urls))


def carrefour_parse(url: str, html: str) -> dict | None:
    parts = url.rstrip("/").split("/")
    slug = parts[-3] if len(parts) >= 3 else ""
    return ld_record("carrefour", url, html, parts[-1], english_slug_name(slug))


# ---------------------------------------------------------------- Faces (beauty, Chalhoub)
def faces_urls(f) -> list[str]:
    return sitemap_pages(f, "https://www.faces.sa/ar/sitemap_index.xml", url_ok=lambda u: "/ar/p/" in u)


def faces_parse(url: str, html: str) -> dict | None:
    rec = ld_record("faces", url, html, url.rstrip("/").split("/")[-1].removesuffix(".html"))
    if rec:
        slug = url.rstrip("/").split("/")[-1].removesuffix(".html")
        rec["nameEn"] = english_slug_name(slug.rsplit("-", 1)[0])
        rec["path"] = category_path(html, url, rec["nameAr"])
    return rec


# ---------------------------------------------------------------- Mumzworld (mother, baby, kids)
MUMZ_PREFIX = re.compile(r"^\s*(?:اشتر[يى]?|تسوق)[^|]*\|\s*")


def mumzworld_urls(f) -> list[str]:
    return sitemap_pages(f, "https://www.mumzworld.com/media/sitemaps/sa-ar/sitemap_index.xml",
                         keep=lambda m: "product" in m, url_ok=lambda u: "/sa-ar/" in u)


def mumzworld_parse(url: str, html: str) -> dict | None:
    slug = url.rstrip("/").split("/")[-1]
    rec = ld_record("mumzworld", url, html, slug, english_slug_name(slug))
    if rec:
        rec["nameAr"] = MUMZ_PREFIX.sub("", rec["nameAr"])
        rec["path"] = category_path(html, url, rec["nameAr"])
    return rec


# ---------------------------------------------------------------- eXtra (electronics, appliances)
def extra_urls(f) -> list[str]:
    return sitemap_pages(f, "https://www.extra.com/ar-sa/sitemap.xml", keep=lambda m: "/Product-" in m,
                         url_ok=lambda u: "/ar-sa/" in u and "/p/" in u)


def extra_parse(url: str, html: str) -> dict | None:
    parts = url.rstrip("/").split("/")
    rec = ld_record("extra", url, html, parts[-1], english_slug_name(parts[-3]) if len(parts) > 3 else "")
    if rec:
        rec["path"] = category_path(html, url, rec["nameAr"])
    return rec


# ---------------------------------------------------------------- Al-Manea (electronics, appliances)
def almanea_urls(f) -> list[str]:
    return sitemap_pages(f, "https://www.almanea.sa/index_sitemap.xml",
                         keep=lambda m: "-c-" in m, url_ok=lambda u: "/product/" in u)


def almanea_parse(url: str, html: str) -> dict | None:
    slug = url.rstrip("/").split("/")[-1]
    m = re.search(r"-p-(\d+)$", slug)
    rec = ld_record("almanea", url, html, m.group(1) if m else slug, english_slug_name(slug[:m.start()] if m else slug))
    if rec:
        rec["path"] = category_path(html, url, rec["nameAr"])
    return rec


# ---------------------------------------------------------------- SACO (home, tools)
def saco_urls(f) -> list[str]:
    return list(dict.fromkeys(u for u in locs(f.get("https://www.saco.sa/sitemap_ar.xml", timeout=180))
                              if "/product/" in u))


def saco_parse(url: str, html: str) -> dict | None:
    slug = url.rstrip("/").split("/")[-1]
    m = re.search(r"-p-(\w+)$", slug)
    rec = ld_record("saco", url, html, m.group(1) if m else slug, english_slug_name(slug[:m.start()] if m else slug))
    if rec:
        rec["path"] = category_path(html, url, rec["nameAr"])
    return rec


# ---------------------------------------------------------------- IKEA Saudi Arabia (furniture, home)
def ikea_urls(f) -> list[str]:
    urls, page = [], 1
    while page <= 40:
        found = locs(f.get(f"https://www.ikea.com/sitemaps/prod-ar-SA_{page}.xml"))
        if not found:
            break
        urls += [u for u in found if "/sa/ar/p/" in u]
        page += 1
    return list(dict.fromkeys(urls))


def ikea_parse(url: str, html: str) -> dict | None:
    slug = url.rstrip("/").split("/")[-1]
    m = re.search(r"-(\w?\d+)$", slug)
    rec = ld_record("ikea", url, html, m.group(1) if m else slug, english_slug_name(slug[:m.start()] if m else slug))
    if rec:
        rec["path"] = category_path(html, url, rec["nameAr"])
    return rec


# ---------------------------------------------------------------- HungerStation (delivery app)
# HungerStation's public site lists, in its own sitemap, every product of its own quick market
# ("HungerStation Market") and of the supermarket chains it delivers from, each with a price
# (a Riyadh branch). One crawl reads them all; each product is filed under the chain that sells it.
HS = "https://hungerstation.com"
HS_CHAINS = {  # chain part of HungerStation's web address -> our store id
    "danube-80083": "danube", "carrefour-61311": "carrefour", "al-othaim-65969": "othaim",
    "lulu-hypermarket-13841": "lulu", "alraya-98596": "alraya", "farm-market-30616": "farm",
    "spinneys-83719": "spinneys", "grand-hyper-87783": "grandhyper",
}


def hungerstation_urls(f) -> list[str]:
    maps = [f"{HS}/sitemaps/sa-ar/hmarket/products.xml"]
    maps += [f"{HS}/sitemaps/sa-ar/supermarkets/chains/{c}.xml" for c in HS_CHAINS]
    lists = []
    for m in maps:
        lists.append([u for u in locs(f.get(m, timeout=120)) if "/product/" in u])
    # Interleave the lists, so every chain gets read a little each day instead of one after another.
    out = []
    for i in range(max((len(x) for x in lists), default=0)):
        out += [x[i] for x in lists if i < len(x)]
    return list(dict.fromkeys(out))


def hungerstation_parse(url: str, html: str) -> dict | None:
    m = re.search(r"/sa-ar/supermarkets/([^/]+)/product/", url)
    store = HS_CHAINS.get(m.group(1)) if m else ("hungerstation" if "/sa-ar/hmarket/product/" in url else None)
    if not store:
        return None
    slug = urllib.parse.unquote(url.rstrip("/").split("/")[-1])
    rec = ld_record(store, url, html, slug.rsplit("-", 1)[-1])
    if rec:
        rec["path"] = [rec["category"]] if rec.get("category") else []
        # Some chains' product codes end with the barcode, e.g. Carrefour "100833_6281100081036".
        m = re.search(r"_(\d{8,14})$", rec["sid"])
        if m and not rec.get("barcode"):
            rec["barcode"] = gtin(m.group(1))
    return rec


# ---------------------------------------------------------------- Pharmacies on HungerStation
# Pharmacies whose own sites refuse our collector (or have no shop) also sell on HungerStation.
# Their branch pages are public and linked from HungerStation's sitemap (modules/pharmacies.xml ->
# district page -> pharmacy branch -> category pages). Each category page carries its products with
# prices as schema.org JSON-LD, so one page gives a few dozen products.
HS_PHARMACIES = {  # HungerStation vendor number -> our store id
    "95205": "aldawaa", "63994": "mujtama", "13864": "lemon", "81003": "aster", "99786": "kunooz",
}
HREF = re.compile(r'href="([^"]+)"')


def _hs_quote(u: str) -> str:
    return urllib.parse.quote(htmllib.unescape(u), safe=":/?=&%~")


# Supermarket chains on HungerStation, by the same vendor number as in HS_CHAINS ("danube-80083").
HS_SHOPS = {**HS_PHARMACIES, **{k.rsplit("-", 1)[1]: v for k, v in HS_CHAINS.items()}}
HS_BRANCH = re.compile(r"/sa-ar/[a-z]+/(\d+)/[^/\"]+/branch/[^/\"]+")


def _hs_cats(html: str) -> list[str]:
    return [_hs_quote(urllib.parse.urljoin(HS, h).split("?")[0].split("#")[0])
            for h in HREF.findall(html or "") if "/category/" in h and "/sa-ar/qc/" in h]


def hs_pharmacy_urls(f) -> list[str]:
    """Category pages of every shop in HS_SHOPS: supermarket chains (their category pages are in the
    chain sitemaps) and pharmacies (one Riyadh branch each, found through the district pages). A category
    page lists the whole category with prices, so a shop's full range takes a few dozen pages instead of
    one page per product."""
    cats: list[str] = []
    for slug in HS_CHAINS:
        cats += [_hs_quote(u) for u in locs(f.get(f"{HS}/sitemaps/sa-ar/supermarkets/chains/{slug}.xml", timeout=120))
                 if "/category/" in u]
    branches: dict[str, str] = {}
    districts = [u for u in locs(f.get(f"{HS}/sitemaps/sa-ar/modules/pharmacies.xml", timeout=120))
                 if urllib.parse.unquote(u).split("/qc/pharmacies/")[-1].startswith("الرياض/")]
    for d in districts[:80]:
        for page in (d, d + "?page=1", d + "?page=2"):
            for h in HREF.findall(f.get(page) or ""):
                m = HS_BRANCH.search(urllib.parse.unquote(htmllib.unescape(h)))
                if m and m.group(1) in HS_PHARMACIES and m.group(1) not in branches:
                    branches[m.group(1)] = urllib.parse.urljoin(HS, m.group(0))
        if len(branches) == len(HS_PHARMACIES):
            break
    print(f"[hspharmacy] pharmacy branches found: {sorted(HS_PHARMACIES[v] for v in branches)}", flush=True)
    for b in branches.values():
        first = _hs_cats(f.get(_hs_quote(b)))
        # A category page links every category of the shop, also ones the branch page leaves out.
        cats += first + (_hs_cats(f.get(first[0])) if first else [])
    return list(dict.fromkeys(cats))


def hs_shop(url: str) -> str | None:
    """Our store id for a HungerStation supermarket or pharmacy page."""
    u = urllib.parse.unquote(url)
    m = re.search(r"/sa-ar/supermarkets/([^/]+)/", u)
    if m and m.group(1) in HS_CHAINS:
        return HS_CHAINS[m.group(1)]
    m = HS_BRANCH.search(u)
    return HS_SHOPS.get(m.group(1)) if m else None


NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def _hs_next_products(store: str, url: str, html: str) -> list[dict]:
    """Supermarket category pages keep their products in the page's Next.js data, not in JSON-LD."""
    m = NEXT_DATA.search(html)
    try:
        props = json.loads(m.group(1))["props"]["pageProps"] if m else {}
    except (ValueError, KeyError, TypeError):
        return []
    sel = props.get("selectedSubcategory") or props.get("selectedCategory") or {}
    category = str(sel.get("name") or "") if isinstance(sel, dict) else ""
    out = []
    for p in ((props.get("initialProductsList") or {}).get("items") or []):
        price = num(p.get("price")) if isinstance(p, dict) else None
        if price is None or not p.get("sku"):
            continue
        sku = str(p["sku"])
        was = num(p.get("originalPrice"))
        b = re.search(r"_(\d{8,14})$", sku)
        images = p.get("images") or []
        out.append({
            "sid": f"{store}:{sku}", "store": store,
            "nameAr": htmllib.unescape(str(p.get("name") or "")).strip(), "nameEn": "", "brand": "",
            "category": category, "price": price, "was": was if was and was > price else None, "inStock": True,
            "url": url, "image": (images[0] or {}).get("url") if images and isinstance(images[0], dict) else None,
            "barcode": gtin(b.group(1)) if b else None, "path": [category] if category else [],
        })
    return out


def hs_pharmacy_parse(url: str, html: str) -> list[dict] | None:
    store = hs_shop(url)
    if not store:
        return None
    out = []
    for block in LD_JSON.findall(html):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "ItemList":
            continue
        for el in data.get("itemListElement") or []:
            p = (el or {}).get("item") if isinstance(el, dict) else None
            if not isinstance(p, dict) or p.get("@type") != "Product":
                continue
            offer = p.get("offers") or {}
            price = num(offer.get("price"))
            if price is None or not p.get("sku"):
                continue
            out.append({
                "sid": f"{store}:{p['sku']}", "store": store,
                "nameAr": htmllib.unescape(str(p.get("name") or "")).strip(), "nameEn": "",
                "brand": brand_name(p.get("brand")), "category": str(p.get("category") or ""),
                "price": price, "was": None, "inStock": in_stock(offer),
                "url": p.get("@id") or offer.get("url") or url, "image": first_image(p.get("image")),
                "barcode": gtin(p.get("gtin13") or p.get("gtin")), "path": [str(p.get("category") or "")],
            })
    if not out:
        out = _hs_next_products(store, url, html)
    if out and '"isLastPage":false' in html:
        print(f"[hspharmacy] more pages than shown: {urllib.parse.unquote(url)[-80:]}", flush=True)
    return out or None


ALL = [
    Store("tamimi", "أسواق التميمي", "Tamimi Markets", "retailer", "https://www.tamimimarkets.com",
          "https://www.tamimimarkets.com", 0.5, tamimi_urls, tamimi_parse),
    Store("panda", "بنده", "Panda", "retailer", "https://panda.sa", "https://panda.sa", 0.5, panda_urls, panda_parse),
    Store("nahdi", "صيدليات النهدي", "Nahdi Pharmacy", "pharmacy", "https://www.nahdionline.com",
          "https://www.nahdionline.com", 0.5, nahdi_urls, nahdi_parse),
    # Carrefour's own site refuses our collector (see carrefour_urls), so its prices come from HungerStation.
    Store("whites", "صيدليات وايتس", "Whites Pharmacy", "pharmacy", "https://www.whites.sa",
          "https://www.whites.sa/ar-sa/", 0.5, whites_urls, whites_parse),
    Store("united", "صيدلية المتحدة", "United Pharmacy", "pharmacy", "https://unitedpharmacy.sa",
          "https://unitedpharmacy.sa/ar/", 1.0, united_urls, united_parse),
    # Lemon's and Al-Dawaa's own sites refuse our collector (lemon_urls, aldawaa_urls), so their
    # prices come from HungerStation, like Al-Mujtama, Aster and Kunooz (hs_pharmacy_urls).
    Store("hspharmacy", "أقسام هنقرستيشن", "HungerStation category pages", "pharmacy", HS, f"{HS}/sa-ar/qc/pharmacies",
          0.35, hs_pharmacy_urls, hs_pharmacy_parse, listed=False),
    *[Store(sid, ar + " · هنقرستيشن", en + " · HungerStation", "pharmacy", HS, site, 0, None, None)
      for sid, ar, en, site in [
          ("aldawaa", "صيدليات الدواء", "Al-Dawaa Pharmacy", "https://www.al-dawaa.com"),
          ("mujtama", "صيدليات المجتمع", "Al-Mujtama Pharmacy", "https://hungerstation.com/sa-ar/qc/pharmacies"),
          ("lemon", "صيدلية ليمون", "Lemon Pharmacy", "https://lemon.sa"),
          ("aster", "صيدليات أستر", "Aster Pharmacy", "https://www.asterpharmacy.com"),
          ("kunooz", "صيدليات كنوز", "Kunooz Pharmacy", "https://hungerstation.com/sa-ar/qc/pharmacies"),
      ]],
    Store("faces", "فيسز", "Faces", "retailer", "https://www.faces.sa", "https://www.faces.sa/ar/",
          0.5, faces_urls, faces_parse),
    Store("mumzworld", "ممزورلد", "Mumzworld", "retailer", "https://www.mumzworld.com",
          "https://www.mumzworld.com/sa-ar/", 0.5, mumzworld_urls, mumzworld_parse, priority=2),
    Store("extra", "إكسترا", "eXtra", "retailer", "https://www.extra.com", "https://www.extra.com/ar-sa/",
          0.5, extra_urls, extra_parse, priority=2),
    Store("almanea", "المنيع", "Al-Manea", "retailer", "https://www.almanea.sa", "https://www.almanea.sa/",
          0.5, almanea_urls, almanea_parse, priority=2),
    Store("saco", "ساكو", "SACO", "retailer", "https://www.saco.sa", "https://www.saco.sa/ar/",
          0.5, saco_urls, saco_parse, priority=2),
    Store("ikea", "ايكيا", "IKEA", "retailer", "https://www.ikea.com", "https://www.ikea.com/sa/ar/",
          0.5, ikea_urls, ikea_parse, priority=2),
    Store("hungerstation", "هنقرستيشن ماركت", "HungerStation Market", "quick", HS, f"{HS}/sa-ar/hmarket",
          0.35, hungerstation_urls, hungerstation_parse),
    # Supermarkets read through HungerStation (prices as HungerStation shows them, Riyadh branch).
    *[Store(sid, ar + " · هنقرستيشن", en + " · HungerStation", "retailer", HS, site, 0, None, None)
      for sid, ar, en, site in [
          ("danube", "الدانوب", "Danube", "https://www.danube.sa"),
          ("carrefour", "كارفور", "Carrefour", "https://www.carrefourksa.com"),
          ("othaim", "أسواق العثيم", "Othaim Markets", "https://www.othaimmarkets.com"),
          ("lulu", "لولو هايبر ماركت", "LuLu Hypermarket", "https://www.luluhypermarket.com"),
          ("alraya", "أسواق الراية", "Al Raya", "https://hungerstation.com/sa-ar/supermarkets/alraya-98596"),
          ("farm", "أسواق المزرعة", "Farm Superstores", "https://www.farm.com.sa"),
          ("spinneys", "سبينس", "Spinneys", "https://www.spinneys.com"),
          ("grandhyper", "جراند هايبر", "Grand Hyper", "https://hungerstation.com/sa-ar/supermarkets/grand-hyper-87783"),
      ]],
]
