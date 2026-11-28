"""Finds the same product in different stores when there is no shared barcode.

Two listings are linked when ALL of these hold:
- same pack size (within 3%, e.g. "16oz" = "454 g"), or both have no size and the same brand;
- their names share most of their meaningful words (rare words like a brand or "halloumi"
  count more than common ones like "milk"), checked in English and in Arabic;
- they don't each carry different variant words (e.g. "full fat" vs "low fat", "SPF 30" vs "SPF 50");
- each is the other's best candidate in that store.
A missed match only means two separate rows; a wrong match shows a wrong price, so the bar is high.

The same word lists also give every product a "kind": its generic words (the ones used by
several brands, like "full fat milk"), so the app can show other brands of the same kind
side by side, compared per kilo, litre or piece.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
AR_NORM = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ـ": ""})
AR_MARKS = re.compile(r"[ً-ْٰ]")

# unit -> (base unit, factor)
UNITS = {
    "g": ("g", 1), "gm": ("g", 1), "gms": ("g", 1), "gr": ("g", 1), "grm": ("g", 1), "gram": ("g", 1), "grams": ("g", 1),
    "جم": ("g", 1), "غ": ("g", 1), "غم": ("g", 1), "غرام": ("g", 1), "جرام": ("g", 1), "جرامات": ("g", 1), "غرامات": ("g", 1),
    "kg": ("g", 1000), "kgs": ("g", 1000), "kilo": ("g", 1000), "كجم": ("g", 1000), "كيلو": ("g", 1000), "كغ": ("g", 1000), "كيلوجرام": ("g", 1000), "كيلوغرام": ("g", 1000),
    "mg": ("mg", 1), "ملجم": ("mg", 1), "مجم": ("mg", 1), "ملغ": ("mg", 1),
    "oz": ("g", 28.35), "lb": ("g", 453.6), "lbs": ("g", 453.6),
    "ml": ("ml", 1), "مل": ("ml", 1), "ملل": ("ml", 1), "مللتر": ("ml", 1), "ملليلتر": ("ml", 1),
    "cl": ("ml", 10), "l": ("ml", 1000), "lt": ("ml", 1000), "ltr": ("ml", 1000), "litre": ("ml", 1000), "liter": ("ml", 1000),
    "لتر": ("ml", 1000), "لترات": ("ml", 1000), "floz": ("ml", 29.57),
    "pcs": ("pcs", 1), "pc": ("pcs", 1), "piece": ("pcs", 1), "pieces": ("pcs", 1), "tablets": ("pcs", 1), "tablet": ("pcs", 1),
    "tabs": ("pcs", 1), "capsules": ("pcs", 1), "capsule": ("pcs", 1), "caps": ("pcs", 1), "sachet": ("pcs", 1), "sachets": ("pcs", 1),
    "pads": ("pcs", 1), "rolls": ("pcs", 1), "roll": ("pcs", 1), "count": ("pcs", 1), "ct": ("pcs", 1), "wipes": ("pcs", 1),
    "diapers": ("pcs", 1), "bags": ("pcs", 1), "softgels": ("pcs", 1), "lozenges": ("pcs", 1), "sheets": ("pcs", 1),
    "حبة": ("pcs", 1), "حبات": ("pcs", 1), "قطعة": ("pcs", 1), "قطع": ("pcs", 1), "قرص": ("pcs", 1), "اقراص": ("pcs", 1),
    "كبسولة": ("pcs", 1), "كبسولات": ("pcs", 1), "كيس": ("pcs", 1), "اكياس": ("pcs", 1), "مناديل": ("pcs", 1), "حفاضات": ("pcs", 1),
    "منديل": ("pcs", 1), "لفة": ("pcs", 1), "لفات": ("pcs", 1),
    "pants": ("pcs", 1), "nappies": ("pcs", 1), "حفاضة": ("pcs", 1), "حفاضه": ("pcs", 1), "كلوت": ("pcs", 1),
}
# Diapers: "Size 6 16 Kg ... 34 Count" — the kilos are the baby's weight, the count is the pack.
DIAPERS = re.compile(r"diaper|nappy|nappies|pull.?ups|\bpants\b|حفاض|كلوت|pampers|huggies|molfix|بامبرز|هجيز|مولفكس", re.I)
_U = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
_NUM = r"(\d+(?:\.\d+)?)"
MULTI = re.compile(rf"{_NUM}\s*[x×*]\s*{_NUM}\s*({_U})(?![a-zء-ي])", re.I)
MULTI_REV = re.compile(rf"{_NUM}\s*({_U})\s*[x×*]\s*{_NUM}(?![\d.])", re.I)
SINGLE = re.compile(rf"(?<![\d.]){_NUM}\s*-?\s*({_U})(?![a-zء-ي])", re.I)
FLOZ = re.compile(r"fl\.?\s*oz", re.I)

STOP_EN = {"with", "and", "the", "for", "of", "a", "an", "in", "pack", "new", "offer", "x", "pcs", "pc", "size", "free",
           "from", "by", "to", "on", "per", "promo", "value", "bundle", "special"}
STOP_AR = {"و", "مع", "من", "في", "على", "عرض", "جديد", "حجم", "عبوة", "علبة", "مجانا", "خاص", "ب", "ل", "او"}
# Brands that are really a store's own label or a country, not a product brand.
COUNTRIES = ("ksa|saudi|saudi arabia|italy|france|usa|uk|spain|turkey|turkiye|china|india|egypt|holland|netherlands|brazil|uae|"
             "germany|belgium|greece|thailand|vietnam|indonesia|malaysia|philippines|pakistan|sri lanka|kenya|south africa|"
             "australia|new zealand|chile|peru|argentina|mexico|jordan|lebanon|syria|oman|kuwait|bahrain|qatar|yemen|morocco|"
             "tunisia|poland|ireland|denmark|sweden|switzerland|austria|portugal|japan|korea|canada|ukraine|russia|iran|ethiopia")
JUNK_BRANDS = re.compile(rf"tamimi|^(?:{COUNTRIES}|others?|freshly|generic|na|n/a|no brand|local)$", re.I)
# Words that mark a different version of the same product line. Two names that each have
# a different one of these are never the same product.
VARIANT_GROUPS = [
    {"full", "low", "skimmed", "skim", "light", "lite", "zero", "diet", "regular", "half"},
    {"كامل", "قليل", "خالي", "لايت", "دايت", "زيرو"},
    {"men", "women", "unisex", "kid", "baby", "boy", "girl"},
    {"رجال", "رجالي", "نساء", "نسائي", "اطفال", "اولاد", "بنات"},
]
# What kind of item a fragrance or care product is. Two names with different forms are never the
# same product, even with the same brand, line and size (e.g. Delina hair mist vs Delina eau de parfum).
# The first form found wins, so gift sets and hair/body mists are checked before the perfume strengths.
FORMS = [
    ("set", r"\bgift set\b|\bset\b|\bkit\b|مجموعة|مجموعه|طقم|بوكس هدايا|علبة هدايا"),
    ("hair", r"hair (?:mist|perfume|fragrance|spray)|عطر (?:لل|ال)?شعر|معطر (?:لل|ال)?شعر|بخاخ (?:لل|ال)?شعر|ميست (?:لل|ال)?شعر"),
    ("body", r"body (?:mist|spray|splash)|بخاخ (?:لل|ال)?جسم|معطر (?:لل|ال)?جسم|ميست (?:لل|ال)?جسم|سبلاش"),
    ("deo", r"deodorant|antiperspirant|\bdeo\b|مزيل (?:لل|ال)?عرق|مضاد (?:لل|ال)?تعرق"),
    ("lotion", r"body lotion|lotion|لوشن|لوسيون"),
    ("gel", r"shower gel|bath gel|جل (?:لل|ال)?استحمام|شاور جل"),
    ("extrait", r"extrait|اكستريت|إكستريت|اكستريه"),
    ("edc", r"eau de cologne|\bedc\b|كولونيا|كولونيه"),
    ("edt", r"eau de toilette|\bedt\b|تواليت"),
    ("edp", r"eau de parfum|\bedp\b|بارفان|برفان|ماء العطر|ماء عطر|او دو بارفيوم"),
]
_FORMS = [(f, re.compile(rx, re.I)) for f, rx in FORMS]


def product_form(*texts: str) -> str | None:
    t = " ".join(x for x in texts if x)
    t = re.sub(r"[ًٌٍَُِّْـ]", "", t)
    return next((f for f, rx in _FORMS if rx.search(t)), None)


# Prices of the same product rarely differ this much between stores; a bigger gap means a wrong match.
MAX_PRICE_RATIO = 2.5

# A word this rare (seen in under ~1 in 500 listings) names something specific: a scent, a flavour
# line, a model. If each name has one the other lacks, they are different products.
RARE = math.log(500)


def norm_ar(text: str) -> str:
    return AR_MARKS.sub("", text.translate(AR_NORM))


def find_size(*texts: str) -> tuple[float, str] | None:
    """Total pack size in a base unit (g, ml, mg or pcs), from the first text that has one."""
    for t in texts:
        if not t:
            continue
        t = norm_ar(t.translate(ARABIC_DIGITS)).replace("٫", ".").replace(",", ".").lower()
        t = FLOZ.sub("floz", t)
        m = MULTI.search(t)
        if m:
            base, f = UNITS[m.group(3)]
            return float(m.group(1)) * float(m.group(2)) * f, base
        m = MULTI_REV.search(t)
        if m:
            base, f = UNITS[m.group(2)]
            return float(m.group(1)) * float(m.group(3)) * f, base
        # "Panadol Extra 500mg 24 tablets": 500 mg is the dose, 24 tablets is the pack.
        # A strength in mg only counts as the size when nothing else in the name does.
        found = [(float(m.group(1)) * UNITS[m.group(2)][1], UNITS[m.group(2)][0]) for m in SINGLE.finditer(t) if float(m.group(1)) > 0]
        if DIAPERS.search(t):
            found = [x for x in found if x[1] == "pcs"]
            if not found:
                continue
        pack = [x for x in found if x[1] != "mg"]
        if pack or found:
            return (pack or found)[0]
    return None


def size_label(size: tuple[float, str] | None) -> str:
    if not size:
        return "-"
    v, u = size
    return f"{float(f'{v:.2g}'):g}{u}"  # two significant digits: 453.6 g and 454 g land together


def same_size(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return a[1] == b[1] and abs(a[0] - b[0]) <= 0.03 * max(a[0], b[0])


def _strip_sizes(t: str) -> str:
    t = FLOZ.sub("floz", t)
    for rx in (MULTI, MULTI_REV, SINGLE):
        t = rx.sub(" ", t)
    return t


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens_en(name: str, brand: str = "") -> list[str]:
    t = _strip_sizes(name.lower().replace("&", " and ").replace("'", "").translate(ARABIC_DIGITS))
    words = [_stem(w) for w in re.split(r"[^a-z0-9]+", t) if w and w not in STOP_EN]
    words = [w for w in words if not w.isdigit() or len(w) <= 4]  # long digit runs are product codes
    if brand and re.fullmatch(r"[A-Za-z0-9&' .\-]+", brand) and not JUNK_BRANDS.search(brand.strip()):
        for w in re.split(r"[^a-z0-9]+", brand.lower().replace("'", "")):
            if w and w not in STOP_EN and w not in words:
                words.append(_stem(w))
    return words


def tokens_ar(name: str, brand: str = "") -> list[str]:
    t = _strip_sizes(norm_ar(name.lower().translate(ARABIC_DIGITS)))
    if brand and re.search(r"[ء-ي]", brand):
        t += " " + norm_ar(brand)
    out = []
    for w in re.split(r"[^0-9a-zء-ي]+", t):
        if not w or w in STOP_AR:
            continue
        if w.startswith("ال") and len(w) > 4:
            w = w[2:]
        elif w.startswith("وال") and len(w) > 5:
            w = w[3:]
        if w not in out:
            out.append(w)
    return out


class Item:
    __slots__ = ("i", "store", "size", "en", "ar", "brand", "form", "price")

    def __init__(self, i, rec):
        self.i = i
        self.store = rec["store"]
        self.size = find_size(rec.get("nameAr", ""), rec.get("nameEn", ""), rec.get("size", ""))
        self.en = set(tokens_en(rec.get("nameEn", ""), rec.get("brand", "")))
        self.ar = set(tokens_ar(rec.get("nameAr", ""), rec.get("brand", "")))
        b = (rec.get("brand") or "").strip().lower()
        self.brand = "" if JUNK_BRANDS.search(b) else norm_ar(b)
        self.form = product_form(rec.get("nameEn", ""), rec.get("nameAr", ""))
        self.price = rec.get("price") or 0


def _weights(items, attr):
    df = Counter()
    for it in items:
        df.update(getattr(it, attr))
    n = max(len(items), 2)
    return {w: math.log(n / c) for w, c in df.items()}, df


def _score(a: set, b: set, w: dict) -> float:
    if not a or not b:
        return 0.0
    common = a & b
    if not common:
        return 0.0
    wa_only = sum(w[x] for x in a - b)
    wb_only = sum(w[x] for x in b - a)
    wc = sum(w[x] for x in common)
    total_a, total_b = wc + wa_only, wc + wb_only
    # Both names carry their own distinctive words -> different variants.
    if min(wa_only / total_a, wb_only / total_b) > EXCLUSIVE_MAX:
        return 0.0
    if any(w[x] >= RARE for x in a - b) and any(w[x] >= RARE for x in b - a):
        return 0.0
    nums_a = {x for x in a if any(c.isdigit() for c in x)}
    nums_b = {x for x in b if any(c.isdigit() for c in x)}
    if nums_a and nums_b and nums_a != nums_b:
        return 0.0
    for g in VARIANT_GROUPS:
        va, vb = a & g, b & g
        if va and vb and va != vb:
            return 0.0
    return wc / (wc + wa_only + wb_only)


THRESHOLD = 0.62
EXCLUSIVE_MAX = 0.2
NO_SIZE_THRESHOLD = 0.8


def links(records: list[dict]) -> list[tuple[int, int, float]]:
    """Pairs of record indexes (from different stores) that are the same product."""
    items = [Item(i, r) for i, r in enumerate(records)]
    w_en, df_en = _weights(items, "en")
    w_ar, df_ar = _weights(items, "ar")
    buckets: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        buckets[size_label(it.size)].append(it)

    best: dict[tuple[int, str], tuple[float, int]] = {}
    for label, group in buckets.items():
        if len({it.store for it in group}) < 2:
            continue
        index_en: dict[str, list[Item]] = defaultdict(list)
        index_ar: dict[str, list[Item]] = defaultdict(list)
        for it in group:
            # Index each listing under its rarest words only; a real match shares at least one.
            for w in sorted(it.en, key=lambda x: df_en[x])[:3]:
                index_en[w].append(it)
            for w in sorted(it.ar, key=lambda x: df_ar[x])[:3]:
                index_ar[w].append(it)
        need = NO_SIZE_THRESHOLD if label == "-" else THRESHOLD
        for a in group:
            cands = {}
            for w in sorted(a.en, key=lambda x: df_en[x])[:3]:
                for b in index_en[w]:
                    cands[b.i] = b
            for w in sorted(a.ar, key=lambda x: df_ar[x])[:3]:
                for b in index_ar[w]:
                    cands[b.i] = b
            for b in cands.values():
                if b.store == a.store or b.i <= a.i or not same_size(a.size, b.size):
                    continue
                if label == "-" and (not a.brand or a.brand != b.brand):
                    continue
                if (a.form or b.form) and a.form != b.form and a.form and b.form:
                    continue
                if a.price and b.price and max(a.price, b.price) / min(a.price, b.price) > MAX_PRICE_RATIO:
                    continue
                # English names are cleaner (Arabic ones mix in English words and spelling varies),
                # so Arabic decides only when a store has no English name.
                s = _score(a.en, b.en, w_en) if a.en and b.en else _score(a.ar, b.ar, w_ar)
                if s < need:
                    continue
                for x, y in ((a, b), (b, a)):
                    k = (x.i, y.store)
                    if s > best.get(k, (0.0, -1))[0]:
                        best[k] = (s, y.i)
    out = []
    for (i, store_j), (s, j) in best.items():
        if i < j and best.get((j, records[i]["store"]), (0, -1))[1] == i:
            out.append((i, j, s))
    return out


def generic_words(records: list[dict], min_brands: int = 3) -> set[str]:
    """English words used by at least `min_brands` different brands: product kinds, not brand names."""
    brands_of: dict[str, set] = defaultdict(set)
    for r in records:
        b = (r.get("brand") or "").strip().lower()
        toks = tokens_en(r.get("nameEn", ""))
        if not b or JUNK_BRANDS.search(b):
            b = toks[0] if toks else ""
        for w in toks:
            brands_of[w].add(b)
    return {w for w, bs in brands_of.items() if len(bs) >= min_brands and not w.isdigit() and len(w) > 1}


def kind_words(name_en: str, generic: set[str]) -> str | None:
    """'Almarai Full Fat Milk 1L' -> 'fat full milk': what kind of product it is, with the brand left out,
    so the app can line up other brands of the same kind and compare them per kilo or litre."""
    words = sorted({w for w in tokens_en(name_en) if w in generic and not any(c.isdigit() for c in w)})
    return " ".join(words) or None
