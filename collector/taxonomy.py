"""Puts every product into one category tree, built from the trees of the strongest store per section
(see trees.py).

1. Build the tree: sections on top, then the owner store's own categories under each section.
2. A product sold by the owner store gets the owner's category straight from that store's page
   (Nahdi: page breadcrumb or category name; Panda: category name).
3. Every other product (Tamimi, Whites, Panda's beauty items, Nahdi's household items...) is placed by
   example: words in its names, its brand and its store's own category are compared with the products
   already placed. It goes as deep into the tree as the evidence is clear, and stops higher up when not.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict

import trees

_DIACRITICS = re.compile(r"[ً-ْٰـ]")
_WORD = re.compile(r"[a-zء-ي]+")
_ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
# Words that say nothing about the kind of product.
_STOP = {
    "with", "and", "the", "for", "of", "pack", "pcs", "piece", "pieces", "new", "offer", "free", "size", "ml", "gm", "kg",
    "من", "مع", "في", "على", "عرض", "حبة", "حبه", "قطعة", "قطعه", "جرام", "جم", "مل", "لتر", "كجم", "كيلو", "عبوة", "عبوه",
    "اللون", "لون", "حجم", "مجموعة", "مجموعه",
}


def key(text: str) -> str:
    """Same key for "أحمر-شفاه" (web address) and "أحمر شفاه" (page text)."""
    t = _DIACRITICS.sub("", (text or "").lower()).translate(_ARABIC_FOLD)
    return "".join(_WORD.findall(t))


def words(text: str) -> list[str]:
    t = _DIACRITICS.sub("", (text or "").lower()).translate(_ARABIC_FOLD)
    return [w for w in _WORD.findall(t) if len(w) >= 3 and w not in _STOP]


def _pretty_en(slug: str) -> str:
    t = slug.replace("-", " ").strip()
    t = re.sub(r"\b(otc|rx|edt|edp|edc)\b", lambda m: m.group(1).upper(), t)
    return t[:1].upper() + t[1:]


class Tree:
    def __init__(self, nahdi_nodes: list[dict] | None):
        self.nodes: dict[str, dict] = {}       # id -> {id, parent, nameAr, nameEn, section}
        self.children: dict[str, list[str]] = defaultdict(list)
        self.nahdi_by_path: dict[tuple, str] = {}   # tuple of keys -> node id
        self.nahdi_by_name: dict[str, str] = {}     # key of last name -> shallowest node id
        self.nahdi_paths: dict[tuple, str] = {}     # Nahdi top category (web address part) -> node id
        self.panda_by_name: dict[str, list[str]] = defaultdict(list)
        self.owned: set[str] = set()          # nodes whose products the owner store places by itself
        self._anc: dict[str, list[str]] = {}
        nahdi_tops, panda_tops = {}, {}
        for sid, ar, en, owner, tops in trees.SECTIONS:
            self._add(sid, None, ar, en, sid)
            for t in tops:
                (nahdi_tops if owner == "nahdi" else panda_tops)[t] = sid
        self._add_panda(panda_tops)
        self._add_nahdi(nahdi_nodes or [], nahdi_tops)

    def _add(self, nid, parent, ar, en, section):
        if nid in self.nodes:
            return
        self.nodes[nid] = {"id": nid, "parent": parent, "nameAr": ar, "nameEn": en or ar, "section": section}
        if parent:
            self.children[parent].append(nid)

    def _add_panda(self, owned_tops: dict):
        """Panda tops used by a section hang under it (a section with one top gets its sub-categories
        directly); the other tops are kept aside, only so their products can be recognised."""
        for tid, ar, en in trees.PANDA_TOPS:
            section = owned_tops.get(tid)
            single = section and sum(1 for v in owned_tops.values() if v == section) == 1
            nid = section if single else f"p{tid}"
            if not single:
                self._add(nid, section, ar, en, section)  # section None: an unowned top, not in the app
            for sub, parent, sar in trees.PANDA_SUBS:
                if parent == tid:
                    self._add(f"p{sub}", nid, sar, trees.PANDA_SUBS_EN.get(sub, sar), section)
                    self.panda_by_name[key(sar)].append(f"p{sub}")
                    if section:
                        self.owned.add(f"p{sub}")
            if section:
                self.owned.add(nid)

    def _add_nahdi(self, entries: list[dict], owned_tops: dict):
        own = {tuple(e["ar"]): e["id"] for e in entries if e.get("ar")}
        en_for: dict[tuple, str] = {}
        prefixes = set()
        for e in entries:
            ar, en = e.get("ar") or [], e.get("en") or []
            for d in range(1, len(ar) + 1):
                prefixes.add(tuple(ar[:d]))
                if len(en) == len(ar):
                    en_for.setdefault(tuple(ar[:d]), en[d - 1])
        for p in sorted(prefixes, key=lambda p: (len(p), p)):
            section = owned_tops.get(p[0])
            plp = own.get(p)
            nid = f"n{plp}" if plp else "n-" + hashlib.md5("/".join(p).encode()).hexdigest()[:8]
            k = tuple(key(x) for x in p)
            if k in self.nahdi_by_path:
                continue
            parent = (section if len(p) == 1 else self.nahdi_by_path.get(k[:-1]))
            if len(p) > 1 and parent is None:
                continue
            en = en_for.get(p)
            self._add(nid, parent, p[-1].replace("-", " "), _pretty_en(en) if en else None, section)
            self.nahdi_by_path[k] = nid
            if len(p) == 1:
                self.nahdi_paths[p] = nid
            self.nahdi_by_name.setdefault(k[-1], nid)  # shallowest first, thanks to the sort
            if section:
                self.owned.add(nid)

    def add_path_sections(self, groups: list[list[dict]]):
        """Sections such as electronics use their owner store's breadcrumbs (record "path") as the tree."""
        self.path_nodes: dict[tuple, str] = {}
        owners = {store: sec for sec, store in trees.PATH_SECTIONS.items()}
        for g in groups:
            for r in g:
                sec = owners.get(r.get("store"))
                path = [x for x in (r.get("path") or []) if x][:3]
                if not sec or not path:
                    continue
                parent = sec
                for d in range(1, len(path) + 1):
                    k = (r["store"],) + tuple(key(x) for x in path[:d])
                    nid = self.path_nodes.get(k)
                    if nid is None:
                        nid = r["store"][:2] + "-" + hashlib.md5("/".join(k).encode()).hexdigest()[:8]
                        self._add(nid, parent, path[d - 1], path[d - 1], sec)
                        self.path_nodes[k] = nid
                        self.owned.add(nid)
                    parent = nid

    def ancestors(self, nid: str) -> list[str]:
        """The node, its parent, ... up to its section."""
        if nid not in self._anc:
            out, n = [], nid
            while n:
                out.append(n)
                n = self.nodes[n]["parent"]
            self._anc[nid] = out
        return self._anc[nid]

    def store_node(self, rec: dict) -> str | None:
        """The node a store's own page puts this record in (owned or not), if we know that store's tree."""
        store = rec.get("store")
        if store == "nahdi":
            path = [key(x) for x in rec.get("path") or []]
            if tuple(path) in self.nahdi_by_path:  # the page's breadcrumb, when it matches the tree exactly
                return self.nahdi_by_path[tuple(path)]
            for name in reversed(path):
                if name in self.nahdi_by_name:
                    return self.nahdi_by_name[name]
            return self.nahdi_by_name.get(key(rec.get("category", "")))
        if store in trees.PATH_SECTIONS.values():
            path = [key(x) for x in rec.get("path") or [] if x][:3]
            return getattr(self, "path_nodes", {}).get((store,) + tuple(path)) if path else None
        if store == "panda":
            ids = self.panda_by_name.get(key(rec.get("category", "")), [])
            if len(ids) > 1:  # e.g. meat: fresh or frozen
                frozen = re.search(r"frozen|مجمد", f"{rec.get('nameEn', '')} {rec.get('nameAr', '')}", re.I)
                ids = [i for i in ids if (self.nodes[i]["parent"] == "p211") == bool(frozen)] or ids
            return ids[0] if ids else None
        return None


def hints(recs: list[dict], tree: Tree) -> list[str]:
    """Sections this product can be in, from its stores' own top categories (empty: no idea)."""
    for r in recs:
        if r.get("store") in trees.STORE_HINTS:
            return trees.STORE_HINTS[r["store"]]
    for r in recs:
        store, top = r.get("store"), None
        if store == "tamimi":
            top = (r.get("category") or "").split(" / ")[0].strip()
        elif store in ("panda", "nahdi"):
            sn = tree.store_node(r)
            if sn:
                root = tree.ancestors(sn)[-1]
                top = root[1:] if store == "panda" else next(
                    (p[0] for p, nid in tree.nahdi_paths.items() if nid == root), None)
        h = trees.SECTION_HINTS.get((store, top))
        if h:
            return h
    return []


def features(recs: list[dict], tree: Tree) -> set[str]:
    out = set()
    for r in recs:
        for w in words(f"{r.get('nameAr', '')} {r.get('nameEn', '')}"):
            out.add(w)
        b = key(r.get("brand", ""))
        if b:
            out.add("b:" + b)
        c = key(r.get("category", ""))
        if c:
            out.add(f"c:{r.get('store')}:{c}")
        sn = tree.store_node(r)
        if sn:
            out.add("n:" + sn)
    return out


def assign(groups: list[list[dict]], nahdi_nodes: list[dict] | None) -> tuple[list[str], list[dict]]:
    """A tree node for each group of records (one group = one product), and the tree to publish."""
    tree = Tree(nahdi_nodes)
    tree.add_path_sections(groups)
    result: list[str | None] = []
    feats: list[set[str]] = []
    allowed: list[list[str]] = []
    for g in groups:
        allowed.append(hints(g, tree))
        owned = [n for n in (tree.store_node(r) for r in g) if n and n in tree.owned]
        # Deepest owned node wins (e.g. Nahdi's breadcrumb over a bare top-level name).
        result.append(max(owned, key=lambda n: len(tree.ancestors(n))) if owned else None)
        feats.append(features(g, tree))

    # Learn: how often each feature appears with each placed node.
    counts: dict[str, Counter] = defaultdict(Counter)
    for f, nid in zip(feats, result):
        if nid:
            for t in f:
                counts[t][nid] += 1
    placed = sum(1 for n in result if n)
    weight = {t: math.log(1 + placed / sum(c.values())) for t, c in counts.items()}
    top = {t: c.most_common(40) for t, c in counts.items()}
    totals = {t: sum(c.values()) for t, c in counts.items()}

    for i, nid in enumerate(result):
        if nid:
            continue
        score: Counter = Counter()
        for t in feats[i]:
            if t not in top:
                continue
            w = weight[t] / totals[t]
            for n, c in top[t]:
                for a in tree.ancestors(n):
                    score[a] += w * c
        result[i] = _descend(tree, score, allowed[i])

    # Publish only nodes that hold products (themselves or below), sections always.
    used: Counter = Counter()
    for nid in result:
        for a in tree.ancestors(nid):
            used[a] += 1
    order = {s[0]: i for i, s in enumerate(trees.SECTIONS)}
    nodes = []
    for nid, n in tree.nodes.items():
        if n["section"] is None or (n["parent"] is not None and not used[nid]):
            continue
        nodes.append({"id": nid, "parent": n["parent"], "nameAr": n["nameAr"], "nameEn": n["nameEn"], "count": used[nid]})
    nodes.sort(key=lambda n: (order.get(n["id"], 99) if n["parent"] is None else 99, -n["count"]))
    return result, nodes


def _descend(tree: Tree, score: Counter, allowed: list[str]) -> str:
    """Pick a section (within what the store's own category allows), then step into the best child
    while it clearly leads (>= 60% of its parent's score)."""
    sections = allowed or [s[0] for s in trees.SECTIONS if s[0] != "other"]
    total = sum(score[s] for s in sections)
    best = max(sections, key=lambda s: score[s])
    firm = bool(allowed)  # the store's own category settles the section
    if total <= 0:
        return sections[0] if firm else "other"
    if score[best] < 0.5 * total and not firm:
        return "other"
    node = best
    while True:
        kids = [k for k in tree.children.get(node, []) if score[k] > 0]
        if not kids:
            return node
        k = max(kids, key=lambda k: score[k])
        if score[k] < 0.6 * score[node]:
            return node
        node = k
