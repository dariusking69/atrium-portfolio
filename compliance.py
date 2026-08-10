#!/usr/bin/env python3
"""
Fair Housing / accuracy sanitizer for ARCHIVED AppFolio marketing copy.

Why this exists
---------------
The portfolio pages republish marketing descriptions written by many different
people between 2016 and today. A live scan of all 6,262 archived listings found:

    3,122  with a phone number or staff email baked into the body text
    1,254  shouting "AVAILABLE NOW!!!" about units leased years ago
    1,086  naming school districts / "zoned for ..."   (steering risk)
      235  familial-status language, e.g. "perfect for family living"
       34  religious landmarks used as selling points

Putting that back on the public web under Atrium's name today is a bigger
liability than the stale-listing problem this project set out to fix. Every
description passes through here before it is written to a page.

Two severities:
  SOFT  - mechanically fixable (dead phone numbers, stale urgency). Rewritten,
          page publishes normally.
  HARD  - protected-class language. The sentence is dropped AND the listing is
          written to review/flagged.csv for a human to read. Pages still build
          (with the sentence removed) so one bad 2017 description can't block
          the whole site, but nothing silently ships unreviewed.

The regexes are deliberately broad. False positives are cheap here - a dropped
sentence costs a little marketing polish; a missed one is a Fair Housing
complaint. "Church Street" and "an exclusive community pool" are the known
benign hits, so those carry narrow carve-outs rather than blanket suppression.
"""
import csv
import re
from pathlib import Path

HERE = Path(__file__).parent

# --------------------------------------------------------------------------
# HARD - protected-class language. Drop the sentence, flag for human review.
# --------------------------------------------------------------------------
HARD = [
    # Familial status (FHA protected). "Perfect for families" is the single most
    # common real violation in the archive - 235 listings.
    ("familial", re.compile(
        r"\b(?:perfect|ideal|great|excellent|wonderful|suitable)\s+(?:for\s+)?"
        r"(?:a\s+|the\s+|your\s+)?(?:famil|kid|child|couple|single|bachelor|student)", re.I)),
    ("familial", re.compile(
        r"\bfamily[-\s]friendly\b|\bno\s+(?:kids|children|pets\s+or\s+children)\b|"
        r"\badults?\s+only\b|\bmature\s+(?:adult|couple|individual|tenant)|"
        r"\bempty[-\s]nester|\bbachelor\s+pad\b|\bmust\s+be\s+\d+\+?\s+years?\s+old\b", re.I)),

    # Steering by school. Naming a school district signals the demographics of a
    # neighborhood, which is why HUD treats it as a steering risk even when the
    # writer meant it innocently. 1,086 listings.
    ("school_steering", re.compile(
        r"\bzoned\s+for\b[^.!?]*|\b(?:elementary|middle|high|magnet|charter)\s+school\b[^.!?]*|"
        r"\bschool\s+district\b[^.!?]*|\bschool\s+ratings?\b[^.!?]*|"
        # Quality claims about schools are the steering signal, not the school name.
        r"\b(?:top|highly|well|a)[-\s]rated\s+schools?\b[^.!?]*|"
        r"\b(?:excellent|great|best|good|desirable)\s+schools?\b[^.!?]*|"
        r"\bschool\s+zone[sd]?\b[^.!?]*", re.I)),

    # Religion. Carve-out below keeps street names ("Church Street", "Temple Terrace").
    ("religion", re.compile(
        r"\b(?:church|christian|catholic|synagogue|temple|mosque|parish|congregation)\b", re.I)),

    # Disability / physical ability requirements.
    ("disability", re.compile(
        r"\bable[-\s]bodied\b|\bmust\s+be\s+able\s+to\s+(?:walk|climb|carry)|"
        r"\bno\s+wheelchair|\bnot\s+(?:handicap|wheelchair)[-\s]accessible|"
        r"\bwalk[-\s]?up\s+only\b|\bno\s+(?:service|emotional\s+support)\s+animal", re.I)),

    # National origin / race / ethnicity proxies.
    ("national_origin", re.compile(
        r"\benglish[-\s]speaking\b|\bmust\s+speak\b|\b(?:americans?|nationals?)\s+only\b|"
        r"\bintegrated\s+(?:neighborhood|community)\b|\btraditional\s+neighborhood\b", re.I)),

    # Source of income (protected in a growing number of FL/VA jurisdictions).
    ("source_of_income", re.compile(
        r"\bno\s+(?:section\s*8|housing\s+vouchers?|hud)\b|\bsection\s*8\s+not\s+accepted\b|"
        r"\bno\s+government\s+(?:assistance|subsid)", re.I)),
]

# Benign phrases that trip a HARD pattern. Checked against the matched sentence.
CARVE_OUTS = re.compile(
    r"church\s+st|church\s+street|church\s+ave|temple\s+ter|temple\s+terrace|"
    r"christian\s+(?:st|street|ave|dr)|\bchurch\s+and\s+(?:main|orange)",
    re.I)

# --------------------------------------------------------------------------
# SOFT - mechanically fixable. Rewritten in place, no review needed.
# --------------------------------------------------------------------------
# AppFolio copy uses the typographic apostrophe (U+2019) far more often than the
# ASCII one, so every contraction pattern has to accept both. "Don\u2019t miss the
# opportunity..." sailed straight through a `don'?t` pattern.
AP = r"['\u2019\u02bc`]?"

PHONE = re.compile(r"\(?\b\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b")
EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
URL = re.compile(r"\b(?:https?://|www\.)\S+", re.I)

# Time-sensitive claims that are false the moment the unit leases.
STALE = re.compile(
    r"\bavailable\s+(?:now|immediately)\b!*|\bmove[-\s]in\s+ready\s+today\b|"
    # "call today", but also "call to schedule", "call for a showing", "call us"
    r"\bcall\s+(?:today|now|us|to|for|or|at)\b[^.!?]*|"
    # "please call 813-555-1234 or text ..." - scrubbing just the number left
    # behind "please call or to." on a run-on sentence with no full stop.
    r"\bplease\s+call\b[^.!?]*|\b(?:call|text)\s+or\s+(?:text|call)\b[^.!?]*|"
    r"\bwon" + AP + r"t\s+last\b!*|\bhurry\b!*|\bact\s+fast\b!*|"
    # "schedule your private viewing/appointment", not just showing/tour
    r"\bschedule\s+(?:your|a)\s+(?:private\s+)?(?:showing|tour|viewing|appointment|visit)\b[^.!?]*|"
    r"\bapply\s+(?:today|now)\b[^.!?]*|\bcontact\s+us\s+(?:today|now)\b[^.!?]*|"
    # "don't miss the opportunity" / "don't wait" - the old copy is full of these
    r"\bdon" + AP + r"t\s+(?:miss|wait|delay|hesitate)\b[^.!?]*|"
    r"\bthis\s+one\s+won" + AP + r"t\b[^.!?]*|\bbook\s+(?:your|a)\s+(?:showing|tour|viewing)\b[^.!?]*",
    re.I)

# --------------------------------------------------------------------------
# BRAND - words the Atrium brand spec bans outright: "cheap / affordable /
# budget / low-cost". Atrium positions as a boutique, tailored operator, and
# price-first language undercuts that. These are removed as WORDS, not by
# dropping the sentence, because they are almost always a stray adjective in an
# otherwise useful description ("this affordable 3-bedroom home features...").
# --------------------------------------------------------------------------
BRAND_BANNED = re.compile(
    r"\b(?:cheap(?:est|ly)?|affordabl[ey]|affordability|budget[-\s]friendly|"
    r"low[-\s]cost|lowest[-\s]priced?|bargain|economical|inexpensive)\b", re.I)

# "Affordable Housing" is a regulatory term (LIHTC, Section 8, income-restricted
# programs), not marketing puffery. Stripping it would change what the listing
# legally says about the unit, so the whole sentence is left alone when the word
# appears in that sense.
AFFORDABLE_PROGRAM = re.compile(
    r"\baffordable\s+(?:housing|units?|communit|program|apartments?)|"
    r"\bincome[-\s]restricted\b|\bsection\s*8\b|\blihtc\b|\btax\s+credit\b", re.I)

# Removing an adjective can strand the wrong article: "an affordable home" would
# otherwise become "an home".
_ARTICLE = re.compile(r"\b([Aa])n?\b(\s+)(\w)")


def _fix_articles(text):
    def swap(m):
        art, gap, nxt = m.groups()
        correct = "an" if nxt.lower() in "aeiou" else "a"
        return (correct.capitalize() if art.isupper() else correct) + gap + nxt
    return _ARTICLE.sub(swap, text)


def _strip_banned(sent):
    """
    Remove a banned word and repair what its absence breaks.

    Deleting a word out of a sentence is not just a substitution - it strands
    punctuation and capitals. "An affordable, updated home" became "An, updated
    home", and "Cheap rent and a great location!" became lowercase "rent and...".
    """
    # A conjunction has to leave with the word it joined, or "comfortably and
    # affordably with apartments" becomes "comfortably and with apartments".
    out = re.sub(r"\s+(?:and|or)\s+" + BRAND_BANNED.pattern + r"\b", "", sent, flags=re.I)
    out = re.sub(BRAND_BANNED.pattern + r"\s+(?:and|or)\s+", " ", out, flags=re.I)
    # Take an adjective's trailing comma with it, so a list like
    # "affordable, updated" closes up instead of leaving a dangling comma.
    out = re.sub(BRAND_BANNED.pattern + r"\s*,\s*", " ", out, flags=re.I)
    out = BRAND_BANNED.sub("", out)
    out = re.sub(r"\s*,\s*,", ",", out)
    out = re.sub(r"\b(An?|The)\s*,\s*", r"\1 ", out, flags=re.I)
    out = _fix_articles(_tidy(out))
    # Re-capitalise if the removed word had been the first word.
    for i, ch in enumerate(out):
        if ch.isalpha():
            return out[:i] + ch.upper() + out[i + 1:]
    return out


SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _sentences(text):
    """Split into sentences, tolerating the \\r\\n soup AppFolio stores."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{2,}", "\n\n", text)
    parts = []
    for block in text.split("\n\n"):
        block = re.sub(r"\s*\n\s*", " ", block).strip()
        if block:
            parts.append([s.strip() for s in SENTENCE_SPLIT.split(block) if s.strip()])
    return parts


def sanitize(text, listing_id="", address=""):
    """
    Returns (clean_text, findings) where findings is a list of
    {severity, category, snippet}. clean_text is always safe to publish;
    HARD findings additionally mean a human should look at it.
    """
    findings = []
    if not text or not text.strip():
        return "", findings

    blocks = _sentences(text)
    kept_blocks = []

    for block in blocks:
        kept = []
        for sent in block:
            # --- HARD: protected-class language. Drop sentence + flag. ---
            hard_hit = None
            for category, pattern in HARD:
                if not pattern.search(sent):
                    continue
                # Street names etc. shouldn't cost us a sentence.
                if category == "religion" and CARVE_OUTS.search(sent):
                    continue
                hard_hit = category
                break
            if hard_hit:
                findings.append({"severity": "HARD", "category": hard_hit, "snippet": sent[:220]})
                continue

            # --- BRAND: banned price-first vocabulary. ---
            # Word-level removal, not a sentence drop: the ban is on the word,
            # and the rest of the sentence is usually worth keeping.
            if BRAND_BANNED.search(sent) and not AFFORDABLE_PROGRAM.search(sent):
                findings.append({"severity": "BRAND", "category": "banned_word",
                                 "snippet": sent[:220]})
                cleaned = _strip_banned(sent)
                # "Discover affordable luxury and unbeatable value." survives as a
                # real sentence; something that was only the banned claim does not.
                if len(cleaned.strip(" .,!?-")) < 12:
                    continue
                sent = cleaned

            # --- SOFT: contact details and time-sensitive claims. ---
            # These live in pure call-to-action sentences ("Please call 407-585-2721
            # to schedule your private showing."). Scrubbing them inline leaves
            # "Please call to." - so drop the whole sentence instead, and only fall
            # back to inline scrubbing when the sentence also carries real
            # description we'd lose.
            soft_cats = [
                label for label, pat in
                (("phone", PHONE), ("email", EMAIL), ("url", URL), ("stale_claim", STALE))
                if pat.search(sent)
            ]
            if soft_cats:
                findings.append({
                    "severity": "SOFT",
                    "category": "+".join(soft_cats),
                    "snippet": sent[:220],
                })
                stripped = STALE.sub("", URL.sub("", EMAIL.sub("", PHONE.sub("", sent))))
                stripped = _tidy(stripped)
                # What survives has to be a real clause, not connective debris.
                if len(stripped.strip(" .,!?-")) < 30 or _is_cta(stripped):
                    continue
                # Cutting a trailing clause leaves a dangling comma or conjunction
                # ("Professionally managed by Atrium Management,"). Close it cleanly.
                # Drop the orphaned terminator first ("Management,!"), then the
                # dangling comma/conjunction, then close the sentence properly.
                stripped = re.sub(r"[\s.!?]+$", "", stripped)
                stripped = re.sub(r"[\s,;:\-–—]*(?:\b(?:and|or|with|plus)\b)?[\s,;:\-–—]*$",
                                  "", stripped)
                if not stripped:
                    continue
                stripped += "."
                sent = stripped
            kept.append(sent)
        if kept:
            kept_blocks.append(kept)

    out = "\n\n".join(" ".join(b) for b in kept_blocks)
    return _tidy(out), findings


# Sentences that exist only to tell the reader to get in touch. After the phone
# number is stripped these are noise, and on a leased page they're actively wrong.
_CTA = re.compile(
    r"^\s*(?:please\s+)?(?:call|contact|email|text|visit|apply|schedule|book|tour|see|come|stop by|"
    r"reach out|inquire|message|ask)\b", re.I)


def _is_cta(sent):
    return bool(_CTA.match(sent.strip()))


def _tidy(out):
    """Clean up the punctuation wreckage substitutions leave behind."""
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+([.,!?;:])", r"\1", out)
    out = re.sub(r"([.!?])\1{1,}", r"\1", out)         # "NOW!!!" -> "NOW!"
    out = re.sub(r"(?:^|(?<=[.!?]))\s*[.,;:]+", " ", out)
    out = re.sub(r"\(\s*\)|\[\s*\]", "", out)
    out = re.sub(r"\s+,", ",", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"^[\s\-–—,.;:]+", "", out, flags=re.M)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


class ReviewLog:
    """Collects findings across a build and writes review/flagged.csv."""

    def __init__(self):
        self.rows = []
        self.hard_ids = set()

    def add(self, listing_id, address, city, findings, published_url=""):
        for f in findings:
            self.rows.append({
                "severity": f["severity"],
                "category": f["category"],
                "address": address,
                "city": city,
                "listing_id": listing_id,
                "page": published_url,
                "snippet": f["snippet"],
            })
            if f["severity"] == "HARD":
                self.hard_ids.add(listing_id)

    def write(self, path=None):
        path = Path(path or HERE / "review" / "flagged.csv")
        path.parent.mkdir(parents=True, exist_ok=True)
        cols = ["severity", "category", "address", "city", "listing_id", "page", "snippet"]
        rows = sorted(self.rows, key=lambda r: (r["severity"] != "HARD", r["category"], r["address"]))
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        return path

    def summary(self):
        """(hard, soft, brand, n_listings_with_hard_findings)"""
        from collections import Counter
        hard = Counter(r["category"] for r in self.rows if r["severity"] == "HARD")
        soft = Counter(r["category"] for r in self.rows if r["severity"] == "SOFT")
        brand = Counter(r["category"] for r in self.rows if r["severity"] == "BRAND")
        return hard, soft, brand, len(self.hard_ids)


if __name__ == "__main__":
    demo = ("Beautiful 4 Bed 2.5 Bath Town Home! Perfect for family living and hosting friends. "
            "Zoned for Region 1 Elementary School, Sanford Middle School. "
            "Please call 407-585-2721 to schedule your private showing. AVAILABLE NOW!!!")
    clean, found = sanitize(demo)
    print("BEFORE:\n", demo, "\n")
    print("AFTER:\n", clean, "\n")
    for f in found:
        print(f" {f['severity']:5} {f['category']:16} {f['snippet'][:80]}")
