#!/usr/bin/env python3
"""
Address -> lat/lng for the portfolio map.

AppFolio's properties endpoint carries no coordinates (verified: 0 of 986 rows),
and the public listings feed only has them for the ~517 units advertised right
now. The other ~460 properties need geocoding.

Strategy, cheapest first:
  1. cache/geocode.json          - anything resolved on a previous run
  2. AppFolio's public feed      - free, exact, already fetched, covers live units
  3. US Census batch geocoder    - free, no API key, 10k addresses per request.
                                   Live test: 117/120 matched.
  4. OSM Nominatim               - one at a time, 1 req/sec per their usage policy.
                                   Only for the Census stragglers (typically ~3%).

The cache is committed, so a normal refresh run geocodes nothing at all.
"""
import csv
import io
import json
import time
from pathlib import Path

import re

import requests

HERE = Path(__file__).parent
CACHE = HERE / "cache" / "geocode.json"
OVERRIDES = HERE / "cache" / "coord_overrides.json"
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "AtriumPortfolioMap/1.0 (+https://meetatrium.com; tech@atriummanagement.com)"


def load_cache():
    if CACHE.exists():
        return json.loads(CACHE.read_text())
    return {}


def save_cache(cache):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True))


def key(addr, city, state, zipc):
    return f"{(addr or '').strip().lower()}|{(city or '').strip().lower()}|{(state or '').strip().upper()}|{(zipc or '')[:5]}"


# Unit designators baked into Address1 ("5325 Curry Ford Rd Unit B201",
# "2400 Feather Sound Dr APT 827", "615 Casa Park Court A"). The Census matcher
# wants a plain street address and returns No_Match when one is attached, which
# is most of why 33 properties had no pin - including Aston Square, a 291-unit
# community. Strip it and retry before giving up.
_UNIT = re.compile(
    r"\s+(?:#|apt\.?|unit|ste\.?|suite|bldg\.?|building|lot|trlr|fl\.?|floor)\s*[\w-]*\s*$",
    re.I)
_TRAILING_LETTER = re.compile(r"\s+[A-Z]\d?\s*$")


def street_variants(addr):
    """The address as given, then progressively simplified fallbacks."""
    a = (addr or "").strip()
    out = [a]
    stripped = _UNIT.sub("", a).strip()
    if stripped and stripped != a:
        out.append(stripped)
    bare = _TRAILING_LETTER.sub("", stripped or a).strip()
    if bare and bare not in out:
        out.append(bare)
    return out


def _census_batch(rows):
    """rows: [(id, addr, city, state, zip)]. Returns {id: (lat, lng)}."""
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    try:
        r = requests.post(
            CENSUS,
            files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
            data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
            timeout=300,
        )
    except Exception as e:
        print(f"    census batch failed: {e}")
        return {}
    if r.status_code != 200:
        print(f"    census batch HTTP {r.status_code}")
        return {}
    out = {}
    for line in csv.reader(io.StringIO(r.text)):
        # id, input, match_flag, match_type, matched_addr, "lng,lat", tigerid, side
        if len(line) > 5 and line[2] == "Match" and line[5]:
            try:
                lng, lat = line[5].split(",")
                out[line[0]] = (round(float(lat), 6), round(float(lng), 6))
            except ValueError:
                pass
    return out


def _nominatim(addr, city, state, zipc):
    try:
        r = requests.get(
            NOMINATIM,
            params={"format": "json", "limit": 1,
                    "q": f"{addr}, {city}, {state} {zipc}"},
            headers={"User-Agent": UA},
            timeout=30,
        )
        if r.status_code == 200 and r.json():
            j = r.json()[0]
            return round(float(j["lat"]), 6), round(float(j["lon"]), 6)
    except Exception:
        pass
    return None


def geocode_all(properties, seed_coords=None, verbose=True):
    """
    properties: list of dicts with Id / Address1 / City / State / Zip.
    seed_coords: {address_key: (lat, lng)} harvested from the public listings feed.
    Returns {property_id: (lat, lng)} and updates the on-disk cache.
    """
    cache = load_cache()
    if seed_coords:
        added = 0
        for k, v in seed_coords.items():
            if k not in cache:
                cache[k] = list(v)
                added += 1
        if verbose and added:
            print(f"  seeded {added} coords from the live AppFolio feed")

    # Manual overrides win over everything. Some properties are new builds whose
    # streets exist in neither the Census TIGER database nor OpenStreetMap -
    # Aston Square (291 units) is one - and no amount of retrying will find them.
    over = {}
    if OVERRIDES.exists():
        raw = json.loads(OVERRIDES.read_text())
        over = {k: v for k, v in raw.items()
                if not k.startswith("_") and isinstance(v, (list, tuple)) and len(v) == 2}

    resolved, todo = {}, []
    for p in properties:
        if p.get("Name") in over:
            resolved[p["Id"]] = tuple(over[p["Name"]])
            continue
        k = key(p.get("Address1"), p.get("City"), p.get("State"), p.get("Zip"))
        if k in cache and cache[k]:
            resolved[p["Id"]] = tuple(cache[k])
        elif p.get("Address1") and p.get("City"):
            todo.append((p, k))

    if verbose:
        print(f"  {len(resolved)} from cache, {len(todo)} to geocode")

    # --- Census, in batches of 1000 (their documented ceiling is 10k) ---
    for i in range(0, len(todo), 1000):
        chunk = todo[i:i + 1000]
        rows = [[p["Id"], p.get("Address1") or "", p.get("City") or "",
                 p.get("State") or "", (p.get("Zip") or "")[:5]] for p, _ in chunk]
        got = _census_batch(rows)
        for p, k in chunk:
            if p["Id"] in got:
                resolved[p["Id"]] = got[p["Id"]]
                cache[k] = list(got[p["Id"]])
        if verbose:
            print(f"  census batch {i // 1000 + 1}: {len(got)}/{len(chunk)} matched")
        save_cache(cache)

    # --- Retry the misses with the unit designator stripped ---
    retry = [(p, k) for p, k in todo if p["Id"] not in resolved
             and len(street_variants(p.get("Address1"))) > 1]
    if retry:
        rows = [[p["Id"], street_variants(p.get("Address1"))[1], p.get("City") or "",
                 p.get("State") or "", (p.get("Zip") or "")[:5]] for p, _ in retry]
        got = _census_batch(rows)
        for p, k in retry:
            if p["Id"] in got:
                resolved[p["Id"]] = got[p["Id"]]
                cache[k] = list(got[p["Id"]])
        if verbose:
            print(f"  census retry without unit numbers: {len(got)}/{len(retry)} matched")
        save_cache(cache)

    # --- Nominatim for the stragglers ---
    missing = [(p, k) for p, k in todo if p["Id"] not in resolved]
    if missing and verbose:
        print(f"  {len(missing)} unmatched -> Nominatim (1/sec)")
    for n, (p, k) in enumerate(missing):
        hit = None
        for variant in street_variants(p.get("Address1")):
            hit = _nominatim(variant, p.get("City"), p.get("State"), (p.get("Zip") or "")[:5])
            if hit:
                break
            time.sleep(1.1)
        if hit:
            resolved[p["Id"]] = hit
            cache[k] = list(hit)
        else:
            cache[k] = None          # negative-cache so we stop retrying it
        time.sleep(1.1)              # Nominatim usage policy
        if verbose and (n + 1) % 25 == 0:
            print(f"    nominatim {n + 1}/{len(missing)}")
        if (n + 1) % 25 == 0:
            save_cache(cache)

    save_cache(cache)
    if verbose:
        print(f"  geocoded {len(resolved)}/{len(properties)} properties")
    return resolved
