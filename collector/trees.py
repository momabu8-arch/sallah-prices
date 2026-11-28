"""The category trees Sallah borrows from stores, and the app's top-level sections built on them.

Mostafa's rule (2026-11-24): each section of the app uses the category tree of the store that is
strongest in it, and products from every other store are placed into that same tree.

- Medicines, beauty, mother & baby: Nahdi's tree. It is big (800+ categories, up to 4 levels) and
  changes, so the collector reads it from Nahdi's own sitemap every run (stores.nahdi_tree) and keeps
  a copy in the state folder.
- Groceries, drinks, cleaning & home, pets: Panda's tree (read from panda.sa on 2026-11-24, below).
  Bin Dawood was the first choice for cleaning, but its site doesn't load for our collector.
"""
from __future__ import annotations

# Sections: (id, Arabic, English, store whose tree is used, that store's top categories used here).
# Nahdi tops are the first part of its category web addresses; Panda tops are its category numbers.
SECTIONS = [
    ("health", "الأدوية والصحة", "Medicines & health", "nahdi", [
        "العلاجات-بدون-وصفة", "العلاجات-الوصفية", "medicines-treatment", "الفيتامينات-والمكملات-الغذائية",
        "مكملات-رياضية", "التغذية-الصحية", "الإسعافات-الأولية-والعناية-بالجروح", "الأجهزة-الصحية",
        "الدعامات-والتعافي", "رعاية-كبار-السن", "العدسات-اللاصقة", "الملابس-الطبية",
    ]),
    ("beauty", "العناية والجمال", "Personal care & beauty", "nahdi", [
        "العناية-بالبشرة", "المكياج", "العطور", "العناية-بالشعر", "الاستحمام-والعناية-بالجسم",
        "العناية-بالفم-والأسنان", "العناية-بالرجال", "العناية-النسائية", "إكسسوارات-الجمال",
    ]),
    ("baby", "الأم والطفل", "Mother & baby", "nahdi", ["العناية-بالطفل", "عناية-الأطفال", "رعاية-الأم"]),
    ("food", "البقالة", "Groceries", "panda", ["311", "235", "211", "466", "467", "468", "238"]),
    ("drinks", "المشروبات والمياه", "Drinks & water", "panda", ["288", "815"]),
    ("home", "المنظفات والمنزل", "Cleaning & home", "panda", ["273"]),
    ("pets", "الحيوانات الأليفة", "Pets", "panda", ["269"]),
    # Sections whose tree is the owner store's own page breadcrumbs (taxonomy.Tree.add_path_sections).
    ("electronics", "الإلكترونيات والأجهزة", "Electronics & appliances", "extra", []),
    ("furniture", "الأثاث والديكور", "Furniture & décor", "ikea", []),
    ("kids", "ألعاب وملابس الأطفال", "Kids: toys & clothes", "mumzworld", []),
    ("other", "أخرى", "Other", None, []),
]

# Sections built from a store's breadcrumbs (section id -> store id); see SECTIONS above.
PATH_SECTIONS = {"electronics": "extra", "furniture": "ikea", "kids": "mumzworld"}

# Shops that only sell some kinds of products: their products stay inside these sections.
STORE_HINTS = {
    "faces": ["beauty"],
    "extra": ["electronics"],
    "almanea": ["electronics"],
    "saco": ["home", "electronics", "furniture"],
    "ikea": ["furniture", "home", "electronics", "kids"],
}

# Panda: top categories (id, Arabic, English) and their sub-categories (id, parent, Arabic).
PANDA_TOPS = [
    ("311", "الطازج", "Fresh"), ("235", "المخبوزات", "Bakery"), ("211", "المجمدات", "Frozen"),
    ("466", "الأغذية الأساسية", "Food basics"), ("467", "مستلزمات الطبخ", "Cooking essentials"),
    ("468", "الإفطار", "Breakfast"), ("238", "الوجبات الخفيفة", "Snacks"), ("288", "المشروبات", "Beverages"),
    ("815", "المياه", "Water"), ("273", "المنزل", "Household"), ("269", "الحيوانات الأليفة", "Pets"),
    ("209", "العناية الشخصية", "Personal care"), ("228", "الأطفال", "Baby care"),
    ("427", "الجمال", "Beauty care"), ("340", "الإلكترونيات", "Electronics"),
]
PANDA_SUBS = [
    ("330", "209", "الصيدلية"), ("334", "311", "تمور"), ("339", "340", "أجهزة المطبخ"),
    ("349", "311", "الجبنة و اللبنة"), ("350", "311", "الأجبان والمقبلات"), ("352", "311", "الفواكه و الخضروات"),
    ("353", "311", "اللحوم والدواجن"), ("354", "311", "الأسماك والمأكولات البحرية"), ("356", "311", "الألبان والبيض"),
    ("357", "235", "الخبز"), ("358", "235", "الشابورة"), ("359", "235", "الكرواسون والمعجنات"),
    ("360", "235", "الحلويات والكعك"), ("361", "235", "الدونات و كيك المفن"), ("362", "211", "الفواكه و الخضروات"),
    ("363", "211", "البطاطس المقلية وحلقات بصل"), ("364", "211", "اللحوم والدواجن"),
    ("365", "211", "الأسماك والمأكولات البحرية"), ("366", "211", "المعجنات و البيتزا والسمبوسة"),
    ("367", "211", "الآيس كريم والحلويات"), ("368", "466", "الأرز والحبوب"), ("369", "466", "الزيت و السمن"),
    ("370", "466", "المعكرونة والنودلز"), ("371", "467", "الصوصات والتتبيلات"), ("372", "467", "مكونات الطبخ"),
    ("373", "467", "الفواكه المجففة والمكسرات والبذور"), ("374", "467", "الشوربة"), ("375", "467", "المعلبات"),
    ("376", "468", "حبوب الإفطار"), ("377", "468", "المربى و الاطعمة القابلة للدهن"), ("378", "467", "الحلويات"),
    ("379", "468", "العسل"), ("380", "467", "الخبز المنزلي"), ("381", "466", "السكر والمحليات"),
    ("382", "467", "الأغذية العالمية و الأغذية الآسيوية"), ("383", "467", "الزيتون والمخللات"),
    ("384", "288", "المشروبات الغازية"), ("385", "288", "مشروبات الطاقة"), ("386", "288", "العصائر"),
    ("388", "288", "الشاي والمشروبات العشبية"), ("389", "288", "القهوة"), ("390", "288", "مشروبات أخرى"),
    ("391", "238", "الشوكولاتة"), ("392", "238", "الفشار"), ("393", "238", "رقائق البطاطس"),
    ("394", "238", "البسكويت و الكوكيز"), ("395", "238", "اللبان و حلوى النعناع"),
    ("396", "238", "المكسرات والفواكه المجففة"), ("397", "238", "الحلويات وحلويات الجيلي"),
    ("399", "238", "الوجبات خفيفة صحية"), ("400", "228", "الحفائض"), ("401", "228", "مناديل مبلله للاطفال"),
    ("402", "228", "مستلزمات الأطفال"), ("403", "228", "حليب الأطفال"), ("405", "427", "العناية بالوجه و البشرة"),
    ("406", "209", "العناية بالشعر"), ("407", "209", "العناية بالفم"), ("408", "209", "الاستحمام والصابون"),
    ("409", "209", "العناية الشخصية النسائية"), ("410", "209", "العناية الشخصية الرجالية"),
    ("411", "273", "مستلزمات غسيل الملابس"), ("412", "273", "ورق المرحاض"), ("413", "273", "لفائف المطبخ"),
    ("414", "273", "المناديل"), ("415", "273", "مستلزمات التنظيف"), ("416", "273", "مستلزمات غسل الأطباق"),
    ("417", "273", "ملطفات الجو"), ("418", "273", "المستلزمات المنزلية الضرورية وتخزين المواد الغذائية"),
    ("420", "273", "مستلزمات تنظيف الأرضيات"), ("421", "273", "مستلزمات التخييم"), ("422", "269", "القطط"),
    ("424", "269", "الكلاب"), ("428", "228", "أغذية الأطفال والوجبات الخفيفة"), ("429", "228", "إكسسوارات أطفال"),
    ("430", "209", "العناية بالجسم"), ("431", "427", "اكسسوارات التجميل و المكياج"), ("433", "340", "الإكسسوارات"),
    ("465", "211", "الجاهز للخبز و الأكل"), ("469", "468", "حليب طويل الأجل و مشتقاته"),
    ("474", "273", "المبيدات الحشرية"), ("475", "427", "العطور"), ("805", "273", "منتجات استهلاكية"),
    ("810", "273", "الأدوات المنزلية"), ("811", "273", "شنط السفر"), ("812", "273", "قرطاسية"), ("813", "273", "ألعاب"),
    ("814", "340", "مستلزمات المنزل والتنظيف"), ("821", "815", "مياه معدنية"), ("822", "815", "مياه غازية"),
    ("856", "340", "السماعات والأجهزة القابلة للارتداء"), ("969", "815", "مياة جوز هند"), ("971", "815", "مياه منكهة"),
    ("972", "815", "مياه فاخرة"),
]

# English names for Panda sub-categories (from panda.sa's English web addresses).
PANDA_SUBS_EN = {
    "334": "Dates", "349": "Cheese & labneh", "350": "Deli", "352": "Fruits & vegetables", "353": "Meat & poultry",
    "354": "Fish & seafood", "356": "Dairy & eggs", "357": "Breads & rolls", "358": "Rusks",
    "359": "Croissants & pastries", "360": "Desserts & cakes", "361": "Donuts & muffins", "362": "Fruits & vegetables",
    "363": "French fries & onion rings", "364": "Meat & poultry", "365": "Fish & seafood",
    "366": "Pizza, pastries & sambusa", "367": "Ice creams & desserts", "368": "Rice & grains", "369": "Oil & ghee",
    "370": "Pasta & noodles", "371": "Sauces, marinades & dressing", "372": "Cooking ingredients",
    "373": "Dried fruits, nuts & seeds", "374": "Soup", "375": "Tinned cans & packets", "376": "Cereal",
    "377": "Jams & spreads", "378": "Desserts", "379": "Honey", "380": "Home baking", "381": "Sugar & sweeteners",
    "382": "World & Asian foods", "383": "Olives & pickles", "384": "Soft drinks", "385": "Energy drinks",
    "386": "Juices", "388": "Tea & herbal drinks", "389": "Coffee", "390": "Other drinks", "391": "Chocolate",
    "392": "Popcorn", "393": "Chips", "394": "Biscuits & cookies", "395": "Mints & gums", "396": "Nuts & dried fruits",
    "397": "Candies & jelly sweets", "399": "Healthy snacks", "411": "Laundry", "412": "Toilet paper",
    "413": "Kitchen rolls", "414": "Tissues", "415": "Cleaning supplies", "416": "Dishwashing", "417": "Air fresheners",
    "418": "Home essentials & food storage", "420": "Floor cleaning", "421": "Camping", "422": "Cats", "424": "Dogs",
    "465": "Ready to bake & eat", "469": "Long-life milk", "474": "Insecticides", "805": "Disposables",
    "810": "Housewares", "811": "Travel bags", "812": "Stationery", "813": "Toys", "821": "Mineral water",
    "822": "Sparkling water", "969": "Coconut water", "971": "Flavoured water", "972": "Premium water",
}

# Which sections a product can belong to, from its store's own top category. Used when the
# words alone don't decide (e.g. Tamimi's "FRESH / ..." can only be groceries).
# (store, first part of the store's category or the store's top category id) -> sections, best first.
SECTION_HINTS = {
    ("tamimi", "FOOD & BEVERAGES"): ["food", "drinks"],
    ("tamimi", "FRESH"): ["food"],
    ("tamimi", "HOUSEHOLD"): ["home"],
    ("tamimi", "HEALTH & BEAUTY"): ["beauty", "health"],
    ("tamimi", "HEALTHY LIVING"): ["food", "drinks", "health"],
    ("tamimi", "BABY"): ["baby"],
    ("tamimi", "PETS"): ["pets"],
    ("panda", "209"): ["beauty", "health"],
    ("panda", "228"): ["baby"],
    ("panda", "427"): ["beauty"],
    ("nahdi", "القهوة"): ["drinks"],
    ("nahdi", "العناية-بالمنزل"): ["home"],
    ("nahdi", "النظافة-والتعقيم"): ["home"],
    ("nahdi", "العناية-بالحيوانات-الأليفة"): ["pets"],
}
