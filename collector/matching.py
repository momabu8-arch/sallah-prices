"""Turns store records into the app's price file: one product, with an offer from each store that sells it.

Two records are the same product when:
1. they have the same barcode (GTIN/EAN), or
2. their English names are the same once cleaned up (word order, units and small words ignored), or
3. fuzzy.py finds them alike enough: same pack size, mostly the same words, no clashing variant words.
A missed match only means two separate rows, a wrong match shows a wrong price, so all rules lean strict.

Each product also gets a "kind" (fuzzy.kind_words): its generic words, shared by other brands
of the same kind of product, so the app can offer cheaper alternatives.
"""
from __future__ import annotations

import re
from collections import deque
from datetime import datetime, timedelta, timezone

import fuzzy
import taxonomy

CATEGORIES = [
    ("fresh", "خضار وفواكه ولحوم", "Fresh food"),
    ("dairy", "ألبان وبيض", "Dairy & eggs"),
    ("pantry", "مواد غذائية", "Pantry"),
    ("drinks", "مشروبات", "Drinks"),
    ("cleaning", "منظفات", "Cleaning"),
    ("baby", "أطفال", "Baby"),
    ("personal", "عناية شخصية", "Personal care"),
    ("pharmacy", "صيدلية", "Pharmacy"),
    ("other", "أخرى", "Other"),
]

# First matching rule wins. Matched against the store's category text plus the product name.
CATEGORY_RULES = [
    ("baby", r"baby|infant|diaper|nappy|wipes|أطفال|طفل|رضع|حفاض|حفاضات"),
    ("pharmacy", r"medicine|vitamin|supplement|pain|cold|flu|first aid|health|pharmacy|أدوية|دواء|فيتامين|مكملات|صحة|مسكن|إسعافات"),
    ("cleaning", r"clean|laundry|detergent|dish|tissue|household|bleach|منظف|غسيل|جلي|مناديل|تنظيف|مبيض"),
    ("personal", r"personal care|beauty|skin|hair|shampoo|deodorant|oral|tooth|makeup|perfume|fragrance|cosmetic|عناية|بشرة|شعر|شامبو|مزيل|أسنان|مكياج|عطر|تجميل"),
    ("dairy", r"dairy|milk|laban|yogh?urt|cheese|butter|cream|egg|ألبان|حليب|لبن|زبادي|جبن|زبدة|قشطة|بيض"),
    ("drinks", r"beverage|drink|water|juice|soda|soft drink|coffee|tea|مشروب|مياه|ماء|عصير|غازي|قهوة|شاي"),
    ("fresh", r"fresh|fruit|vegetable|meat|chicken|poultry|fish|seafood|bakery|طازج|فواكه|خضار|لحوم|دجاج|أسماك|مخبوزات"),
    ("pantry", r"food|grocery|rice|pasta|canned|oil|sugar|flour|spice|snack|biscuit|chocolate|cereal|sauce|مواد غذائية|أرز|معكرونة|معلبات|زيت|سكر|طحين|بهارات|وجبات|بسكويت|شوكولات|حبوب|صلص"),
]

UNIT_ALIASES = {
    "g": "g", "gm": "g", "gms": "g", "gr": "g", "gram": "g", "grams": "g", "جم": "g", "غ": "g", "غرام": "g", "جرام": "g",
    "kg": "kg", "kgs": "kg", "كجم": "kg", "كيلو": "kg", "كغ": "kg",
    "ml": "ml", "مل": "ml",
    "l": "l", "ltr": "l", "litre": "l", "liter": "l", "lt": "l", "لتر": "l",
    "pcs": "pcs", "pc": "pcs", "piece": "pcs", "pieces": "pcs", "tablets": "pcs", "tablet": "pcs", "tabs": "pcs", "capsules": "pcs", "capsule": "pcs", "sachet": "pcs",
    "caps": "pcs", "sachets": "pcs", "pads": "pcs", "rolls": "pcs", "حبة": "pcs", "قطعة": "pcs", "قرص": "pcs", "كبسولة": "pcs",
}
_UNIT = "|".join(sorted((re.escape(u) for u in UNIT_ALIASES), key=len, reverse=True))
MULTI = re.compile(rf"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*({_UNIT})(?![a-z؀-ۿ])", re.I)
SINGLE = re.compile(rf"(\d+(?:\.\d+)?)\s*({_UNIT})(?![a-z؀-ۿ])", re.I)

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

STOP = {"with", "and", "the", "for", "of", "a", "an", "pack", "piece", "pcs", "pc", "x", "new", "offer"}


def parse_size(*texts: str) -> tuple[float, str]:
    """Pack size from a product name: '10 x 25.6g' -> (256, 'g'); '1.5 L' -> (1.5, 'l'). Default (1, 'pcs')."""
    for t in texts:
        if not t:
            continue
        t = t.translate(ARABIC_DIGITS).replace("٫", ".").replace(",", ".")
        m = MULTI.search(t)
        if m:
            return float(m.group(1)) * float(m.group(2)), UNIT_ALIASES[m.group(3).lower()]
        m = SINGLE.search(t)
        if m:
            v = float(m.group(1))
            if v > 0:
                return v, UNIT_ALIASES[m.group(2).lower()]
    return 1.0, "pcs"


def _base_amount(value: float, unit: str) -> str:
    if unit == "kg":
        return f"{value * 1000:g}g"
    if unit == "l":
        return f"{value * 1000:g}ml"
    return f"{value:g}{unit}"


def name_key(name_en: str) -> str | None:
    """'Almarai Full Fat Milk 1 L' and 'almarai milk full-fat 1000ml' -> the same key."""
    if not name_en:
        return None
    text = name_en.lower().replace(",", ".")
    sizes = []
    for m in MULTI.finditer(text):
        sizes.append(_base_amount(float(m.group(1)) * float(m.group(2)), UNIT_ALIASES[m.group(3).lower()]))
    text = MULTI.sub(" ", text)
    for m in SINGLE.finditer(text):
        sizes.append(_base_amount(float(m.group(1)), UNIT_ALIASES[m.group(2).lower()]))
    text = SINGLE.sub(" ", text)
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w and w not in STOP]
    if len(words) < 2 or not sizes:
        return None  # too vague to match safely
    return " ".join(sorted(set(words))) + "|" + ",".join(sorted(sizes))


_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def parse_deal(promo: str | None, price: float) -> dict | None:
    """Multi-buy offers as {"qty": n, "price": total for n}: "1 + 1 مجانا" -> 2 for the price of 1.
    Plain discounts are already in the price, so only multi-buy wording is read here."""
    if not promo:
        return None
    t = promo.translate(_AR_DIGITS).lower()
    m = re.search(r"(\d+)\s*\+\s*(\d+)", t) or \
        re.search(r"(?:buy|اشتر[يى]?|إشتر[يى]?)\s*(\d+)\D{0,25}?(?:get|واحصل|و احصل|احصل)\D{0,10}?(\d+)", t)
    if m:
        buy, get = int(m.group(1)), int(m.group(2))
        if 0 < buy <= 10 and 0 < get <= 10:
            return {"qty": buy + get, "price": round(buy * price, 2)}
    m = re.search(r"(\d+)\s*(?:for|بـ|ب)\s*(\d+(?:\.\d+)?)", t)
    if m:
        qty, total = int(m.group(1)), float(m.group(2))
        if 1 < qty <= 10 and 0 < total < qty * price:
            return {"qty": qty, "price": round(total, 2)}
    m = re.search(r"(\d+)\s*%", t)
    if m and re.search(r"second|2nd|الثان|التان", t):
        pct = int(m.group(1))
        if 0 < pct <= 100:
            return {"qty": 2, "price": round(price * (2 - pct / 100), 2)}
    if re.search(r"(?:second|2nd)[^%]*half|نصف السعر", t):
        return {"qty": 2, "price": round(price * 1.5, 2)}
    return None


def category_for(text: str, store_kind: str) -> str:
    t = text.lower()
    for cat, pattern in CATEGORY_RULES:
        if re.search(pattern, t):
            return cat
    return "pharmacy" if store_kind == "pharmacy" else "other"


class _UnionFind:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def build_catalog(records: list[dict], stores: list, now: datetime | None = None, max_products: int = 155000,
                  nahdi_tree: list[dict] | None = None) -> dict:
    """nahdi_tree: Nahdi's category tree (stores.nahdi_tree), for the app's category navigation."""
    kinds = {s.id: s.kind for s in stores}
    order = {s.id: i for i, s in enumerate(stores)}
    recs = [r for r in records if r.get("price") and r.get("store") in kinds]
    uf = _UnionFind(len(recs))
    seen: dict[str, int] = {}
    for i, r in enumerate(recs):
        keys = []
        if r.get("barcode"):
            keys.append("b:" + r["barcode"].lstrip("0"))
        k = name_key(r.get("nameEn", ""))
        if k:
            keys.append("n:" + k)
        for key in keys:
            if key in seen:
                uf.union(i, seen[key])
            else:
                seen[key] = i
    for i, j, _ in fuzzy.links(recs):
        uf.union(i, j)
    generic = fuzzy.generic_words(recs)

    groups: dict[int, list[dict]] = {}
    for i, r in enumerate(recs):
        groups.setdefault(uf.find(i), []).append(r)

    products = []
    for group in groups.values():
        # One offer per store: the cheapest in-stock one.
        by_store: dict[str, dict] = {}
        for r in sorted(group, key=lambda r: (not r.get("inStock", True), r["price"])):
            by_store.setdefault(r["store"], r)
        chosen = sorted(by_store.values(), key=lambda r: order[r["store"]])
        # Real English names (Tamimi) beat names rebuilt from web addresses.
        en_src = next((r for r in chosen if r["store"] == "tamimi" and r.get("nameEn")), None) or \
            next((r for r in chosen if r.get("nameEn")), chosen[0])
        ar_src = next((r for r in chosen if r.get("nameAr")), chosen[0])
        barcode = next((r["barcode"] for r in chosen if r.get("barcode")), None)
        # Arabic names keep decimals ("22.5 جرام"); names rebuilt from web addresses lose them ("22 5g").
        size, unit = parse_size(ar_src.get("nameAr", ""), en_src.get("nameEn", ""))
        exact = fuzzy.find_size(ar_src.get("nameAr", ""), en_src.get("nameEn", ""))
        if not exact and unit in ("g", "kg") and fuzzy.DIAPERS.search(f"{ar_src.get('nameAr', '')} {en_src.get('nameEn', '')}"):
            size, unit = 1.0, "pcs"  # a diaper pack's kilos are the baby's weight; count unknown
        if exact and exact[1] in ("g", "ml", "pcs"):  # also understands oz, cl, lb and more Arabic units
            size, unit = exact
            if unit in ("g", "ml") and size >= 1000:
                size, unit = size / 1000, {"g": "kg", "ml": "l"}[unit]
        kind = next((k for k in (fuzzy.kind_words(r.get("nameEn", ""), generic) for r in chosen) if k), None)
        cat_text = " ".join(f"{r.get('category', '')} {r.get('nameEn', '')}" for r in chosen)
        pid = ("b-" + barcode) if barcode else chosen[0]["sid"].replace(":", "-")
        products.append({
            "id": pid,
            "nameAr": ar_src.get("nameAr") or en_src.get("nameEn", ""),
            "nameEn": en_src.get("nameEn") or ar_src.get("nameAr", ""),
            "brand": next((r["brand"] for r in chosen if r.get("brand")), ""),
            "category": category_for(cat_text, kinds[chosen[0]["store"]]),
            "size": round(size, 3),
            "unit": unit,
            "barcode": barcode,
            "image": next((r["image"] for r in chosen if r.get("image")), None),
            "kind": kind,
            "_recs": group,
            "offers": [
                {k: v for k, v in {
                    "store": r["store"], "price": round(r["price"], 2),
                    "was": round(r["was"], 2) if r.get("was") else None,
                    "inStock": bool(r.get("inStock", True)), "url": r.get("url"),
                    "at": (r.get("fetchedAt") or "")[:10] or None,  # day this price was read from the store
                    "promo": r.get("promo") or None, "deal": parse_deal(r.get("promo"), r["price"]),
                    # Price changes [[day since 2026-01-01, price], ...], only once the price has changed.
                    "h": r["hist"] if len(r.get("hist") or []) >= 2 else None,
                }.items() if v is not None}
                for r in chosen
            ],
        })

    # Products sold in more stores first, so comparisons show up at the top.
    products.sort(key=lambda p: (-len(p["offers"]), p["nameEn"].lower()))
    # The app holds the whole file in memory: 200,000 products (139 MB) made phones fail to load the
    # new prices on 2026-11-28, while 170,000 (108 MB) loaded fine. Keep the file below that until the
    # app stores prices in a database instead.
    # Products found in several stores always stay; the rest is shared out store by store so
    # every store (every pharmacy too) shows up, not just the ones early in the alphabet.
    multi = [p for p in products if len(p["offers"]) > 1]
    single: dict[str, list] = {}
    for p in products:
        if len(p["offers"]) == 1:
            single.setdefault(p["offers"][0]["store"], []).append(p)
    # Groceries, pharmacies and delivery apps (priority 1) are shared out first, other shops
    # (electronics, furniture...) take whatever room is left.
    fill, room = [], max(0, max_products - len(multi))
    for prio in sorted({getattr(s, "priority", 1) for s in stores}):
        queues = [deque(single[s.id]) for s in stores if s.id in single and getattr(s, "priority", 1) == prio]
        while room > 0 and any(queues):
            for q in queues:
                if q and room > 0:
                    fill.append(q.popleft())
                    room -= 1
    products = multi[:max_products] + sorted(fill, key=lambda p: p["nameEn"].lower())
    # Category navigation: every product gets a node of the shared tree (taxonomy.py).
    nodes, tree = taxonomy.assign([p.pop("_recs") for p in products], nahdi_tree)
    for p, node in zip(products, nodes):
        p["node"] = node
    now = now or datetime.now(timezone(timedelta(hours=3)))
    # When each store's prices were last read (newest page), so the app can show it.
    last_read: dict[str, str] = {}
    for r in recs:
        t = r.get("fetchedAt")
        if t and t > last_read.get(r["store"], ""):
            last_read[r["store"]] = t
    return {
        "version": 1,
        "generatedAt": now.replace(microsecond=0).isoformat(),
        "city": "riyadh",
        "sample": False,
        "stores": [{"id": s.id, "nameAr": s.nameAr, "nameEn": s.nameEn, "kind": s.kind, "website": s.website,
                    **({"updatedAt": last_read[s.id]} if s.id in last_read else {})}
                   for s in stores if getattr(s, "listed", True)],
        "categories": [{"id": c, "nameAr": a, "nameEn": e} for c, a, e in CATEGORIES],
        "tree": tree,
        "products": products,
    }
