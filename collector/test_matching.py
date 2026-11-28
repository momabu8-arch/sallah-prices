"""Run: python3 collector/test_matching.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matching  # noqa: E402
import stores  # noqa: E402

assert matching.parse_size("Card Chocolate & Milk Wafer 10 x 25.6g") == (256.0, "g")
assert matching.parse_size("Almarai Milk 1.5 L") == (1.5, "l")
assert matching.parse_size("حليب المراعي 1 لتر") == (1.0, "l")
assert matching.parse_size("Panadol 24 Tablets") == (24.0, "pcs")
assert matching.parse_size("Something") == (1.0, "pcs")
assert matching.parse_size("Galaxy 12gm") == (12.0, "g")
assert matching.parse_size("توب بار الشوكولاتة ٢١ جرام") == (21.0, "g")
assert matching.parse_size("شوكولاتة جالكسي فلوتس، 2 إصبع، 22.5 جرام") == (22.5, "g")

a = matching.name_key("Almarai Full Fat Milk 1 L")
b = matching.name_key("almarai milk full-fat 1000ml")
assert a == b, (a, b)
assert matching.name_key("Milk") is None           # too vague
assert matching.name_key("Almarai Milk") is None   # no size
assert matching.name_key("Almarai Milk 1L") != matching.name_key("Almarai Milk 2L")

assert stores.slug_to_name("almarai-full-fat-milk-1l") == "Almarai Full Fat Milk 1l"
assert stores.gtin("6281007025066") == "6281007025066"
assert stores.gtin("1149") is None

recs = [
    {"sid": "panda:1", "store": "panda", "nameAr": "حليب", "nameEn": "Almarai Milk Full Fat 1l", "brand": "المراعي",
     "category": "الألبان", "price": 6.5, "was": None, "inStock": True, "url": "u1", "image": "i1", "barcode": "06281007025066"},
    {"sid": "tamimi:1", "store": "tamimi", "nameAr": "حليب كامل", "nameEn": "Almarai Full Fat Milk 1 L", "brand": "Almarai",
     "category": "DAIRY", "price": 6.25, "was": 7.0, "inStock": True, "url": "u2", "image": None, "barcode": "6281007025066"},
    {"sid": "nahdi:1", "store": "nahdi", "nameAr": "بنادول", "nameEn": "Panadol Advance 24 Tablets", "brand": "",
     "category": "مسكنات", "price": 9.0, "was": None, "inStock": True, "url": "u3", "image": "i3", "barcode": None},
    {"sid": "aldawaa:1", "store": "aldawaa", "nameAr": "بنادول أدفانس", "nameEn": "Panadol Advance 24 Tablet", "brand": "",
     "category": "", "price": 8.5, "was": None, "inStock": True, "url": "u4", "image": None, "barcode": None},
    {"sid": "aldawaa:2", "store": "aldawaa", "nameAr": "بنادول", "nameEn": "Panadol Advance 24 Tablets", "brand": "",
     "category": "", "price": 8.75, "was": None, "inStock": True, "url": "u5", "image": None, "barcode": None},
]
c = matching.build_catalog(recs, stores.ALL)
ps = c["products"]
milk = next(p for p in ps if p["barcode"])
assert [o["store"] for o in milk["offers"]] == ["tamimi", "panda"], milk
assert milk["nameEn"] == "Almarai Full Fat Milk 1 L" and milk["image"] == "i1"
assert milk["category"] == "dairy", milk["category"]
assert (milk["size"], milk["unit"]) == (1.0, "l")
panadol = next(p for p in ps if p["nameEn"].startswith("Panadol") and len(p["offers"]) == 2)
assert {o["store"]: o["price"] for o in panadol["offers"]} == {"nahdi": 9.0, "aldawaa": 8.5}  # cheaper of the two Al-Dawaa listings, panadol
assert panadol["category"] == "pharmacy"
assert c["sample"] is False and len(c["stores"]) == len([s for s in stores.ALL if s.listed])
print("matching tests passed:", len(ps), "products")

# Sitemaps that wrap addresses in CDATA (Lemon)
assert stores.locs("<loc><![CDATA[https://lemon.sa/a?x=1&y=2]]></loc>") == ["https://lemon.sa/a?x=1&y=2"]
assert stores.english_slug_name("gauze-roll-10pieces") == "Gauze Roll 10pieces"
assert stores.english_slug_name("%D9%84%D9%88%D8%B4%D9%86-200") == ""

page = """<script type="application/ld+json">{"@type":"Product","name":"كريم 21 400مل","sku":"03107106",
"brand":{"name":"nonfood_star"},"image":"https://x/i.jpg","offers":{"@type":"Offer","price":"34.50",
"availability":"http://schema.org/InStock"}}</script>"""
r = stores.lemon_parse("https://lemon.sa/index.php?route=product/product&product_id=11797", page)
assert r["sid"] == "lemon:03107106" and r["price"] == 34.5 and r["barcode"] is None and r["brand"] == "", r

# robots.txt wildcards
import collect  # noqa: E402
rb = collect.Robots("User-agent: *\nDisallow: /*.html\nDisallow: /*?\nAllow: */*?p=\nUser-agent: GPTBot\nDisallow: /\n")
assert rb.allowed("https://x/mafsau/ar/a/p/1") and not rb.allowed("https://x/a.html")
assert not rb.allowed("https://x/a?b=1") and rb.allowed("https://x/a?p=2")
print("all matching tests passed")

# The price file: valid JSON, one product per line
import json as _json, tempfile as _tf
_c = matching.build_catalog(recs, stores.ALL)
with _tf.TemporaryDirectory() as d:
    collect.save_catalog(d + "/c.json", _c)
    text = open(d + "/c.json", encoding="utf-8").read()
assert _json.loads(text) == _json.loads(_json.dumps(_c))
lines = text.split("\n")
assert lines[0].endswith('"products":[') and lines[1].startswith('{"id"') and lines[-2] == "]}", lines[:2]

# Fuzzy matching across stores without barcodes
import fuzzy  # noqa: E402
assert fuzzy.find_size("Daisy Sour Cream 16oz") == (16 * 28.35, "g")
assert fuzzy.find_size("حليب ١.٥ لتر") == (1500.0, "ml")
assert fuzzy.find_size("Nestle Mega 12x95 Ml") == (1140.0, "ml")
assert fuzzy.find_size("Panadol") is None
assert fuzzy.find_size("Panadol Extra 500mg 24tablets") == (24.0, "pcs")
assert fuzzy.find_size("بنادول إكسترا 500 ملجم 24 قرص") == (24.0, "pcs")
assert fuzzy.find_size("Vitamin D 1000 mg") == (1000.0, "mg")
assert fuzzy.same_size(fuzzy.find_size("16oz"), fuzzy.find_size("454 g"))
R = lambda store, en, ar="", brand="": {"store": store, "nameEn": en, "nameAr": ar, "brand": brand, "price": 1}
filler = [R("x", f"Filler Item Number{i} Word{i % 50} 100g") for i in range(600)]
cases = [
    R("panda", "Goody Light Tuna No Drain 125g"), R("tamimi", "Light No Drain Tuna 125g", brand="Goody"),   # same
    R("panda", "Almarai Milk Full Fat 1l"), R("tamimi", "Almarai Low Fat Milk 1 L"),                     # full vs low fat
    R("nahdi", "Alfred Verne Sacred Isle Eau De Parfum 80 Ml"), R("whites", "Alfred Verne Sapphire Isle Eau De Parfum 80 Ml"),
    R("nahdi", "Sensodyne Toothpaste Deep Clean Extra Soft"), R("panda", "Sensodyne Toothbrush Deep Clean Soft", brand="Sensodyne"),
    R("nahdi", "Lady Speed Stick Bio Control Deodorant 45gm"), R("whites", "Lady Speed Stick Bio Control Deodorant 45g"),
    R("nahdi", "Head And Shoulders Shampoo 400ml"), R("whites", "Head And Shoulders Shampoo 200ml"),        # size differs
    R("panda", "Panadol Extra Tablets 24pcs"), R("whites", "Panadol Extra 500mg 24tablets"),               # dose is not the size
]
base = len(filler)
found = {(i - base, j - base) for i, j, _ in fuzzy.links(filler + cases) if i >= base}
assert found == {(0, 1), (8, 9), (12, 13)}, found
gen = {"milk", "full", "fat"}
assert fuzzy.kind_words("Almarai Full Fat Milk 1L", gen) == "fat full milk"
print("fuzzy matching tests passed")

# Category tree: owner stores place their own products, others are placed by example.
import taxonomy  # noqa: E402
NAHDI = [{"id": "72436", "ar": ["العلاجات-بدون-وصفة", "مسكنات-الألم", "مسكنات-الألم-والحمى-للبالغين"],
          "en": ["otc-treatments", "pain-killers", "adult-pain-fever"]},
         {"id": "69391", "ar": ["المكياج", "الشفاه", "أحمر-شفاه"], "en": []}]
T = lambda store, en, cat="", path=None: {"store": store, "nameEn": en, "nameAr": "", "brand": "", "category": cat, "path": path or []}
groups = [[T("nahdi", "Panadol Extra Tablets", "مسكنات الألم والحمى للبالغين")] for _ in range(3)] + \
         [[T("nahdi", "Lipstick Red", path=["المكياج", "الشفاه", "أحمر شفاه"])]] + \
         [[T("panda", "Tide Laundry Powder", "مستلزمات غسيل الملابس")] for _ in range(3)] + \
         [[T("panda", "Frozen Chicken Breast", "اللحوم والدواجن")], [T("panda", "Fresh Chicken Breast", "اللحوم والدواجن")]] + \
         [[T("tamimi", "Panadol Extra 24 Tablets", "HEALTH / PAIN")], [T("tamimi", "Tide Laundry Powder 2kg", "HOUSEHOLD / LAUNDRY")],
          [T("tamimi", "Something Unknown")]]
nodes, tree = taxonomy.assign(groups, NAHDI)
assert nodes[0] == "n72436" and nodes[3] == "n69391", nodes
assert nodes[4] == "p411" and nodes[7] == "p364" and nodes[8] == "p353", nodes
assert nodes[9] == "n72436", nodes      # Tamimi's Panadol lands in Nahdi's tree
assert nodes[10] == "p411", nodes       # Tamimi's Tide lands in Panda's laundry
assert nodes[11] == "other", nodes
ids = {n["id"]: n for n in tree}
assert ids["n72436"]["nameEn"] == "Adult pain fever" and ids["home"]["parent"] is None
assert "p415" not in ids  # empty categories are not published
print("category tree tests passed")

assert fuzzy.find_size("Pampers Ultimate Comfort Pants Diapers Size 6 16 Kg Super Saving Pack 34 Count") == (34.0, "pcs")
assert fuzzy.find_size("بامبرز حفاضات كلوت مقاس 6 16+ كجم 34 حفاضة") == (34.0, "pcs")
print("diaper size tests passed")
# Multi-buy offers
assert matching.parse_deal("1 + 1 مجانا", 30.06) == {"qty": 2, "price": 30.06}
assert matching.parse_deal("اشتر 2 واحصل على 1 مجاناً", 10) == {"qty": 3, "price": 20}
assert matching.parse_deal("Buy 2 Get 1 Free", 10) == {"qty": 3, "price": 20}
assert matching.parse_deal("3 بـ 25", 10) == {"qty": 3, "price": 25}
assert matching.parse_deal("خصم 50% على القطعة الثانية", 10) == {"qty": 2, "price": 15}
assert matching.parse_deal("35% أقل", 10) is None
assert matching.parse_deal(None, 10) is None
html = 'x\\"price\\":30.06,\\"promo_badge\\":\\"1 + 1 مجانا\\",\\"pl\\":0'
assert stores.rsc_text(html, "promo_badge") == "1 + 1 مجانا", stores.rsc_text(html, "promo_badge")
assert stores.rsc_text('"mix_match_promo":null,', "mix_match_promo") is None
assert stores.rsc_text('"mix_match_promo":{"id":3,"label":"اشتر 2 واحصل على 1"}', "mix_match_promo") == "اشتر 2 واحصل على 1"
_d = matching.build_catalog([dict(recs[0], promo="1 + 1 مجانا")], stores.ALL)["products"][0]["offers"][0]
assert _d["promo"] == "1 + 1 مجانا" and _d["deal"] == {"qty": 2, "price": 6.5}, _d
print("deal tests passed")

# A hair mist is not the eau de parfum of the same line (Mostafa's report, 2026-11-26).
import fuzzy  # noqa: E402
assert fuzzy.product_form("بارفومز دي مارلي ديلينا عطر للشعر 75 مل") == "hair"
assert fuzzy.product_form("Parfums De Marly Delina Eau De Parfum For Women 75ml", "ماء عطر دي مارلي ديلينا للنساء") == "edp"
assert fuzzy.product_form("Dior Sauvage EDT 100ml") == "edt"
assert fuzzy.product_form("Almarai Milk 1L") is None
pair = [
    {"sid": "nahdi:d", "store": "nahdi", "nameAr": "ماء عطر دي مارلي ديلينا للنساء - 75 مل", "nameEn": "Parfums De Marly Delina Eau De Parfum For Women 75ml",
     "brand": "Parfums De Marly", "price": 1278.55},
    {"sid": "whites:d", "store": "whites", "nameAr": "بارفومز دي مارلي ديلينا عطر للشعر 75 مل", "nameEn": "",
     "brand": "Parfums De Marly", "price": 298.31},
]
assert fuzzy.links(pair) == [], "hair mist matched with eau de parfum"
pair[1]["nameAr"] = "بارفومز دي مارلي ديلينا ماء عطر للنساء 75 مل"
pair[1]["price"] = 300.0
assert fuzzy.links(pair) == [], "a 4x price gap must not be called the same product"
print("product form tests passed")
