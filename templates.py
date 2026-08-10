#!/usr/bin/env python3
"""
Page rendering for the portfolio site.

Every page is a standalone, crawlable HTML document - that is the entire point of
the project. Search engines cannot see inside the Squarespace iframe, so the
ranking has to come from these files.

SEO contract per page:
  - unique <title> and meta description built from real property data
  - self-referencing canonical
  - Open Graph + Twitter card
  - JSON-LD: Accommodation subtype + BreadcrumbList
  - availability declared honestly:
        available -> schema.org/InStock, apply button present
        leased    -> schema.org/SoldOut, NO apply button anywhere on the page
  - internal links out to the city hub and to what IS available nearby

The leased treatment is the whole reason this project exists. The old site kept
dead listings up and let prospects apply to them. Here a leased page keeps its
search value but cannot convert into a bad application: the apply CTA is not
rendered at all (not hidden with CSS - absent from the DOM), and the page leads
with what is actually available near it.
"""
import html
import json
import re
from datetime import date

BRAND = "Atrium Management"

# Set by build.py --preview. Flips every page to noindex and shows a review banner.
PREVIEW = False

# --------------------------------------------------------------------------
# Shared chrome. Matches the residential listings widget exactly: Open Sans,
# red #f13d3d, ink #070707, hairline #e6e6e6, uppercase letter-spaced CTAs.
# --------------------------------------------------------------------------
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;500;600;700&display=swap');
:root{--red:#f13d3d;--ink:#070707;--line:#e6e6e6;--muted:#666;--bg:#fff;
  --font:"Open Sans","Helvetica Neue",Helvetica,Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;font-family:var(--font);color:var(--ink);background:var(--bg);
  -webkit-font-smoothing:antialiased;line-height:1.55}
a{color:inherit;text-decoration:none}
img{max-width:100%;display:block}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}

/* ---- motion: everything arrives, nothing pops ---- */
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@keyframes fade{from{opacity:0}to{opacity:1}}
@keyframes sweep{from{transform:translateX(-101%)}to{transform:none}}
@keyframes drift{from{transform:scale(1.06)}to{transform:scale(1)}}
.rise{animation:rise .55s cubic-bezier(.2,.7,.3,1) both}
.reveal{opacity:0;transform:translateY(18px);transition:opacity .6s cubic-bezier(.2,.7,.3,1),transform .6s cubic-bezier(.2,.7,.3,1)}
.reveal.in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){
  .rise,.hero-img{animation:none!important}
  .reveal{opacity:1;transform:none;transition:none}
  *{scroll-behavior:auto!important}
}

/* ---- header ---- */
header.site{border-bottom:1px solid var(--line);position:sticky;top:0;background:rgba(255,255,255,.94);
  backdrop-filter:saturate(1.6) blur(8px);z-index:40}
header.site .wrap{display:flex;align-items:center;gap:18px;height:62px}
/* The real wordmark file, never type set to look like it - the brand rules are
   explicit that the letterforms must not be recreated. Height is fixed and width
   follows, so the lockup can never be stretched. */
.logo{display:flex;align-items:center;flex:none}
.logo img{height:19px;width:auto;display:block}
@media(max-width:520px){.logo img{height:16px}}
header.site nav{margin-left:auto;display:flex;gap:20px;font-size:13px;font-weight:600;
  text-transform:uppercase;letter-spacing:1.2px}
header.site nav a{position:relative;padding:4px 0;color:var(--muted)}
header.site nav a:after{content:"";position:absolute;left:0;right:0;bottom:0;height:2px;background:var(--red);
  transform:scaleX(0);transform-origin:left;transition:transform .28s cubic-bezier(.2,.7,.3,1)}
header.site nav a:hover{color:var(--ink)}
header.site nav a:hover:after{transform:scaleX(1)}
@media(max-width:640px){header.site nav a:not(.cta){display:none}}

/* ---- breadcrumb ---- */
.crumb{font-size:12px;color:var(--muted);padding:16px 0 0;letter-spacing:.3px}
.crumb a:hover{color:var(--red)}
.crumb span{margin:0 7px;opacity:.5}

/* ---- hero ---- */
.hero{position:relative;margin-top:14px;border-radius:14px;overflow:hidden;background:#eceff3;
  aspect-ratio:16/9;max-height:520px}
.hero-img{width:100%;height:100%;object-fit:cover;animation:drift 1.4s cubic-bezier(.2,.7,.3,1) both}
.hero-scrim{position:absolute;inset:0;background:linear-gradient(180deg,rgba(7,7,7,0) 45%,rgba(7,7,7,.72) 100%)}
.hero-meta{position:absolute;left:0;right:0;bottom:0;padding:22px 24px;color:#fff;
  display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap}
.hero-price{font-size:30px;font-weight:700;line-height:1}
.hero-sub{font-size:14px;opacity:.92;font-weight:500}
.shots{position:absolute;right:16px;top:16px;background:rgba(7,7,7,.62);color:#fff;font-size:12px;
  font-weight:600;padding:6px 11px;border-radius:20px;display:inline-flex;align-items:center;gap:6px}

/* ---- LEASED banner ---- */
/* Deliberately loud and never dismissible. The failure mode we are designing
   against is a prospect not noticing, then applying to a home rented in 2019. */
.leased{position:absolute;top:0;left:0;right:0;background:var(--ink);color:#fff;
  padding:13px 24px;display:flex;align-items:center;gap:12px;z-index:3;overflow:hidden}
.leased:before{content:"";position:absolute;inset:0;background:var(--red);
  transform:translateX(-101%);animation:sweep .7s cubic-bezier(.2,.7,.3,1) .25s both;z-index:-1;opacity:.16}
.leased svg{flex:none}
.leased-t{font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:2.4px}
.leased-s{font-size:13px;opacity:.82;font-weight:400;letter-spacing:0}
@media(max-width:560px){.leased{flex-direction:column;align-items:flex-start;gap:4px;padding:11px 16px}
  .leased-t{font-size:12px;letter-spacing:1.8px}}

/* ---- title block ---- */
h1{font-size:31px;line-height:1.2;margin:26px 0 6px;font-weight:700;letter-spacing:-.4px}
.addr{font-size:15px;color:var(--muted);font-weight:600}
.specs{display:flex;flex-wrap:wrap;gap:26px;margin:20px 0;padding:18px 0;
  border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.spec{display:flex;align-items:center;gap:9px;font-size:14.5px;font-weight:600}
.spec svg{width:19px;height:19px;flex:none;color:var(--red)}
.spec i{font-style:normal;color:var(--muted);font-weight:400}

/* ---- body layout ---- */
.cols{display:grid;grid-template-columns:1fr 320px;gap:44px;margin:34px 0 60px;align-items:start}
@media(max-width:900px){.cols{grid-template-columns:1fr;gap:30px}}
h2{font-size:13px;text-transform:uppercase;letter-spacing:2.2px;color:var(--muted);
  margin:34px 0 14px;font-weight:700}
.prose{font-size:15.5px;white-space:pre-line;color:#242424}
.tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.tag{font-size:12.5px;border:1px solid var(--line);border-radius:20px;padding:6px 13px;
  background:#fafafa;transition:border-color .2s,transform .2s}
.tag:hover{border-color:var(--red);transform:translateY(-1px)}

/* ---- gallery ---- */
.gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:9px;margin-top:8px}
.gal a{aspect-ratio:4/3;border-radius:8px;overflow:hidden;background:#eceff3;position:relative}
.gal img{width:100%;height:100%;object-fit:cover;transition:transform .5s cubic-bezier(.2,.7,.3,1)}
.gal a:hover img{transform:scale(1.06)}

/* ---- sidebar ---- */
.card{border:1px solid var(--line);border-radius:12px;padding:20px;position:sticky;top:82px}
.card .k{font-size:12px;text-transform:uppercase;letter-spacing:1.6px;color:var(--muted);font-weight:700}
.card .big{font-size:27px;font-weight:700;margin:5px 0 2px}
.rowk{display:flex;justify-content:space-between;font-size:14px;padding:9px 0;border-top:1px solid var(--line)}
.rowk span:first-child{color:var(--muted)}
.btn{display:block;text-align:center;padding:14px;font-size:13.5px;font-weight:700;text-transform:uppercase;
  letter-spacing:1.6px;border-radius:6px;margin-top:14px;transition:background .2s,transform .18s}
.btn-p{background:var(--ink);color:#fff}
.btn-p:hover{background:var(--red);transform:translateY(-1px)}
.btn-s{background:#f2f2f2;color:var(--ink)}
.btn-s:hover{background:var(--line)}
.note{font-size:12.5px;color:var(--muted);margin-top:12px;line-height:1.5}

/* ---- nearby / cards ---- */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}
.pcard{border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column;
  transition:box-shadow .18s,transform .18s;background:#fff}
.pcard:hover{box-shadow:0 14px 34px -18px rgba(7,7,7,.42);transform:translateY(-2px)}
.pcard .ph{aspect-ratio:4/3;background:#eceff3;position:relative;overflow:hidden}
.pcard .ph img{width:100%;height:100%;object-fit:cover;transition:transform .5s cubic-bezier(.2,.7,.3,1)}
.pcard:hover .ph img{transform:scale(1.05)}
.pcard .pb{padding:12px 14px 14px}
.pcard .pp{font-size:16px;font-weight:700}
.pcard .pa{font-size:13px;color:var(--muted);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pcard .ps{font-size:12.5px;color:#333;margin-top:7px}
.chip{position:absolute;left:0;bottom:0;font-size:11px;font-weight:700;text-transform:uppercase;
  letter-spacing:1.2px;padding:6px 10px;background:rgba(255,255,255,.9)}
.chip.off{background:var(--ink);color:#fff}

/* ---- footer ---- */
footer.site{border-top:1px solid var(--line);margin-top:60px;padding:34px 0 50px;font-size:13px;color:var(--muted)}
footer.site .wrap{display:flex;gap:24px;flex-wrap:wrap;align-items:center}
footer.site a:hover{color:var(--red)}
.fh{font-size:11.5px;line-height:1.6;opacity:.85;max-width:640px}
"""

JS = """
// Reveal-on-scroll. Everything below the fold arrives rather than pops.
(function(){
  var io=new IntersectionObserver(function(es){
    es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('in'); io.unobserve(e.target); } });
  },{rootMargin:'0px 0px -8% 0px',threshold:.06});
  document.querySelectorAll('.reveal').forEach(function(el,i){
    el.style.transitionDelay=Math.min(i*40,240)+'ms'; io.observe(el);
  });
  // Gallery: swap the hero to the clicked shot instead of leaving the page.
  var hero=document.querySelector('.hero-img');
  document.querySelectorAll('.gal a').forEach(function(a){
    a.addEventListener('click',function(ev){
      var full=a.getAttribute('data-full'); if(!hero||!full) return;
      ev.preventDefault();
      hero.style.transition='opacity .22s'; hero.style.opacity=0;
      setTimeout(function(){ hero.src=full; hero.onload=function(){ hero.style.opacity=1; }; },200);
      document.querySelector('.hero').scrollIntoView({behavior:'smooth',block:'center'});
    });
  });
})();
"""

ICON = {
    "bed": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 17v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5M2 17h20M2 17v3M22 17v3M6 10V7a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v3"/></svg>',
    "bath": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h18v3a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4v-3zM6 12V6a2 2 0 0 1 2-2 2 2 0 0 1 2 2M5 19l-1 2M19 19l1 2"/></svg>',
    "area": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 3h18v18H3zM9 3v18M3 9h18"/></svg>',
    "home": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 10l9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg>',
    "cal": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
    "lock": '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg>',
    "camera": '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>',
}


PREVIEW_BAR = (
    '<div style="background:#070707;color:#fff;font:600 12px/1.4 system-ui,sans-serif;'
    'letter-spacing:1.6px;text-transform:uppercase;text-align:center;padding:9px 14px">'
    'Internal preview &middot; not public, not indexed &middot; content pending Fair Housing review'
    '</div>')


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def money(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f <= 0 else f"${f:,.0f}"


_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _ship(css):
    """Strip the internal commentary out of the CSS we serve publicly."""
    return _CSS_COMMENT.sub("", css)


def shell(title, desc, canonical, body, base, og_image=None, ld=None, extra_head=""):
    ld_block = ""
    if ld:
        ld_block = "\n".join(
            f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in ld)
    og = f'<meta property="og:image" content="{e(og_image)}">' if og_image else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canonical)}">
<link rel="icon" href="/static/favicon.png" type="image/png">
<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
{'<meta name="robots" content="noindex,nofollow">' if PREVIEW else '<meta name="robots" content="index,follow,max-image-preview:large">'}
<meta property="og:type" content="website">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(canonical)}">
<meta property="og:site_name" content="{e(BRAND)}">
{og}
<meta name="twitter:card" content="summary_large_image">
{extra_head}
<style>{_ship(CSS)}</style>
{ld_block}
</head>
<body>
{PREVIEW_BAR if PREVIEW else ""}
<header class="site"><div class="wrap">
  <a class="logo" href="{base}/" aria-label="{e(BRAND)} home">
    <img src="/static/atrium-wordmark.svg" alt="{e(BRAND)}" width="122" height="19">
  </a>
  <nav>
    <a href="{base}/">Portfolio Map</a>
    <a href="https://listings.meetatrium.com/widget.html">Available Rentals</a>
    <a class="cta" href="https://meetatrium.com">meetatrium.com</a>
  </nav>
</div></header>
{body}
<footer class="site"><div class="wrap">
  <div>&copy; {date.today().year} {e(BRAND)}</div>
  <div><a href="https://meetatrium.com">meetatrium.com</a></div>
  <div><a href="{base}/sitemap.xml">Sitemap</a></div>
  <p class="fh">{e(BRAND)} is an Equal Housing Opportunity provider. We do not discriminate on the
  basis of race, color, religion, sex, familial status, national origin, disability, or any other
  characteristic protected by federal, state, or local law. Property details reflect the most recent
  advertised information and are provided for reference only; availability, pricing, and terms are
  subject to change and should be confirmed before relying on them.</p>
</div></footer>
<script>{JS}</script>
</body>
</html>"""


def leased_banner(last_seen=None):
    when = ""
    if last_seen:
        try:
            when = " &middot; Last advertised " + datetime_month(last_seen)
        except Exception:
            when = ""
    return f"""<div class="leased">
  {ICON['lock']}
  <span class="leased-t">Leased</span>
  <span class="leased-s">This home is not currently available for rent{when}</span>
</div>"""


def datetime_month(iso):
    from datetime import datetime as _d
    return _d.strptime(iso[:10], "%Y-%m-%d").strftime("%B %Y")


def specs_row(beds, baths, sqft, ptype=None, year=None):
    out = []
    if beds is not None:
        out.append((ICON["bed"], "Studio" if int(beds) == 0 else f"{int(beds)}", "Bedrooms" if beds != 1 else "Bedroom"))
    if baths:
        out.append((ICON["bath"], f"{float(baths):g}", "Bathrooms" if float(baths) != 1 else "Bathroom"))
    if sqft:
        out.append((ICON["area"], f"{int(sqft):,}", "Sq Ft"))
    if ptype:
        out.append((ICON["home"], ptype.replace("-", " "), ""))
    if year:
        out.append((ICON["cal"], str(year), "Built"))
    if not out:
        return ""
    cells = "".join(f'<div class="spec">{ic}<span>{e(v)}</span> <i>{e(l)}</i></div>' for ic, v, l in out)
    return f'<div class="specs reveal">{cells}</div>'


def gallery(photos, limit=12):
    if len(photos) < 2:
        return ""
    shots = photos[1:limit + 1]
    cells = "".join(
        f'<a href="{e(p["url"])}" data-full="{e(p["url"])}" aria-label="Photo {i + 2}">'
        f'<img loading="lazy" src="{e(p.get("thumb") or p["url"])}" alt=""></a>'
        for i, p in enumerate(shots))
    return f'<h2 class="reveal">Photos</h2><div class="gal reveal">{cells}</div>'


def nearby_block(items, heading, base, empty_msg=None):
    """The module that fixes the old site's failure: leased page -> live inventory."""
    if not items:
        return f'<h2 class="reveal">{e(heading)}</h2><p class="note reveal">{e(empty_msg or "")}</p>' if empty_msg else ""
    cards = []
    for r in items:
        ph = r["photos"][0]["thumb"] if r.get("photos") else None
        img = (f'<img loading="lazy" src="{e(ph)}" alt="{e(r["street"])}">' if ph else "")
        price = money(r.get("rent")) or money(r.get("rent_min")) or "Contact for price"
        bits = []
        if r.get("beds") is not None:
            bits.append("Studio" if int(r["beds"]) == 0 else f'{int(r["beds"])} bd')
        if r.get("baths"):
            bits.append(f'{float(r["baths"]):g} ba')
        if r.get("sqft"):
            bits.append(f'{int(r["sqft"]):,} sqft')
        chip = '<span class="chip">Available</span>' if r.get("available") else '<span class="chip off">Leased</span>'
        cards.append(
            f'<a class="pcard" href="{base}{e(r["url"])}">'
            f'<div class="ph">{img}{chip}</div>'
            f'<div class="pb"><div class="pp">{e(price)}</div>'
            f'<div class="pa">{e(r["street"])}, {e(r["city"])}</div>'
            # Join with the literal character, not the HTML entity - e() would
            # escape the entity and print "&middot;" on the page.
            f'<div class="ps">{e(" · ".join(bits))}</div></div></a>')
    return (f'<h2 class="reveal">{e(heading)}</h2>'
            f'<div class="grid reveal">{"".join(cards)}</div>')


# ==========================================================================
# PAGE RENDERERS
# ==========================================================================

def fit_title(core, limit=60):
    """
    Compose "<core> | Atrium Management", keeping it near the ~60 chars Google
    shows. Slicing the combined string cut mid-word and shipped titles ending
    "| Atrium Ma" - so drop the brand suffix entirely before mutilating it, and
    if the core alone is still long, trim on a word boundary.
    """
    full = f"{core} | {BRAND}"
    if len(full) <= limit:
        return full
    if len(core) <= limit:
        return core
    cut = core[:limit]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > limit * 0.6 else cut).rstrip(" ,-\u2013\u2014")


def _postal(r):
    return {"@type": "PostalAddress", "streetAddress": r["street"], "addressLocality": r["city"],
            "addressRegion": r["state"], "postalCode": r["zip"], "addressCountry": "US"}


def _breadcrumbs(base, trail):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": n,
                 **({"item": base + u} if u else {})}
                for i, (n, u) in enumerate(trail)]}


def _accommodation(r, kind):
    node = {"@type": kind, "name": r.get("name") or r["street"], "address": _postal(r)}
    if r.get("lat") and r.get("lng"):
        node["geo"] = {"@type": "GeoCoordinates", "latitude": r["lat"], "longitude": r["lng"]}
    if r.get("beds") is not None:
        node["numberOfBedrooms"] = int(r["beds"])
    if r.get("baths"):
        node["numberOfBathroomsTotal"] = float(r["baths"])
    if r.get("sqft"):
        node["floorSize"] = {"@type": "QuantitativeValue", "value": int(r["sqft"]), "unitCode": "FTK"}
    if r.get("desc"):
        node["description"] = r["desc"][:900]
    if r.get("photos"):
        node["photo"] = [p["url"] for p in r["photos"][:8]]
    if r.get("amenities"):
        node["amenityFeature"] = [
            {"@type": "LocationFeatureSpecification", "name": a, "value": True}
            for a in r["amenities"][:14]]
    return node


def render_home(r, base, nearby):
    """Single-family / commercial detail page."""
    avail = r["available"]
    city_url = f"{base}/rentals/{r['city_slug']}/"
    canonical = base + r["url"]
    label = f"{r['street']}, {r['city']}, {r['state']} {r['zip']}"

    bits = [x for x in (
        ("Studio" if r.get("beds") == 0 else f"{int(r['beds'])} bed") if r.get("beds") is not None else None,
        f"{float(r['baths']):g} bath" if r.get("baths") else None,
        f"{int(r['sqft']):,} sq ft" if r.get("sqft") else None) if x]
    spec_txt = ", ".join(bits)

    if avail:
        title = fit_title(f"{r['street']}, {r['city']} {r['state']} - {spec_txt} for Rent")
        desc = (f"{spec_txt.capitalize()} rental at {label}. "
                f"{money(r.get('rent')) or 'Contact for pricing'} per month. "
                f"View photos, amenities, and apply online with {BRAND}.")[:158]
    else:
        # Leased pages target the ADDRESS and the neighborhood, not "for rent" -
        # ranking for the address is what drives the traffic, and promising
        # availability we do not have is exactly the old site's mistake.
        title = fit_title(f"{r['street']}, {r['city']}, {r['state']} - Rental Details")
        desc = (f"{spec_txt.capitalize()} home at {label}, managed by {BRAND}. "
                f"Currently leased - see comparable rentals available now in {r['city']}.")[:158]

    hero_photo = r["photos"][0]["url"] if r["photos"] else None
    hero_img = (f'<img class="hero-img" src="{e(hero_photo)}" alt="{e(label)}">'
                if hero_photo else "")
    shots = (f'<span class="shots">{ICON["camera"]}{len(r["photos"])} photos</span>'
             if len(r["photos"]) > 1 else "")

    price = money(r.get("rent"))
    hero_price = (f'<div class="hero-price">{price}<span class="hero-sub"> / month</span></div>'
                  if avail and price else
                  (f'<div class="hero-sub">Last advertised at {price}/month</div>' if price else ""))

    body_hero = (f'<div class="hero rise">{leased_banner(r.get("last_seen")) if not avail else ""}'
                 f'{hero_img}<div class="hero-scrim"></div>{shots}'
                 f'<div class="hero-meta">{hero_price}</div></div>')

    # ---- sidebar: apply CTA only when the home is genuinely available ----
    if avail:
        rows = "".join(
            f'<div class="rowk"><span>{e(k)}</span><span>{e(v)}</span></div>'
            for k, v in (
                ("Available", r.get("available_on") or "Now"),
                ("Deposit", money(r.get("deposit")) or "-"),
                ("Dogs", r.get("dogs") or "Ask"),
                ("Cats", r.get("cats") or "Ask")) if v)
        apply_btn = (f'<a class="btn btn-p" href="{e(r["apply_url"])}" rel="nofollow">Apply Now</a>'
                     if r.get("apply_url") else "")
        side = (f'<div class="card reveal"><div class="k">Monthly Rent</div>'
                f'<div class="big">{e(price or "Contact us")}</div>{rows}{apply_btn}'
                f'<a class="btn btn-s" href="https://listings.meetatrium.com/widget.html">'
                f'See All Rentals</a></div>')
    else:
        # No apply button in the DOM at all - not hidden, absent.
        side = (f'<div class="card reveal"><div class="k">Status</div>'
                f'<div class="big">Leased</div>'
                f'<p class="note">This home is not accepting applications. '
                f'{BRAND} manages it on behalf of its owner.</p>'
                f'<a class="btn btn-p" href="https://listings.meetatrium.com/widget.html">'
                f'See What&rsquo;s Available</a>'
                f'<a class="btn btn-s" href="{city_url}">More in {e(r["city"])}</a>'
                f'<p class="note">Looking for something like this? Our team can tell you when a '
                f'comparable home comes up. Call {e("(407) 585-2721")}.</p></div>')

    desc_block = (f'<h2 class="reveal">About This Property</h2>'
                  f'<div class="prose reveal">{e(r["desc"])}</div>') if r.get("desc") else ""
    amen = ""
    if r.get("amenities"):
        amen = ('<h2 class="reveal">Features</h2><div class="tags reveal">'
                + "".join(f'<span class="tag">{e(a)}</span>' for a in r["amenities"][:24]) + "</div>")

    near_heading = ("Available Now Nearby" if not avail else f"More Rentals in {r['city']}")
    near = nearby_block(nearby, near_heading, base,
                        empty_msg=f"Nothing available in {r['city']} at the moment - "
                                  f"check all Atrium rentals for the latest.")

    h1 = r.get("title") or f"{spec_txt.capitalize()} in {r['city']}"
    body = f"""<div class="wrap">
  <nav class="crumb"><a href="{base}/">Portfolio</a><span>/</span>
    <a href="{city_url}">{e(r['city'])}</a><span>/</span>{e(r['street'])}</nav>
  {body_hero}
  <h1>{e(h1)}</h1>
  <div class="addr">{e(label)}</div>
  {specs_row(r.get('beds'), r.get('baths'), r.get('sqft'), r.get('ptype'), r.get('year_built'))}
  <div class="cols">
    <div>{desc_block}{amen}{gallery(r['photos'])}</div>
    <div>{side}</div>
  </div>
  {near}
</div>"""

    kind = "SingleFamilyResidence" if r.get("ptype") == "Single-Family" else "Accommodation"
    listing = {
        "@context": "https://schema.org", "@type": "RealEstateListing",
        "url": canonical, "name": h1,
        "about": _accommodation(r, kind),
        "provider": {"@type": "RealEstateAgent", "name": BRAND, "url": "https://meetatrium.com"},
    }
    offer = {"@type": "Offer",
             "businessFunction": "http://purl.org/goodrelations/v1#LeaseOut",
             "availability": "https://schema.org/InStock" if avail else "https://schema.org/SoldOut"}
    if avail and r.get("rent"):
        # Price is only asserted while it is actually true. A leased page carries
        # SoldOut and no price so Google never renders it as a live rental offer.
        offer.update({"price": int(r["rent"]), "priceCurrency": "USD",
                      "priceSpecification": {"@type": "UnitPriceSpecification",
                                             "price": int(r["rent"]), "priceCurrency": "USD",
                                             "unitCode": "MON"}})
    listing["offers"] = offer

    crumbs = _breadcrumbs(base, [("Portfolio", "/"),
                                 (r["city"], f"/rentals/{r['city_slug']}/"),
                                 (r["street"], None)])
    return shell(title, desc, canonical, body, base, hero_photo, [listing, crumbs])


def render_community(r, base, nearby):
    """Multi-family community page - the hub for its floor plans."""
    canonical = base + r["url"]
    city_url = f"{base}/rentals/{r['city_slug']}/"
    label = f"{r['street']}, {r['city']}, {r['state']} {r['zip']}"
    avail = r["available"]
    n = r.get("available_count", 0)

    if avail:
        title = fit_title(f"{r['name']} Apartments in {r['city']}, {r['state']}")
        desc = (f"{n} unit{'s' if n != 1 else ''} available at {r['name']} in {r['city']}, "
                f"{r['state']}. {len(r['plans'])} floor plans, "
                f"{money(r.get('rent_min')) or 'call'}+. Tour with {BRAND}.")[:158]
    else:
        title = fit_title(f"{r['name']} - {r['city']}, {r['state']} Apartments")
        desc = (f"{r['name']} in {r['city']}, {r['state']} - {r['units']} units, "
                f"{len(r['plans'])} floor plans, managed by {BRAND}. "
                f"No units available right now; see what is open nearby.")[:158]

    hero_photo = r["photos"][0]["url"] if r["photos"] else None
    hero_img = f'<img class="hero-img" src="{e(hero_photo)}" alt="{e(r["name"])}">' if hero_photo else ""
    rng = ""
    if r.get("rent_min"):
        rng = (money(r["rent_min"]) if r["rent_min"] == r.get("rent_max")
               else f'{money(r["rent_min"])} &ndash; {money(r.get("rent_max"))}')
    hero_price = (f'<div class="hero-price">{rng}<span class="hero-sub"> / month</span></div>'
                  if avail and rng else (f'<div class="hero-sub">Recently advertised {rng}/month</div>' if rng else ""))
    body_hero = (f'<div class="hero rise">{leased_banner() if not avail else ""}{hero_img}'
                 f'<div class="hero-scrim"></div><div class="hero-meta">{hero_price}</div></div>')

    # floor plan table - the real unique content on a community page
    rows = []
    for p in r["plans"]:
        bl = "Studio" if p.get("beds") == 0 else (f"{int(p['beds'])} Bed" if p.get("beds") is not None else "-")
        ba = f"{float(p['baths']):g} Bath" if p.get("baths") else ""
        sf = f"{int(p['sqft']):,} sq ft" if p.get("sqft") else ""
        pr = money(p.get("rent")) or "Call"
        st = (f'<span class="chip">{p["available_count"]} available</span>'
              if p.get("available_count") else '<span class="chip off">Leased</span>')
        ph = p["photos"][0]["thumb"] if p.get("photos") else None
        img = f'<img loading="lazy" src="{e(ph)}" alt="{e(bl)} at {e(r["name"])}">' if ph else ""
        rows.append(
            f'<a class="pcard" href="{base}{e(r["url"])}{e(p["slug"])}/">'
            f'<div class="ph">{img}{st}</div><div class="pb">'
            f'<div class="pp">{e(pr)}</div><div class="pa">{e(bl)} &middot; {e(ba)}</div>'
            f'<div class="ps">{e(sf)}</div></div></a>')
    plans_block = (f'<h2 class="reveal">Floor Plans</h2><div class="grid reveal">{"".join(rows)}</div>')

    if avail:
        side = (f'<div class="card reveal"><div class="k">Availability</div>'
                f'<div class="big">{n} open</div>'
                f'<div class="rowk"><span>Units</span><span>{r["units"]}</span></div>'
                f'<div class="rowk"><span>Floor plans</span><span>{len(r["plans"])}</span></div>'
                f'<a class="btn btn-p" href="https://listings.meetatrium.com/widget.html?q={e(r["name"])}">'
                f'See Available Units</a></div>')
    else:
        side = (f'<div class="card reveal"><div class="k">Status</div>'
                f'<div class="big">Fully Leased</div>'
                f'<div class="rowk"><span>Units</span><span>{r["units"]}</span></div>'
                f'<div class="rowk"><span>Floor plans</span><span>{len(r["plans"])}</span></div>'
                f'<p class="note">No units are accepting applications right now.</p>'
                f'<a class="btn btn-p" href="https://listings.meetatrium.com/widget.html">'
                f'See What&rsquo;s Available</a>'
                f'<a class="btn btn-s" href="{city_url}">More in {e(r["city"])}</a></div>')

    desc_block = (f'<h2 class="reveal">About {e(r["name"])}</h2>'
                  f'<div class="prose reveal">{e(r["desc"])}</div>') if r.get("desc") else ""
    amen = ""
    if r.get("amenities"):
        amen = ('<h2 class="reveal">Community Amenities</h2><div class="tags reveal">'
                + "".join(f'<span class="tag">{e(a)}</span>' for a in r["amenities"][:24]) + "</div>")

    near = nearby_block(nearby, "Available Now Nearby" if not avail else f"Also in {r['city']}", base)

    body = f"""<div class="wrap">
  <nav class="crumb"><a href="{base}/">Portfolio</a><span>/</span>
    <a href="{city_url}">{e(r['city'])}</a><span>/</span>{e(r['name'])}</nav>
  {body_hero}
  <h1>{e(r['name'])}</h1>
  <div class="addr">{e(label)}</div>
  {specs_row(None, None, None, "Apartment Community", r.get('year_built'))}
  <div class="cols">
    <div>{desc_block}{plans_block}{amen}{gallery(r['photos'])}</div>
    <div>{side}</div>
  </div>
  {near}
</div>"""

    node = _accommodation(r, "ApartmentComplex")
    node["numberOfAccommodationUnits"] = r["units"]
    listing = {"@context": "https://schema.org", "@type": "RealEstateListing",
               "url": canonical, "name": r["name"], "about": node,
               "provider": {"@type": "RealEstateAgent", "name": BRAND, "url": "https://meetatrium.com"},
               "offers": {"@type": "Offer",
                          "businessFunction": "http://purl.org/goodrelations/v1#LeaseOut",
                          "availability": "https://schema.org/InStock" if avail else "https://schema.org/SoldOut",
                          **({"lowPrice": int(r["rent_min"]), "highPrice": int(r["rent_max"] or r["rent_min"]),
                              "priceCurrency": "USD"} if avail and r.get("rent_min") else {})}}
    crumbs = _breadcrumbs(base, [("Portfolio", "/"), (r["city"], f"/rentals/{r['city_slug']}/"),
                                 (r["name"], None)])
    return shell(title, desc, canonical, body, base, hero_photo, [listing, crumbs])


def render_plan(community, p, base):
    """One floor plan inside a community. Distinct content: layout, size, price."""
    bl = "Studio" if p.get("beds") == 0 else (f"{int(p['beds'])} Bedroom" if p.get("beds") is not None else "Unit")
    ba = f"{float(p['baths']):g} Bath" if p.get("baths") else ""
    name = f"{bl} {ba}".strip()
    canonical = f"{base}{community['url']}{p['slug']}/"
    avail = p.get("available_count", 0) > 0
    title = fit_title(f"{name} at {community['name']} - {community['city']}, {community['state']}")
    desc = (f"{name} floor plan at {community['name']} in {community['city']}, "
            f"{community['state']}"
            + (f", {int(p['sqft']):,} sq ft" if p.get("sqft") else "")
            + (f". {money(p.get('rent'))}/month. " if p.get("rent") else ". ")
            + ("Available now." if avail else "Currently leased - see nearby availability."))[:158]

    hero_photo = p["photos"][0]["url"] if p.get("photos") else (
        community["photos"][0]["url"] if community.get("photos") else None)
    hero_img = f'<img class="hero-img" src="{e(hero_photo)}" alt="{e(name)} at {e(community["name"])}">' if hero_photo else ""
    price = money(p.get("rent"))
    hero_price = (f'<div class="hero-price">{price}<span class="hero-sub"> / month</span></div>'
                  if avail and price else (f'<div class="hero-sub">Last advertised at {price}/month</div>' if price else ""))
    body_hero = (f'<div class="hero rise">{leased_banner(p.get("last_seen")) if not avail else ""}'
                 f'{hero_img}<div class="hero-scrim"></div>'
                 f'<div class="hero-meta">{hero_price}</div></div>')

    if avail:
        side = (f'<div class="card reveal"><div class="k">Monthly Rent</div>'
                f'<div class="big">{e(price or "Call")}</div>'
                f'<div class="rowk"><span>Available</span><span>{p["available_count"]} unit(s)</span></div>'
                + (f'<a class="btn btn-p" href="{e(p["apply_url"])}" rel="nofollow">Apply Now</a>'
                   if p.get("apply_url") else "")
                + f'<a class="btn btn-s" href="{base}{community["url"]}">All Floor Plans</a></div>')
    else:
        side = (f'<div class="card reveal"><div class="k">Status</div><div class="big">Leased</div>'
                f'<p class="note">This floor plan has no units accepting applications right now.</p>'
                f'<a class="btn btn-p" href="https://listings.meetatrium.com/widget.html">'
                f'See What&rsquo;s Available</a>'
                f'<a class="btn btn-s" href="{base}{community["url"]}">All Floor Plans</a></div>')

    desc_block = (f'<h2 class="reveal">About This Floor Plan</h2>'
                  f'<div class="prose reveal">{e(p["desc"])}</div>') if p.get("desc") else ""
    amen = ""
    if p.get("amenities"):
        amen = ('<h2 class="reveal">Features</h2><div class="tags reveal">'
                + "".join(f'<span class="tag">{e(a)}</span>' for a in p["amenities"][:20]) + "</div>")

    body = f"""<div class="wrap">
  <nav class="crumb"><a href="{base}/">Portfolio</a><span>/</span>
    <a href="{base}/rentals/{community['city_slug']}/">{e(community['city'])}</a><span>/</span>
    <a href="{base}{community['url']}">{e(community['name'])}</a><span>/</span>{e(name)}</nav>
  {body_hero}
  <h1>{e(name)} at {e(community['name'])}</h1>
  <div class="addr">{e(community['street'])}, {e(community['city'])}, {e(community['state'])} {e(community['zip'])}</div>
  {specs_row(p.get('beds'), p.get('baths'), p.get('sqft'))}
  <div class="cols"><div>{desc_block}{amen}{gallery(p.get('photos') or [])}</div><div>{side}</div></div>
</div>"""

    node = _accommodation({**p, "name": name, "street": community["street"], "city": community["city"],
                           "state": community["state"], "zip": community["zip"],
                           "lat": community.get("lat"), "lng": community.get("lng")}, "Apartment")
    listing = {"@context": "https://schema.org", "@type": "RealEstateListing",
               "url": canonical, "name": f"{name} at {community['name']}", "about": node,
               "provider": {"@type": "RealEstateAgent", "name": BRAND, "url": "https://meetatrium.com"},
               "offers": {"@type": "Offer",
                          "businessFunction": "http://purl.org/goodrelations/v1#LeaseOut",
                          "availability": "https://schema.org/InStock" if avail else "https://schema.org/SoldOut",
                          **({"price": int(p["rent"]), "priceCurrency": "USD"} if avail and p.get("rent") else {})}}
    crumbs = _breadcrumbs(base, [("Portfolio", "/"), (community["city"], f"/rentals/{community['city_slug']}/"),
                                 (community["name"], community["url"]), (name, None)])
    return shell(title, desc, canonical, body, base, hero_photo, [listing, crumbs])


def render_city(city, state, slug, records, base):
    """City hub - the page that competes for 'houses for rent in <city>'."""
    canonical = f"{base}/rentals/{slug}/"
    avail = [r for r in records if r.get("available")]
    homes = [r for r in records if r["kind"] == "home"]
    comms = [r for r in records if r["kind"] == "community"]
    title = fit_title(f"Houses & Apartments for Rent in {city}, {state}")
    desc = (f"{len(avail)} rental{'s' if len(avail) != 1 else ''} available now in {city}, {state}. "
            f"{BRAND} manages {len(homes)} home{'s' if len(homes) != 1 else ''} and "
            f"{len(comms)} communit{'ies' if len(comms) != 1 else 'y'} here.")[:158]

    def cards(items):
        return nearby_block(items, "", base).replace('<h2 class="reveal"></h2>', "")

    a_block = (f'<h2 class="reveal">Available Now in {e(city)}</h2>{cards(avail[:24])}'
               if avail else
               f'<h2 class="reveal">Available Now in {e(city)}</h2>'
               f'<p class="note reveal">Nothing is open in {e(city)} at this moment. '
               f'<a href="https://listings.meetatrium.com/widget.html" style="color:var(--red);font-weight:600">'
               f'See every Atrium rental &rarr;</a></p>')
    c_block = (f'<h2 class="reveal">Apartment Communities in {e(city)}</h2>{cards(comms[:24])}'
               if comms else "")
    h_block = (f'<h2 class="reveal">Homes We Manage in {e(city)}</h2>{cards(homes[:36])}'
               if homes else "")

    body = f"""<div class="wrap">
  <nav class="crumb"><a href="{base}/">Portfolio</a><span>/</span>{e(city)}</nav>
  <h1>Rentals in {e(city)}, {e(state)}</h1>
  <div class="addr">{len(records)} propert{'ies' if len(records) != 1 else 'y'} managed by {e(BRAND)}
    &middot; {len(avail)} available now</div>
  {a_block}{c_block}{h_block}
</div>"""
    ld = {"@context": "https://schema.org", "@type": "CollectionPage",
          "url": canonical, "name": f"Rentals in {city}, {state}",
          "about": {"@type": "City", "name": city, "containedInPlace": {"@type": "State", "name": state}},
          "provider": {"@type": "RealEstateAgent", "name": BRAND, "url": "https://meetatrium.com"}}
    crumbs = _breadcrumbs(base, [("Portfolio", "/"), (city, None)])
    og = next((r["photos"][0]["url"] for r in records if r.get("photos")), None)
    return shell(title, desc, canonical, body, base, og, [ld, crumbs])


def render_index(records, cities, base, widget_block):
    """
    Site root: the portfolio map, plus a crawlable directory beneath it.

    The map is JavaScript, so a crawler that only sees the map finds zero links
    and none of the property pages get discovered. The directory below it is
    plain anchors - that is the crawl path into the whole site, and it is why
    this page is not just an iframe of map.html.
    """
    total = len(records)
    avail = sum(1 for r in records if r.get("available"))
    comms = sorted((r for r in records if r["kind"] == "community"), key=lambda r: r["name"])

    city_links = "".join(
        f'<a class="tag" href="{base}/rentals/{slug}/">{e(city)}, {e(state)} '
        f'<span style="color:var(--muted)">({n})</span></a>'
        for (city, state, slug), n in cities)
    comm_links = "".join(
        f'<a class="tag" href="{base}{e(r["url"])}">{e(r["name"])}</a>' for r in comms)

    body = f"""<div class="wrap">
  <h1 style="margin-top:30px">Our Portfolio</h1>
  <div class="addr">{total:,} properties managed by {e(BRAND)} across Florida, Virginia and Georgia
    &middot; {avail:,} available right now</div>
</div>
{widget_block}
<div class="wrap">
  <h2 class="reveal">Browse by City</h2>
  <div class="tags reveal">{city_links}</div>
  <h2 class="reveal">Apartment Communities</h2>
  <div class="tags reveal">{comm_links}</div>
</div>"""

    ld = {"@context": "https://schema.org", "@type": "RealEstateAgent",
          "name": BRAND, "url": "https://meetatrium.com",
          "areaServed": [{"@type": "City", "name": c} for (c, s, sl), n in cities[:25]]}
    return shell(
        f"Our Portfolio - {total:,} Properties Managed | {BRAND}",
        f"Explore every property {BRAND} manages: {total:,} homes and communities across "
        f"Florida and Virginia, {avail:,} available to rent right now.",
        base + "/", body, base, None, [ld])
