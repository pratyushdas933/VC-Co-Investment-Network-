"""
One-time cleanup pass for funding_deals.json collected before the
extractor fixes (compound-sentence splitting, broadened aggregate
filtering, fragment detection).

Rather than re-scraping, this applies the same is_fragment() heuristic
retroactively:
  - Drops records where the company field is a clause fragment
    (aggregate lead-in sentences that slipped through, e.g. "AI",
    "Meta", "SoftBank" attached to garbled multi-clause sentences).
  - Strips fragment entries out of lead_investors/participating_investors
    lists (e.g. "which secured $32 million in a seed round led by
    Mayfield" showing up as an "investor").
  - Strips trailing periods from company names.

Usage:
    python clean_deals.py funding_deals.json funding_deals_clean.json
"""
import json
import re
import sys


GENERIC_COMPANY_BLOCKLIST = {
    "healthcare", "fintech", "saas", "startup", "startups", "growth",
    "early", "technology", "logistics", "unicorn", "ecommerce",
}


def is_fragment(s):
    if not s:
        return True
    if len(s) > 55:
        return True
    if re.search(r"\b(which|while|raised|led by|round|funding|turning|backed)\b", s, re.IGNORECASE):
        return True
    if re.search(r"\bsecur\w*\b", s, re.IGNORECASE):  # secured/securing/secures
        return True
    if s[:1].islower():
        return True
    if s[:1].isdigit() or s.startswith("$"):
        return True
    if "crore" in s.lower() or "\u25aa" in s:  # bullet char leaking from source list markup
        return True
    if re.search(r"\b(platform|startup|firm|cloud service|app|company)\b", s, re.IGNORECASE):
        # descriptor phrases from company mentions bleeding into investor fields
        # (e.g. "AI acceleration cloud platform Neysa") — real VC firm names don't
        # use these generic nouns
        return True
    if re.search(r"\b(himself|herself|itself|founder|co-founder|CEO)\b", s, re.IGNORECASE):
        # pronoun/role references bleeding in from sentences like "...founder
        # Goyal himself also participated" — not an investor entity
        return True
    return False


def is_company_fragment(s):
    """Lighter check for company names only — skips the lowercase-start
    rule, which wrongly flags legitimately-styled names like 'pi Ventures'
    (a real VC firm) or 'boAt' (a real brand)."""
    if not s:
        return True
    if len(s) > 55:
        return True
    if re.search(r"\b(which|while|raised|led by|round|funding|turning|backed)\b", s, re.IGNORECASE):
        return True
    if re.search(r"\bsecur\w*\b", s, re.IGNORECASE):
        return True
    if s[:1].isdigit() or s.startswith("$"):
        return True
    if "crore" in s.lower() or "\u25aa" in s:
        return True
    if s.strip().lower() in GENERIC_COMPANY_BLOCKLIST:
        # generic category words mistaken for a company name, e.g. "Healthcare"
        # from "Healthcare unicorn raised $275 million..."
        return True
    if re.search(r"'s\s+Rs$", s):
        # truncated possessive fragment, e.g. "Ayana Renewable's Rs"
        return True
    return False


# Recovers investor names from the common "raised $X from Investor[, Investor2
# and Investor3]" phrasing, which the original extractor didn't handle (it only
# caught "led by ..." and "... including ..." patterns). Applied retroactively
# against the stored source_sentence for records that came out with no investors.
FROM_SIMPLE_RE = re.compile(
    r"from\s+(?!existing investors|its founders)([A-Z][^.]+?)(?:\.|,?\s+with participation)", re.IGNORECASE
)


def recover_investors_from_sentence(sentence):
    m = FROM_SIMPLE_RE.search(sentence)
    if not m:
        return []
    raw = m.group(1).strip().rstrip(".")
    raw = re.sub(r"\s+and\s+", ", ", raw)
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p and not is_fragment(p)]


def clean_record(d):
    company = (d.get("company") or "").strip().rstrip(".")
    if is_company_fragment(company):
        return None

    lead = [i.strip().rstrip(".") for i in d.get("lead_investors", [])]
    part = [i.strip().rstrip(".") for i in d.get("participating_investors", [])]
    lead = [i for i in lead if not is_fragment(i)]
    part = [i for i in part if not is_fragment(i)]

    # attempt recovery for records that lost all investor info — the original
    # extractor missed the "raised $X from Investor" phrasing (no "led by")
    if not lead and not part:
        recovered = recover_investors_from_sentence(d.get("source_sentence", ""))
        if recovered:
            part = recovered

    # a record with zero investors and no round type carries no usable
    # signal for graph-building — usually a leftover from an aggregate
    # lead-in sentence where the company/amount matched but the investor
    # clause didn't parse (e.g. "SoftBank offloads $300 Mn stake" fell
    # through the amount/company regexes without being a real deal).
    if not lead and not part and not d.get("round_type"):
        return None

    # "roundup" sentences that name several unrelated companies in one
    # breath (e.g. "X led the pack with $Y from A, B, C, followed by
    # W, Y, Z, among others") can't be safely disambiguated by regex —
    # the investor list found may belong to a *different* company than
    # the one attached to it. Drop rather than risk a wrong attribution.
    src = (d.get("source_sentence") or "").lower()
    if "led the pack" in src or "among others" in src:
        return None

    out = dict(d)
    out["company"] = company
    out["lead_investors"] = lead
    out["participating_investors"] = part
    return out


def main():
    if len(sys.argv) != 3:
        print("Usage: python clean_deals.py funding_deals.json funding_deals_clean.json")
        sys.exit(1)

    infile, outfile = sys.argv[1], sys.argv[2]
    data = json.loads(open(infile, encoding="utf-8").read())

    cleaned = []
    dropped = 0
    for d in data:
        c = clean_record(d)
        if c is None:
            dropped += 1
            continue
        cleaned.append(c)

    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False)

    print(f"Input:   {len(data)} records")
    print(f"Dropped: {dropped} (unusable company field, or no investor/round info after recovery attempt)")
    print(f"Output:  {len(cleaned)} clean records -> {outfile}")

    # quick investor-list noise check on what remains
    still_noisy = sum(
        1 for d in cleaned
        if any(is_fragment(i) for i in d["lead_investors"] + d["participating_investors"])
    )
    print(f"(sanity check: {still_noisy} remaining records still show flagged investor names — should be 0)")


if __name__ == "__main__":
    main()
