"""Sallah price collector.

Reads public product pages of Saudi stores and writes the price file the app reads
(see docs/feed-format.md).

Rules this collector follows:
- Only public product pages listed in each store's own sitemap. No logins, no private APIs.
- Each store's robots.txt is checked before every page.
- One request at a time per store, with a pause between requests.
- No attempt to get around blocking: if a store refuses us, we skip it and say so.

Each run continues where the last one stopped (state is kept per store), so coverage grows
run after run and older prices get refreshed.

Usage:
  python collector/collect.py --state data/state --out data/catalog.json --minutes 40
  python collector/collect.py --smoke   # a few products per store, prints what it found
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matching  # noqa: E402
import stores  # noqa: E402

USER_AGENT = "SallahPriceBot/0.1 (price comparison app; contact via GitHub momabu8-arch)"


class Robots:
    """robots.txt rules with the wildcards real sites use ('*' and '$'); longest matching rule wins."""

    def __init__(self, text: str):
        self.rules: list[tuple[str, bool]] = []
        groups, agents, rules, last_was_agent = [], [], [], False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = (x.strip() for x in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if not last_was_agent and agents:
                    groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(val.lower())
                last_was_agent = True
            elif key in ("allow", "disallow"):
                last_was_agent = False
                if agents and val:
                    rules.append((val, key == "allow"))
        if agents:
            groups.append((agents, rules))
        mine = [r for a, r in groups if any(x != "*" and x in USER_AGENT.lower() for x in a)]
        anyone = [r for a, r in groups if "*" in a]
        for r in (mine or anyone):
            self.rules.extend(r)

    @staticmethod
    def _matches(pattern: str, path: str) -> bool:
        rx = "".join(".*" if c == "*" else re.escape(c) for c in pattern.rstrip("$"))
        rx = "^" + rx + ("$" if pattern.endswith("$") else "")
        return re.match(rx, path) is not None

    def allowed(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(parts.path or "/") + (("?" + urllib.parse.unquote(parts.query)) if parts.query else "")
        best, verdict = -1, True
        for pattern, allow in self.rules:
            if self._matches(urllib.parse.unquote(pattern), path):
                n = len(pattern)
                if n > best or (n == best and allow):
                    best, verdict = n, allow
        return verdict


class Fetcher:
    """Polite HTTP client for one store: robots.txt aware, one request at a time, fixed pause."""

    def __init__(self, base: str, delay: float):
        self.base = base
        self.delay = delay
        self.last = 0.0
        self.blocked = 0
        self.refused = False
        text = ""
        try:
            req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            # 401/403 on robots.txt usually means a bot shield refused us. We respect it and skip the store.
            if e.code in (401, 403):
                self.refused = True
                print(f"[{base}] robots.txt refused us ({e.code}): skipping this store", file=sys.stderr)
        except Exception as e:
            print(f"[{base}] robots.txt unreadable: {e}", file=sys.stderr)
        self.robots = Robots(text)

    def allowed(self, url: str) -> bool:
        return not self.refused and self.robots.allowed(url)

    def get(self, url: str, timeout: int = 60) -> str | None:
        if not self.allowed(url):
            return None
        wait = self.delay - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ar,en;q=0.8",
        })
        for attempt in range(3):
            self.last = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                if e.code in (403, 429, 503):
                    self.blocked += 1
                    time.sleep(5 * (attempt + 1))
                    continue
                if e.code == 404:
                    return None
                time.sleep(2)
            except Exception:
                time.sleep(2)
        return None


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path: str, data, compact: bool = False):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def save_catalog(path: str, catalog: dict):
    """Valid JSON, but with one product per line, so the app can read it product by product
    instead of holding the whole (tens of MB) file in memory at once."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    head = {k: v for k, v in catalog.items() if k != "products"}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(head, ensure_ascii=False, separators=(",", ":"))[:-1] + ',"products":[\n')
        for i, p in enumerate(catalog["products"]):
            if i:
                f.write(",\n")
            f.write(json.dumps(p, ensure_ascii=False, separators=(",", ":")))
        f.write("\n]}\n")
    os.replace(tmp, path)


HIST_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
HIST_DAYS = 180   # how far back the app's price chart goes
HIST_POINTS = 40  # at most this many price changes per product per store


def hist_day(iso: str | None) -> int | None:
    """Day number (days since 2026-01-01) of an ISO time, as the price history stores it."""
    try:
        t = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (t - HIST_EPOCH).days


def price_history(old: dict | None, new: dict) -> list:
    """Price changes of one store's product as [[day, price], ...], oldest first.
    A point is added only when the price changes, so a steady price costs one point."""
    hist = [list(h) for h in (old or {}).get("hist") or [] if isinstance(h, list) and len(h) == 2]
    if not hist and old and old.get("price"):
        d = hist_day(old.get("fetchedAt"))
        if d is not None:
            hist = [[d, round(old["price"], 2)]]
    day = hist_day(new.get("fetchedAt"))
    price = round(new.get("price") or 0, 2)
    if day is None or price <= 0:
        return hist
    if not hist or abs(hist[-1][1] - price) >= 0.01:
        if hist and hist[-1][0] == day:
            hist[-1] = [day, price]  # read twice the same day: keep the latest price
        else:
            hist.append([day, price])
    # Keep the last 180 days, plus the price in force when that window starts.
    recent = [h for h in hist if h[0] >= day - HIST_DAYS]
    older = [h for h in hist if h[0] < day - HIST_DAYS]
    if older:
        recent.insert(0, [day - HIST_DAYS, older[-1][1]])
    return recent[-HIST_POINTS:]


def crawl_store(store: stores.Store, state_dir: str | None, deadline: float, limit: int | None) -> dict:
    """Fetches product pages for one store until the deadline. Returns a report."""
    fetcher = Fetcher(store.base, store.delay)
    state_path = os.path.join(state_dir, f"{store.id}.json") if state_dir else None
    state = load_json(state_path, {}) if state_path else {}
    records: dict = state.get("products", {})
    cursor = int(state.get("cursor", 0))

    urls = store.product_urls(fetcher)
    report = {"store": store.id, "sitemapUrls": len(urls), "fetched": 0, "parsed": 0, "failed": 0, "blocked": 0}
    if not urls:
        report["note"] = "refused by the site's bot protection" if fetcher.refused else "no product URLs (sitemap unreachable)"
        report["blocked"] = fetcher.blocked
        return report

    # Products never read before go first (a big store takes weeks to read in full, and a missing
    # product hides its price completely), then the oldest prices are refreshed in turn.
    seen = {r.get("url") for r in records.values()} | set(state.get("skipped", []))
    new = [u for u in urls if u not in seen] if limit is None else []
    skipped = set(state.get("skipped", []))
    i = n = 0
    while time.monotonic() < deadline and (limit is None or i < limit) and i < len(urls) + len(new):
        if n < len(new):
            url, n = new[n], n + 1
        else:
            url = urls[(cursor + i - n) % len(urls)]
        i += 1
        html = fetcher.get(url)
        report["fetched"] += 1
        if html is None:
            report["failed"] += 1
            if fetcher.blocked >= 20:
                report["note"] = "store kept refusing requests; stopped"
                break
            continue
        try:
            rec = store.parse(url, html)
        except Exception as e:  # one odd page must not stop the run
            rec = None
            print(f"[{store.id}] parse error {url}: {e}", file=sys.stderr)
        if not rec:
            report["failed"] += 1
            skipped.add(url)  # not a product page we can read; don't put it first again
            continue
        # A listing page (e.g. a HungerStation pharmacy category) gives many products at once.
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for r in (rec if isinstance(rec, list) else [rec]):
            r["fetchedAt"] = now
            r["hist"] = price_history(records.get(r["sid"]), r)
            records[r["sid"]] = r
        report["parsed"] += 1

    report["blocked"] = fetcher.blocked
    report["known"] = len(records)
    report["newFirst"] = n
    if state_path:
        save_json(state_path, {"cursor": (cursor + i - n) % len(urls), "products": records,
                               "skipped": sorted(skipped & set(urls))}, compact=True)
    report["records"] = records
    return report


def newest(records) -> list[dict]:
    """One record per listing: two crawls can read the same product (a HungerStation chain's product
    page and its category page); the newest price wins."""
    out: dict = {}
    for r in records:
        old = out.get(r["sid"])
        if old is None or (r.get("fetchedAt") or "") >= (old.get("fetchedAt") or ""):
            out[r["sid"]] = r
    return list(out.values())


def nahdi_tree(state_dir: str | None, fetch: bool) -> list[dict]:
    """Nahdi's category tree: read fresh from its sitemap when we can, else the copy from the last run."""
    path = os.path.join(state_dir, "trees", "nahdi.json") if state_dir else None
    tree = []
    if fetch:
        try:
            nahdi = next(s for s in stores.ALL if s.id == "nahdi")
            tree = stores.nahdi_tree(Fetcher(nahdi.base, nahdi.delay))
        except Exception as e:  # the tree is a nice-to-have; prices matter more
            print(f"[nahdi] category tree not read: {e}", file=sys.stderr)
        print(f"[nahdi] category tree: {len(tree)} categories")
    if tree and path:
        save_json(path, tree, compact=True)
    return tree or (load_json(path, []) if path else [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="data/state")
    ap.add_argument("--out", default="data/catalog.json")
    ap.add_argument("--minutes", type=float, default=40)
    ap.add_argument("--stores", default=",".join(s.id for s in stores.ALL if s.product_urls))
    ap.add_argument("--smoke", action="store_true", help="fetch 3 products per store and print them")
    ap.add_argument("--rebuild", action="store_true", help="no fetching: rebuild the price file from saved state")
    args = ap.parse_args()

    if args.rebuild:
        recs = []
        for s in stores.ALL:
            recs.extend(load_json(os.path.join(args.state, f"{s.id}.json"), {}).get("products", {}).values())
        catalog = matching.build_catalog(newest(recs), stores.ALL, nahdi_tree=nahdi_tree(args.state, fetch=False))
        save_catalog(args.out, catalog)
        multi = sum(1 for p in catalog["products"] if len(p["offers"]) > 1)
        print(f"rebuilt {args.out}: {len(catalog['products'])} products, {multi} in 2+ stores")
        return

    chosen = [s for s in stores.ALL if s.id in args.stores.split(",") and s.product_urls]
    deadline = time.monotonic() + args.minutes * 60
    limit = 3 if args.smoke else None
    state_dir = None if args.smoke else args.state

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(chosen) + 1) as pool:
        tree_job = pool.submit(nahdi_tree, state_dir, "nahdi" in args.stores.split(","))
        reports = list(pool.map(lambda s: crawl_store(s, state_dir, deadline, limit), chosen))
        tree = tree_job.result()

    all_records = []
    for r in reports:
        all_records.extend(r.pop("records", {}).values())
        print(json.dumps(r, ensure_ascii=False))

    if args.smoke:
        for rec in all_records:
            print(json.dumps(rec, ensure_ascii=False))
        catalog = matching.build_catalog(all_records, stores.ALL, nahdi_tree=tree)
        print(f"smoke catalog: {len(tree)} Nahdi categories, nodes: {[p['node'] for p in catalog['products']]}")
        print(f"smoke catalog: {len(catalog['products'])} products")
        return

    catalog = matching.build_catalog(newest(all_records), stores.ALL, nahdi_tree=tree)
    save_catalog(args.out, catalog)
    save_json(os.path.join(os.path.dirname(args.out) or ".", "report.json"), {
        "generatedAt": catalog["generatedAt"],
        "products": len(catalog["products"]),
        "matchedInTwoOrMoreStores": sum(1 for p in catalog["products"] if len(p["offers"]) > 1),
        "stores": reports,
    })
    print(f"wrote {args.out}: {len(catalog['products'])} products")


if __name__ == "__main__":
    main()
