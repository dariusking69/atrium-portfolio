#!/usr/bin/env python3
"""
ATRIUM PORTFOLIO  -  build the whole-portfolio map + SEO property pages.

The problem this solves
-----------------------
atriummanagement.com used to keep a live page for every listing Atrium ever
had, including long-leased ones. Great for search, terrible for prospects, who
kept applying to homes rented years ago. meetatrium.com dropped the practice and
lost the search footprint with it.

This rebuilds the footprint honestly: a page per property we ACTUALLY manage,
showing that property's most recent advertised listing. If the unit isn't
available, the page says LEASED in the hero, drops the apply button entirely,
declares itself SoldOut in structured data, and shows what IS available nearby.
Search engines get a real page; prospects get pointed at real inventory.

Data sources (AppFolio Data API v0 - the only place the archive exists):
    properties  - what we manage right now, incl. ManagementEndDate for churn
    units       - unit counts for community pages
    listings    - 6,262 listings back to 2016, with photos and marketing copy.
                  The public /listings feed only carries today's ~517.

Pipeline:
    fetch -> filter to managed -> join listings to properties -> sanitize copy
    (see compliance.py) -> geocode -> render pages + portfolio.json + sitemap

Usage:
    python3 build.py                 # incremental, uses cached API pulls
    python3 build.py --refresh       # re-pull everything from AppFolio
    python3 build.py --offline       # rebuild pages from cache, no network
    python3 build.py --limit 50      # render a small slice while iterating
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import requests

from compliance import ReviewLog, sanitize
from geocode import geocode_all, key as geo_key

HERE = Path(__file__).parent
CACHE = HERE / "cache"
SITE = HERE / "site"

# ---------------------------------------------------------------- config ----
# BASE_URL decides what goes in <link rel=canonical>, og:url and sitemap.xml.
# Subdomain today; flip to https://meetatrium.com once the Cloudflare Worker in
# worker.js is live and the pages sit under the main domain. Nothing else in the
# build needs to change - internal links are all root-relative.
BASE_URL = os.environ.get("PORTFOLIO_BASE_URL", "https://portfolio.meetatrium.com").rstrip("/")
BRAND = "Atrium Management"
PHONE_DISPLAY = "(407) 585-2721"
APPFOLIO_DB = "atriummanagement"

RED, INK, LINE = "#f13d3d", "#070707", "#e6e6e6"

# Internal-review build. Shareable by link, invisible to search engines - so the
# team can read the real pages before the Fair Housing queue is signed off and
# before the subdomain-vs-meetatrium.com decision is made. Letting Google index
# 1,240 pages on a throwaway host now would mean cleaning up duplicates and
# redirects later.
PREVIEW = False


def env():
    """Read AppFolio creds from the existing project .env files."""
    out = {}
    for p in (Path.home() / "Downloads/Work/atrium_chatbot/.env",
              Path.home() / "Downloads/Work/atrium_intranet/.env",
              HERE / ".env"):
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    for k in ("DATABASE_CLIENT_ID", "DATABASE_CLIENT_SECRET", "DEVELOPER_ID"):
        if os.environ.get(k):
            out[k] = os.environ[k]
    return out


# ------------------------------------------------------------ API fetch ----
def fetch_entity(name, creds, since="2010-01-01T00:00:00Z"):
    """
    Walk every page of a Data API v0 entity.

    Two gotchas baked in: a list GET 400s without a filter, and the
    X-AppFolio-Developer-ID header is case-sensitive at the gateway (urllib
    lowercases custom headers and gets 'Required header missing' - requests
    preserves case, which is why this uses requests).
    """
    auth = (creds["DATABASE_CLIENT_ID"], creds["DATABASE_CLIENT_SECRET"])
    hdr = {"X-AppFolio-Developer-ID": creds["DEVELOPER_ID"]}
    path = (f"/api/v0/{name}.json?database={APPFOLIO_DB}"
            f"&filters%5BLastUpdatedAtFrom%5D={since}")
    rows, page = [], 0
    while path:
        r = requests.get("https://api.appfolio.com" + path, auth=auth, headers=hdr, timeout=120)
        if r.status_code != 200:
            raise SystemExit(f"AppFolio {name} HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        rows += body.get("data", [])
        path = body.get("next_page_path")
        page += 1
        if page % 20 == 0:
            print(f"    {name}: {len(rows)} rows...", flush=True)
    print(f"  {name}: {len(rows)} rows ({page} pages)")
    return rows


def live_feed_coords():
    """
    Harvest lat/lng from AppFolio's public listings page - free exact coords for
    every currently-advertised address. Paginates: the feed caps at 300/page and
    ignores per_page, so page 1 alone silently drops most of the portfolio.
    """
    out, page = {}, 1
    while page <= 20:
        url = f"https://{APPFOLIO_DB}.appfolio.com/listings" + (f"?page={page}" if page > 1 else "")
        try:
            txt = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60).text
        except Exception as e:
            print(f"  live feed page {page} failed: {e}")
            break
        s = txt.find("markers: [")
        if s < 0:
            break
        i, depth = txt.find("[", s), 0
        markers = []
        for j in range(i, len(txt)):
            if txt[j] == "[":
                depth += 1
            elif txt[j] == "]":
                depth -= 1
                if depth == 0:
                    markers = json.loads(txt[i:j + 1])
                    break
        if not markers:
            break
        for m in markers:
            if m.get("latitude") and m.get("longitude"):
                addr = (m.get("address") or "").split(",")
                if len(addr) >= 3:
                    street = addr[0].strip()
                    city = addr[-2].strip()
                    sz = addr[-1].strip().split()
                    st, zc = (sz[0], sz[1] if len(sz) > 1 else "") if sz else ("", "")
                    out[geo_key(street, city, st, zc)] = (
                        round(float(m["latitude"]), 6), round(float(m["longitude"]), 6))
        page += 1
    print(f"  live feed: {len(out)} exact coords")
    return out


def load_or_fetch(refresh, offline):
    data = {}
    for name in ("properties", "units", "listings", "property_groups"):
        f = CACHE / f"{name}.json"
        if f.exists() and (offline or not refresh):
            data[name] = json.loads(f.read_text())
            print(f"  {name}: {len(data[name])} rows (cached)")
        elif offline:
            raise SystemExit(f"--offline but {f} is missing; run without --offline first")
        else:
            data[name] = fetch_entity(name, env())
            CACHE.mkdir(exist_ok=True)
            f.write_text(json.dumps(data[name]))
    # the archive pull is named all_listings.json in the scratch analysis
    if not (CACHE / "listings.json").exists() and (CACHE / "all_listings.json").exists():
        data["listings"] = json.loads((CACHE / "all_listings.json").read_text())
    return data


# --------------------------------------------------------------- helpers ----
def norm_addr(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def slugify(*parts):
    s = " ".join(str(p) for p in parts if p)
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)[:90]


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def money(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f <= 0 else f"${f:,.0f}"


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def beds_label(b):
    if b is None:
        return None
    b = int(b)
    return "Studio" if b == 0 else f"{b} Bed" + ("s" if b > 1 else "")


def baths_label(b):
    f = num(b)
    if f is None:
        return None
    t = f"{f:g}"
    return f"{t} Bath" + ("s" if f != 1 else "")


# --------------------------------------------------------------- shaping ----
def build_model(data):
    """Join the archive onto currently-managed properties and shape it for render."""
    props = data["properties"]
    by_id = {p["Id"]: p for p in props}
    by_addr = defaultdict(list)
    for p in props:
        by_addr[(norm_addr(p.get("Address1")), (p.get("Zip") or "")[:5])].append(p)

    managed = {p["Id"] for p in props if not p.get("HiddenAt") and not p.get("ManagementEndDate")}
    print(f"  {len(managed)} actively managed of {len(props)} properties")

    unit_count = defaultdict(int)
    for u in data["units"]:
        if u.get("PropertyId"):
            unit_count[u["PropertyId"]] += 1

    # attach every archived listing to a property
    per_prop = defaultdict(list)
    orphan = 0
    for l in data["listings"]:
        pid = l.get("PropertyId")
        if pid not in by_id:
            cand = by_addr.get((norm_addr(l.get("Address1")), (l.get("Zip") or "")[:5]))
            pid = cand[0]["Id"] if cand else None
        if pid is None:
            orphan += 1
            continue
        if pid not in managed:
            continue                      # ex-client: never publish their address
        per_prop[pid].append(l)
    print(f"  {len(per_prop)} managed properties have archived listings "
          f"({orphan} listings belong to properties we no longer manage - excluded)")
    return by_id, managed, unit_count, per_prop


def listing_sort_key(l):
    return l.get("LastUpdatedAt") or ""


def shape_listing(l, review, address_label, city):
    """Sanitize + normalize one archived listing into render-ready fields."""
    title_raw = (l.get("MarketingTitle") or "").strip()
    desc_raw = (l.get("MarketingDescription") or "").strip()

    title, tf = sanitize(title_raw)
    desc, df = sanitize(desc_raw)
    review.add(l.get("Id", ""), address_label, city, tf + df)

    photos = []
    for p in (l.get("UnitPhotos") or []):
        u = p.get("Url") or p.get("ThumbnailUrl")
        if u:
            photos.append({"url": u, "thumb": p.get("ThumbnailUrl") or u})
    # Lead with a real photograph. PNG is only 5.5% of all uploaded images but
    # 15% of FIRST images, because floor-plan diagrams and site maps get uploaded
    # ahead of the photos - and Coliseum Lofts led with a line drawing. Sort is
    # stable, so within each group the original order is preserved and every
    # image still appears in the gallery.
    photos.sort(key=lambda p: p["url"].lower().rsplit(".", 1)[-1] in ("png", "gif"))

    rent = num(l.get("AdvertisedRent")) or num(l.get("ListedRent"))
    lo, hi = num(l.get("LowAdvertisedRent")), num(l.get("HighAdvertisedRent"))
    return {
        "id": l.get("Id"),
        "available": bool(l.get("PostedToWebsite")) and bool(l.get("AcceptingApplications")),
        "title": title or None,
        "desc": desc or None,
        "beds": l.get("Bedrooms"),
        "baths": num(l.get("Bathrooms")),
        "sqft": int(num(l.get("SquareFeet")) or 0) or None,
        "rent": rent,
        "rent_low": lo, "rent_high": hi,
        "deposit": num(l.get("Deposit")),
        "amenities": [a for a in (l.get("UnitAmenities") or []) if a],
        "utilities": l.get("UtilitiesIncluded") or None,
        "dogs": l.get("DogPolicy"), "cats": l.get("CatsAllowed"),
        "unit": (l.get("Address2") or "").strip() or None,
        "unit_type_id": l.get("UnitTypeId"),
        "photos": photos,
        "youtube": l.get("YouTubeURL") or None,
        "apply_url": l.get("ApplicationURL") or None,
        "available_on": l.get("AvailableOn"),
        "last_seen": l.get("LastUpdatedAt"),
    }


def pooled_photos(plan_recs, limit=24):
    """Every distinct photo across a community's floor plans, photographs first."""
    seen, out = set(), []
    for s in plan_recs:
        for ph in s.get("photos") or []:
            if ph["url"] not in seen:
                seen.add(ph["url"])
                out.append(ph)
    out.sort(key=lambda p: p["url"].lower().rsplit(".", 1)[-1] in ("png", "gif"))
    return out[:limit]


def unique_slug(base, taken, stable_id=""):
    """
    Guarantee a unique slug without breaking URL stability between builds.

    Distinct AppFolio properties genuinely share a street address - '109 James
    Avenue' exists twice as JAME109#1 and JAME109-B, and both slugged to the same
    path, so one page silently overwrote the other (270 pages lost). Disambiguate
    with a hash of the record's own id rather than a running counter: a counter
    would reshuffle every URL the moment a property is added or removed, which
    for pages whose whole purpose is search ranking is worse than the collision.
    """
    if base not in taken:
        taken.add(base)
        return base
    suffix = hashlib.sha1(str(stable_id).encode()).hexdigest()[:6] if stable_id else "2"
    slug = f"{base}-{suffix}"
    n = 2
    while slug in taken:                    # astronomically unlikely; still bounded
        slug = f"{base}-{suffix}-{n}"
        n += 1
    taken.add(slug)
    return slug


def select_pids(by_id, per_prop, limit=None):
    """
    The canonical property ordering. Geocoding and rendering MUST walk the same
    list - slicing an unsorted dict for one and a sorted one for the other means
    --limit geocodes a different 40 properties than it renders, and the pins
    silently vanish from the map.
    """
    pids = sorted(per_prop.keys(), key=lambda i: (by_id[i].get("Name") or "", i))
    return pids[:limit] if limit else pids


def assemble(by_id, managed, unit_count, per_prop, coords, review, pids):
    """Produce the page records: single-family homes, MF communities, floor plans."""
    records = []
    taken = set()          # every property-level slug issued this build

    for pid in pids:
        p = by_id[pid]
        ls = sorted(per_prop[pid], key=listing_sort_key, reverse=True)
        ptype = p.get("PropertyType") or "Single-Family"
        city = (p.get("City") or "").strip().title()
        state = (p.get("State") or "").strip().upper()
        zipc = (p.get("Zip") or "")[:5]
        street = (p.get("Address1") or "").strip()
        name = (p.get("Name") or street).strip()
        latlng = coords.get(pid)

        if ptype == "Multi-Family":
            # One community page + a page per distinct floor plan.
            #
            # Group by the LAYOUT (beds/baths/sqft), not by UnitTypeId. AppFolio
            # hands out a unit type per unit, so Coliseum Lofts alone reports 49
            # of them - 27 sharing 2bd/2ba. Publishing 27 near-identical
            # "2 Bed 2 Bath" pages for one building is the doorway-page pattern
            # this project is specifically trying not to recreate, and they all
            # collided onto one URL anyway.
            plans = defaultdict(list)
            for l in ls:
                plans[(l.get("Bedrooms"), str(l.get("Bathrooms")),
                       int(num(l.get("SquareFeet")) or 0))].append(l)
            plan_recs = []
            taken_plan_slugs = set()
            for k, group in sorted(plans.items(), key=lambda kv: str(kv[0])):
                group.sort(key=listing_sort_key, reverse=True)
                # Represent the layout with an AVAILABLE unit when one exists.
                #
                # Sorting by LastUpdatedAt and taking [0] looks reasonable and is
                # actively wrong: AppFolio touches a listing record at the moment
                # it leases, so just-leased units reliably sort to the top of
                # their group. Champions Village had 19 open units and every one
                # of its four layouts elected a leased representative, so the map
                # pin and the hero banner both said fully leased.
                #
                # The representative also supplies the rent and photos shown, so
                # preferring an open unit means the page quotes a price someone
                # can actually act on.
                rep = next((g for g in group
                            if g.get("PostedToWebsite") and g.get("AcceptingApplications")),
                           group[0])
                s = shape_listing(rep, review, name, city)
                s["available_count"] = sum(
                    1 for g in group if g.get("PostedToWebsite") and g.get("AcceptingApplications"))
                # Availability is a property of the GROUP, never of whichever
                # single listing happened to be picked to stand in for it.
                s["available"] = s["available_count"] > 0
                s["seen_count"] = len(group)
                base = slugify(name, beds_label(s["beds"]) or "unit",
                               baths_label(s["baths"]) or "",
                               f"{s['sqft']}-sqft" if s.get("sqft") else "")
                s["slug"] = unique_slug(base or "floor-plan", taken_plan_slugs, s.get("id") or "")
                plan_recs.append(s)
            plan_recs.sort(key=lambda s: (s["beds"] if s["beds"] is not None else 99, s["baths"] or 0))
            comm_slug = unique_slug(slugify(name, city), taken, pid)
            rec = {
                "kind": "community",
                "pid": pid, "name": name, "street": street, "city": city,
                "state": state, "zip": zipc, "lat": latlng[0] if latlng else None,
                "lng": latlng[1] if latlng else None,
                "units": unit_count.get(pid, 0),
                "amenities": [a for a in (p.get("Amenities") or []) if a],
                "year_built": p.get("YearBuilt"),
                "plans": plan_recs,
                # Derived from the unit count, not from any single listing record.
                "available": sum(s.get("available_count", 0) for s in plan_recs) > 0,
                "available_count": sum(s.get("available_count", 0) for s in plan_recs),
                "slug": comm_slug,
                "url": f"/communities/{comm_slug}/",
                # Pool photos across every floor plan rather than taking the
                # first plan that happens to have one. Coliseum Lofts' first plan
                # carries a single PNG floor-plan diagram, so the community led
                # with a line drawing while real photos sat on the other plans.
                "photos": pooled_photos(plan_recs),
                "rent_min": min([s["rent"] for s in plan_recs if s["rent"]], default=None),
                "rent_max": max([s["rent"] for s in plan_recs if s["rent"]], default=None),
                "desc": next((s["desc"] for s in plan_recs if s["desc"]), None),
            }
            records.append(rec)
        else:
            # Same trap as the multi-family path: a home re-listed over the years
            # has several listing records, and the newest is often the one stamped
            # when it last leased. Prefer a currently-posted record so an available
            # home is never rendered as LEASED.
            open_now = [l for l in ls
                        if l.get("PostedToWebsite") and l.get("AcceptingApplications")]
            s = shape_listing(open_now[0] if open_now else ls[0], review, street, city)
            s["available"] = bool(open_now)
            home_slug = unique_slug(slugify(street, city), taken, pid)
            s.update({
                "kind": "home",
                "pid": pid, "name": name, "street": street, "city": city,
                "state": state, "zip": zipc,
                "lat": latlng[0] if latlng else None,
                "lng": latlng[1] if latlng else None,
                "ptype": ptype,
                "amenities": sorted(set(s["amenities"]) | set(p.get("Amenities") or [])),
                "year_built": p.get("YearBuilt"),
                "history": len(ls),
                "slug": home_slug,
                "url": f"/homes/{home_slug}/",
            })
            records.append(s)
    return records


# ------------------------------------------------------------- proximity ----
def miles(a_lat, a_lng, b_lat, b_lng):
    from math import asin, cos, radians, sin, sqrt
    dlat, dlng = radians(b_lat - a_lat), radians(b_lng - a_lng)
    h = sin(dlat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(dlng / 2) ** 2
    return 3958.8 * 2 * asin(sqrt(h))


def pick_nearby(rec, records, n=4, radius=12.0):
    """
    What to show on a page. On a LEASED page this is the whole point: it turns
    dead-inventory search traffic into a live option instead of a dead end.
    Prefers genuinely available properties, nearest first; falls back to the
    same city, then anything available.
    """
    pool = [r for r in records if r["pid"] != rec["pid"] and r.get("available")]
    if rec.get("lat") and rec.get("lng"):
        near = []
        for r in pool:
            if r.get("lat") and r.get("lng"):
                d = miles(rec["lat"], rec["lng"], r["lat"], r["lng"])
                if d <= radius:
                    near.append((d, r))
        near.sort(key=lambda t: t[0])
        if len(near) >= n:
            return [r for _, r in near[:n]]
        picked = [r for _, r in near]
    else:
        picked = []
    seen = {r["pid"] for r in picked}
    for r in pool:
        if len(picked) >= n:
            break
        if r["pid"] not in seen and r["city"] == rec["city"]:
            picked.append(r)
            seen.add(r["pid"])
    for r in pool:
        if len(picked) >= n:
            break
        if r["pid"] not in seen:
            picked.append(r)
            seen.add(r["pid"])
    return picked[:n]


# ----------------------------------------------------------------- write ----
def write(path, text, written=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if written is not None:
        written.add(path.resolve())


def page_path(url):
    """'/homes/x/' -> site/homes/x/index.html (pretty URLs on any static host)."""
    return SITE / url.strip("/") / "index.html"



def sanity_check(records, feed_count=None):
    """
    Availability is the one field on these pages that must not be wrong. A leased
    banner on an open unit costs real leases; an open banner on a leased one is
    the exact problem this project was built to fix.

    This caught nothing for weeks because the bug was silent - Champions Village
    rendered as fully leased while holding 19 open units, and nothing in the build
    output looked unusual. So the invariants are asserted every run now.
    """
    problems = []

    # 1. Internal consistency. The map pin, the hero banner and the floor-plan
    #    chips all read different fields; they must never disagree.
    for r in records:
        if not r.get("available") and r.get("available_count", 0) > 0:
            problems.append(f"{r['name']}: says leased but has "
                            f"{r['available_count']} open units")
        if r.get("available") and r.get("available_count", 0) == 0 and r["kind"] == "community":
            problems.append(f"{r['name']}: says available but has 0 open units")
        for pl in r.get("plans", []):
            if bool(pl.get("available")) != (pl.get("available_count", 0) > 0):
                problems.append(f"{r['name']} / {pl.get('slug')}: plan availability "
                                f"disagrees with its unit count")

    # 2. Cross-check against AppFolio's own public listings page, which is what
    #    prospects actually see. These count slightly different things (the feed
    #    is per advertised unit, ours is per unit we can attribute to a managed
    #    property), so this warns rather than fails - but a large gap means the
    #    availability signal has drifted and someone should look.
    open_units = sum(r.get("available_count", 0) or (1 if r.get("available") else 0)
                     for r in records)
    if feed_count:
        ratio = open_units / feed_count
        flag = "" if 0.5 <= ratio <= 1.5 else "   <-- LARGE GAP, INVESTIGATE"
        print(f"  cross-check: {open_units} open units here vs {feed_count} "
              f"advertised on AppFolio's public feed ({ratio:.0%}){flag}")
    else:
        print(f"  {open_units} open units across the portfolio")

    if problems:
        print(f"  !! {len(problems)} AVAILABILITY INCONSISTENCIES:")
        for line in problems[:10]:
            print(f"       {line}")
        raise SystemExit("availability invariants failed - refusing to publish "
                         "pages that would mislabel inventory")
    print("  availability invariants: ok")


def render_all(records, review):
    import templates as T

    for r in records:
        r["city_slug"] = slugify(r["city"], r["state"])

    by_city = defaultdict(list)
    for r in records:
        by_city[(r["city"], r["state"], r["city_slug"])].append(r)

    urls = []
    written = set()          # absolute paths written this run; prune() uses it
    today = date.today().isoformat()
    n_home = n_comm = n_plan = 0

    for r in records:
        nearby = pick_nearby(r, records)
        if r["kind"] == "home":
            write(page_path(r["url"]), T.render_home(r, BASE_URL, nearby), written)
            n_home += 1
        else:
            write(page_path(r["url"]), T.render_community(r, BASE_URL, nearby), written)
            n_comm += 1
            for p in r["plans"]:
                write(page_path(r["url"] + p["slug"] + "/"), T.render_plan(r, p, BASE_URL), written)
                urls.append((f"{BASE_URL}{r['url']}{p['slug']}/", today, "0.5"))
                n_plan += 1
        urls.append((BASE_URL + r["url"], today, "0.8" if r.get("available") else "0.5"))

    n_city = 0
    for (city, state, slug), recs in sorted(by_city.items()):
        if len(recs) < 2:                 # a one-property "city hub" is thin content
            continue
        write(page_path(f"/rentals/{slug}/"), T.render_city(city, state, slug, recs, BASE_URL), written)
        urls.append((f"{BASE_URL}/rentals/{slug}/", today, "0.7"))
        n_city += 1

    # Site root: map widget + a crawlable directory (the crawl path into everything).
    widget = (HERE / "map.html").read_text()
    block = widget.split("<!-- WIDGET START -->")[1].split("<!-- WIDGET END -->")[0]
    # Root page fetches same-origin. The ABSOLUTE url is only needed by the
    # Squarespace-embedded copy in map.html, which runs on a different origin.
    block = block.replace("DATA_URL:  'portfolio.json'", "DATA_URL:  '/portfolio.json'")
    leaflet = ('<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">')
    city_counts = sorted(((k, len(v)) for k, v in by_city.items() if len(v) >= 2),
                         key=lambda t: -t[1])
    write(SITE / "index.html",
          T.render_index(records, city_counts, BASE_URL, block).replace("</head>", leaflet + "\n</head>"))
    urls.append((BASE_URL + "/", today, "1.0"))

    # sitemap
    body = "\n".join(
        f"  <url><loc>{u}</loc><lastmod>{m}</lastmod><priority>{p}</priority></url>"
        for u, m, p in sorted(set(urls)))
    write(SITE / "sitemap.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "\n</urlset>\n")
    # Brand assets: the official logo files, copied verbatim. Generated once by
    # tools/make_assets.py from Marketing/ - not redrawn here, because the brand
    # rules forbid recreating the letterforms.
    import shutil
    src = HERE / "static"
    if src.exists():
        dest = SITE / "static"
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, dest / f.name)
                written.add((dest / f.name).resolve())

    if PREVIEW:
        write(SITE / "robots.txt",
              "# INTERNAL PREVIEW - not for indexing.\n"
              "User-agent: *\nDisallow: /\n")
    else:
        write(SITE / "robots.txt",
              f"User-agent: *\nAllow: /\n\nSitemap: {BASE_URL}/sitemap.xml\n")

    print(f"  pages: {n_home} homes, {n_comm} communities, {n_plan} floor plans, "
          f"{n_city} city hubs = {n_home + n_comm + n_plan + n_city}")
    prune(written)
    return len(urls)


def prune(written):
    """
    Delete pages this build did not write.

    Properties leave the portfolio and slugs change, and site/ is not cleaned
    between runs - so without this, a page for a home we no longer manage stays
    on disk, stays served, and stays indexed. It is out of the sitemap but Google
    does not need the sitemap to keep crawling a URL it already knows.
    """
    stale = 0
    for section in ("homes", "communities", "rentals"):
        root = SITE / section
        if not root.exists():
            continue
        for f in root.rglob("index.html"):
            if f.resolve() not in written:
                f.unlink()
                stale += 1
    # tidy up the directories those pages left behind
    for section in ("homes", "communities", "rentals"):
        root = SITE / section
        if not root.exists():
            continue
        for d in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    if stale:
        print(f"  pruned {stale} stale pages (renamed or no longer managed)")


# Display names for the portfolio filter, copied VERBATIM from the Intranet's
# records.py PG_NAMES so agents see the same labels in both places. No PG6 in
# the filter - it deliberately does not exist on the dashboard (leave it out;
# do not "fix" this). AppFolio does hold a stale 3-property "PG6" group, plus a
# "PG1 ... Including Associations" variant and empty merge artifacts - all
# excluded by _pg_groups().
PG_LABELS = {
    "PG1": "PG1 · Orlando Boutique", "PG2": "PG2 · Lake Mary",
    "PG3": "PG3 · Orlando SFH", "PG4": "PG4 · Gainesville",
    "PG5": "PG5 · Tampa",
    "PG7": "PG7 · ATW Orlando Boutique",
    "PG8": "PG8 · Melbourne", "PG9": "PG9 · Lakeland",
    "PG10": "PG10 · Richmond",
}


def build_portfolio_codes(data):
    """
    property uuid -> ["PG1", "mf-aaron-webb", ...] plus the dropdown catalogue.

    Two families, mirroring the Intranet dashboard:
      - PG1..PG10 (no PG6): the SF property groups, from v0 groups named
        "PGn - Team ..." or bare "PGn".
      - Regional-manager portfolios: v0 groups named "MF Region_<Manager>" -
        the same groups the Intranet's MF Region view keys off, so membership
        stays AppFolio-managed and never hardcoded here.
    """
    groups = data.get("property_groups") or []
    by_prop = defaultdict(list)
    catalogue = []

    for code in PG_LABELS:                                   # dict order = PG1..PG10
        n = code[2:]
        cands = [g for g in groups
                 if (g.get("Name") or "").strip() in (f"PG{n}",)
                 or (g.get("Name") or "").startswith(f"PG{n} - ")]
        cands = [g for g in cands
                 if "including" not in g["Name"].lower() and "merge" not in g["Name"].lower()]
        if not cands:
            continue
        # Duplicates exist; the primary team group is the most populated one.
        g = max(cands, key=lambda g: len(g.get("PropertyIds") or []))
        members = g.get("PropertyIds") or []
        for pid in members:
            by_prop[pid].append(code)
        catalogue.append({"code": code, "label": PG_LABELS[code],
                          "kind": "pg", "count": len(members)})

    for g in sorted(groups, key=lambda g: g.get("Name") or ""):
        name = (g.get("Name") or "")
        if not name.startswith("MF Region_"):
            continue
        manager = name[len("MF Region_"):].strip()
        code = "mf-" + slugify(manager)
        members = g.get("PropertyIds") or []
        for pid in members:
            by_prop[pid].append(code)
        catalogue.append({"code": code, "label": f"MF · {manager}",
                          "kind": "region", "count": len(members)})

    print(f"  portfolios: {sum(1 for c in catalogue if c['kind'] == 'pg')} PGs + "
          f"{sum(1 for c in catalogue if c['kind'] == 'region')} regional-manager regions; "
          f"{len(by_prop)} properties carry a code")
    return by_prop, catalogue


def build_listing_pf(per_prop, pf_by_prop):
    """
    listable_uid -> portfolio codes, for the live listings widget.

    The widget's street-address join works for single-family but NOT for
    multi-family: a unit advertises its own building address ("2601 Champions
    Way #104") while the community property record carries one Address1, so no
    MF listing ever matched and every regional-manager filter showed zero
    available homes. The archive join in build_model() already resolved
    listing -> property by PropertyId (with address fallback), so publish that
    mapping keyed by the SAME listable uid the widget's listings.json rows carry.

    Only recently-touched listings are included (posted now, or updated in the
    last 60 days) - that covers everything the live feed can be showing plus
    the just-leased stragglers, at ~1/8 the size of the full archive map.
    """
    from datetime import timedelta
    cutoff = (date.today() - timedelta(days=60)).isoformat()
    out = {}
    for pid, ls in per_prop.items():
        codes = pf_by_prop.get(pid)
        if not codes:
            continue
        for l in ls:
            if not l.get("Id"):
                continue
            if l.get("PostedToWebsite") or (l.get("LastUpdatedAt") or "") >= cutoff:
                out[l["Id"]] = codes
    print(f"  listing_pf: {len(out)} live/recent listings mapped to portfolio codes")
    return out


def write_map_data(records, pf_by_prop=None, pf_catalogue=None, listing_pf=None):
    """Compact JSON the map widget fetches. Everything the pins and cards need."""
    pf_by_prop = pf_by_prop or {}
    pins = []
    for r in records:
        if not (r.get("lat") and r.get("lng")):
            continue
        codes = pf_by_prop.get(r["pid"])
        pins.append({
            "id": r["pid"], "k": "c" if r["kind"] == "community" else "h",
            "n": r.get("name") or r["street"], "s": r["street"], "c": r["city"],
            "st": r["state"], "z": r["zip"],
            "lat": r["lat"], "lng": r["lng"],
            "a": 1 if r.get("available") else 0,
            "ac": r.get("available_count", 1 if r.get("available") else 0),
            "bd": r.get("beds"), "ba": r.get("baths"), "sf": r.get("sqft"),
            "r": r.get("rent") or r.get("rent_min"),
            "rmax": r.get("rent_max"),
            "u": r.get("units"),
            "p": (r["photos"][0]["thumb"] if r.get("photos") else None),
            "url": r["url"],
            # portfolio codes (PG / regional manager) - omitted when none, so
            # the file only grows for properties that actually carry a code
            **({"pf": codes} if codes else {}),
        })
    write(SITE / "portfolio.json", json.dumps(pins, separators=(",", ":")))
    if pf_catalogue is not None:
        write(SITE / "portfolios.json", json.dumps(
            {"version": 1, "portfolios": pf_catalogue,
             "listing_pf": listing_pf or {}}, separators=(",", ":")))
        with_pf = sum(1 for p in pins if p.get("pf"))
        print(f"  portfolios.json: {len(pf_catalogue)} filter entries; "
              f"{with_pf}/{len(pins)} pins carry a portfolio code")
    missing = len(records) - len(pins)
    print(f"  portfolio.json: {len(pins)} mapped pins"
          + (f" ({missing} without coordinates - not shown on the map)" if missing else ""))
    return pins


# ------------------------------------------------------------------ main ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-pull everything from AppFolio")
    ap.add_argument("--offline", action="store_true", help="rebuild from cache, no network")
    ap.add_argument("--limit", type=int, help="render only N properties (fast iteration)")
    ap.add_argument("--preview", action="store_true",
                    help="internal review build: noindex everywhere + robots Disallow + banner")
    args = ap.parse_args()

    global PREVIEW
    PREVIEW = args.preview
    import templates as T
    T.PREVIEW = args.preview

    print(f"Atrium Portfolio build  ->  {BASE_URL}"
          + ("   [PREVIEW: noindex, not for public launch]" if args.preview else ""))
    print("\n[1/5] AppFolio data")
    data = load_or_fetch(args.refresh, args.offline)

    print("\n[2/5] Join archive to managed portfolio")
    by_id, managed, unit_count, per_prop = build_model(data)

    print("\n[3/5] Geocode")
    pids = select_pids(by_id, per_prop, args.limit)
    props = [by_id[i] for i in pids]
    seed = {} if args.offline else live_feed_coords()
    coords = geocode_all(props, seed_coords=seed)

    print("\n[4/5] Sanitize + assemble")
    review = ReviewLog()
    records = assemble(by_id, managed, unit_count, per_prop, coords, review, pids)
    hard, soft, brand, hard_n = review.summary()
    path = review.write()
    print(f"  {len(records)} property records")
    print(f"  compliance: {hard_n} listings with HARD findings -> {path}")
    for cat, n in hard.most_common():
        print(f"      HARD  {cat:18} {n}")
    for cat, n in soft.most_common(4):
        print(f"      soft  {cat:18} {n}")
    for cat, n in brand.most_common():
        print(f"      brand {cat:18} {n}   (banned price-first vocabulary removed)")

    print("\n[5/5] Verify")
    sanity_check(records, feed_count=len(seed) if seed else None)

    print("\n[6/6] Render")
    render_all(records, review)
    pf_by_prop, pf_catalogue = build_portfolio_codes(data)
    listing_pf = build_listing_pf(per_prop, pf_by_prop)
    write_map_data(records, pf_by_prop, pf_catalogue, listing_pf)

    avail = sum(1 for r in records if r.get("available"))
    print(f"\nDone. {avail} available / {len(records) - avail} leased. Output in {SITE}/")


if __name__ == "__main__":
    main()
