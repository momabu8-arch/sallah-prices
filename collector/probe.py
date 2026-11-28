"""Check whether candidate stores can be read by the collector (run on GitHub Actions, not locally).

For each site: robots.txt, sitemaps, a couple of product pages, and whether those pages carry a
schema.org Product price. Prints a short report. Only public pages; same bot name as the collector.

  python collector/probe.py host1 host2 ...   (default: the list below)
"""
from __future__ import annotations

import re
import sys
import urllib.error
import urllib.request
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import USER_AGENT, Robots  # noqa: E402
from stores import locs, ld_products, num  # noqa: E402

CANDIDATES = [
    "https://www.mumzworld.com/media/sitemaps/sa-ar/sitemap_index.xml",
    "https://www.ikea.com/sitemaps/prod-ar-SA_1.xml", "https://www.ikea.com/sa/ar/",
    "https://gcc.luluhypermarket.com/ar-sa/sitemap.xml", "https://www.extra.com/ar-sa/sitemap.xml",
    "https://www.faces.sa/ar/sitemap_index.xml", "https://niceonesa.com/sitemap.xml",
    "bindawood.com", "www.hungerstation.com", "keeta.com", "www.keeta.com", "www.danubehome.com", "www.abyat.com",
    "www.alsaifgallery.com", "www.almanea.sa", "www.blackbox.com.sa", "www.virginmegastore.sa", "www.xcite.com.sa",
    "www.homebox.sa", "www.sharafdg.sa", "www.tryano.com", "www.ounass.com", "www.levelshoes.com",
    "www.6thstreet.com", "www.max.com", "www.styli.com", "www.bath-body.sa", "www.vavavoom.sa", "www.wardah.sa",
    "www.saharaa.com", "www.dukan.sa", "www.zid.sa", "www.salla.sa", "www.nahdi.sa", "www.aldawaa.sa",
    "www.kunooz.com.sa", "www.orange-pharmacy.com", "www.boots.sa", "www.toysrus.sa", "www.panda.sa",
    "www.tamimimarkets.com", "www.othaim.com", "www.farm.sa", "www.farmgo.sa", "www.alraya.sa", "www.alrayasupermarket.com",
]
OLD = [
    "www.danube.sa", "www.bindawood.com", "www.farm.com.sa", "www.farmsuperstores.com", "www.manuelmarket.com",
    "www.nestohypermarket.com", "www.alsadhan.com", "www.othaimmarkets.com", "gcc.luluhypermarket.com",
    "www.carrefourksa.com", "www.al-dawaa.com", "lemon.sa", "unitedpharmacy.sa",
    "niceonesa.com", "www.goldenscent.com", "www.mumzworld.com", "www.faces.sa", "www.sephora.me",
    "www.boots.com.sa", "www.orangepharmacy.com.sa", "www.kunoozpharmacy.com", "www.ghayapharmacy.com",
    "www.nana.sa", "store.nana.sa", "ananinja.com", "www.noon.com", "www.amazon.sa",
    "www.extra.com", "www.jarir.com", "www.saco.sa", "www.ikea.com", "www.centrepointstores.com",
    "www.homecentre.com", "www.hyperpanda.com", "www.zahrah.sa", "www.sary.com", "www.ozonemarkets.com",
    "www.alrayamarkets.com", "www.spar.sa", "www.aljazeerah.sa", "www.toysrus.com.sa", "www.babyshop.com",
    "www.firstcry.sa", "www.vitaminshoppe.com.sa", "www.iherb.com", "www.namshi.com",
]


def get(url: str, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8",
                                               "Accept-Language": "ar,en;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(6_000_000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return type(e).__name__, ""


PRODUCTISH = re.compile(r"product|/p/|/pdp/|/products?/|-p-|/dp/", re.I)


def probe(host: str) -> None:
    start = None
    if host.startswith("http"):
        start, host = host, host.split("/")[2]
    base = "https://" + host
    out = [f"== {host}"]
    st, robots_txt = get(base + "/robots.txt")
    out.append(f"  robots: {st}")
    if st in (401, 403):
        print("\n".join(out + ["  -> REFUSED (bot shield on robots.txt)"]), flush=True)
        return
    rob = Robots(robots_txt)
    maps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_txt) or [base + "/sitemap.xml", base + "/sitemap_index.xml"]
    if start:
        maps = [start]
    out.append(f"  sitemaps in robots: {maps[:6]}")
    product_urls: list[str] = []
    seen = 0
    for m in maps[:4]:
        s, xml = get(m)
        kids = locs(xml)
        out.append(f"  {m} -> {s}, {len(kids)} locs")
        if not kids:
            continue
        subs = [k for k in kids if k.endswith(".xml") or "sitemap" in k.lower()]
        if subs:
            pick = [k for k in subs if "product" in k.lower()] or subs
            out.append(f"    sub-sitemaps: {len(subs)} e.g. {pick[:3]}")
            for sub in pick[:2]:
                s2, x2 = get(sub)
                l2 = locs(x2)
                seen += len(l2)
                out.append(f"    {sub} -> {s2}, {len(l2)} locs e.g. {l2[:2]}")
                product_urls += [u for u in l2 if PRODUCTISH.search(u)] or l2[-5:]
        else:
            seen += len(kids)
            product_urls += [u for u in kids if PRODUCTISH.search(u)]
        if len(product_urls) >= 5:
            break
    for u in (product_urls[:1] + product_urls[len(product_urls)//2:][:1]):
        ok = rob.allowed(u)
        s, html = get(u) if ok else ("robots-disallow", "")
        prods = ld_products(html)
        info = ""
        if prods:
            p = prods[0]
            off = p.get("offers") or {}
            off = off[0] if isinstance(off, list) and off else off
            info = f"LD name={str(p.get('name'))[:60]!r} price={num((off or {}).get('price') or (off or {}).get('lowPrice'))} {(off or {}).get('priceCurrency')} gtin={p.get('gtin13') or p.get('gtin')}"
        else:
            info = f"no LD Product; len={len(html)} next_data={'__NEXT_DATA__' in html} rsc={'__next_f' in html} 'price' x{html.count('price')}"
        out.append(f"  page {u[:110]} -> {s}; {info}")
    if not product_urls:
        out.append("  no product URLs found")
    print("\n".join(out), flush=True)


def dump(url: str) -> None:
    """Print a page's JSON-LD and breadcrumb, or a sitemap's first entries."""
    if url.startswith("FIRST:"):
        ls = [u for u in locs(get(url[6:])[1]) if "/product" in u or "/p/" in u] or locs(get(url[6:])[1])[5:]
        if not ls:
            print(f"## FIRST {url}: nothing"); return
        url = ls[len(ls) // 2]
    st, body = get(url)
    if url.endswith(".txt"):
        print(f"## DUMP {url} -> {st}\n{body[:3000]}"); return
    if "<urlset" not in body and "<sitemapindex" not in body:
        m = re.search(r'__NEXT_DATA__[^>]*>(.{0,4000})', body, re.S)
        print("  NEXT_DATA:", m.group(1) if m else None)
    print(f"## DUMP {url} -> {st} len={len(body)}")
    if "<urlset" in body or "<sitemapindex" in body:
        ls = locs(body)
        print(f"  {len(ls)} locs")
        for u in ls[:60]:
            print("   ", u[:160])
        return
    from stores import LD_JSON
    for b in LD_JSON.findall(body):
        print("  LD:", b.strip()[:3000])
    for k in ("og:title", "og:image", "product:price:amount", "product:brand"):
        m = re.search(r'<meta[^>]+(?:property|name)="' + re.escape(k) + r'"[^>]+content="([^"]*)"', body)
        print(f"  meta {k}: {m.group(1)[:200] if m else None}")


DUMPS = [
    "https://hungerstation.com/robots.txt",
    "https://hungerstation.com/sitemaps/sa-ar/supermarkets/chains/danube-80083.xml",
    "https://hungerstation.com/sitemaps/sa-ar/supermarkets/chains/alraya-98596.xml",
    "https://hungerstation.com/sitemaps/sa-ar/supermarkets/chains/farm-market-30616.xml",
    "https://hungerstation.com/sitemaps/sa-ar/supermarkets/chains/al-othaim-65969.xml",
    "https://hungerstation.com/sitemaps/sa-ar/modules/supermarkets.xml",
    "https://hungerstation.com/sitemaps/sa-ar/modules/pharmacies.xml",
    "FIRST:https://hungerstation.com/sitemaps/sa-ar/supermarkets/chains/danube-80083.xml",
    "FIRST:https://hungerstation.com/sitemaps/sa-ar/hmarket/products.xml",
    "https://www.saco.sa/robots.txt",
]


if __name__ == "__main__":
    if os.environ.get("PROBE_DUMP"):
        for u in DUMPS:
            try:
                dump(u)
            except Exception as e:
                print(f"## DUMP {u} error {e}")
        sys.exit(0)
    for h in sys.argv[1:] or CANDIDATES:
        try:
            probe(h)
        except Exception as e:
            print(f"== {h}\n  error {e}", flush=True)
