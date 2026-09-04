"""
Entrackr Weekly Funding Report scraper.

Run this LOCALLY (not in a sandboxed environment) — it needs open
internet access to entrackr.com.

What it does:
  1. Crawls the paginated "Weekly Funding Report" archive to collect
     article URLs.
  2. Fetches each report article and extracts the main body text.
  3. Runs the body text through the same deal-extraction logic
     prototyped in extractor.py (rule-based + spaCy NER).
  4. Saves everything incrementally to funding_deals.json, so you can
     stop/resume without losing progress.

Setup:
    pip install requests beautifulsoup4 spacy tqdm
    python -m spacy download en_core_web_sm

Usage:
    python scrape_entrackr.py --pages 5
    (each listing page has ~10 reports; start small, e.g. --pages 3,
     to sanity check before doing a big run)

Politeness:
  - Sends a real User-Agent and rate-limits requests (default 2s
    between calls) — do not remove this; hammering a small news site
    is bad practice and will get you IP-blocked anyway.
  - Respects a --max-articles cap so you don't accidentally scrape
    the entire multi-year archive on a first run.
"""

import argparse
import json
import re
import time
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import spacy

BASE = "https://entrackr.com"
LISTING_URL = "https://entrackr.com/report/weekly-funding-report"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
OUTFILE = Path("funding_deals.json")
SEEN_URLS_FILE = Path("seen_urls.json")

RATE_LIMIT_SECONDS = 2.0

nlp = spacy.load("en_core_web_sm")

# ---------------- extraction logic (same as extractor.py prototype) ----------------

ROUND_PATTERNS = [
    r"Series [A-F]", r"Pre-[Ss]eries [A-F]", r"[Ss]eed round", r"[Pp]re-seed",
    r"maiden funding round", r"growth equity", r"debt round", r"bridge round",
]
ROUND_RE = re.compile(r"(" + "|".join(ROUND_PATTERNS) + r")")
AMOUNT_RE = re.compile(r"\$([\d,.]+)\s*(million|billion|Mn|Bn)", re.IGNORECASE)
LED_BY_RE = re.compile(r"(?:led|co-led)\s+by\s+([^.]+?)(?:,?\s+with participation from ([^.]+))?\.")
PARTICIPATION_RE = re.compile(r"with participation from ([^.]+)\.")
FROM_INVESTORS_RE = re.compile(r"from (?:existing investors,?\s*)?including ([^.]+)\.")
AGGREGATE_SENTENCE_RE = re.compile(
    r"^\s*(this week|in contrast|on a weekly basis|the average weekly|"
    r"growth[- ]stage startups|early[- ]stage startups)", re.IGNORECASE
)
AGGREGATE_COUNT_RE = re.compile(
    r"(\d+\s+(Indian\s+)?startups\s+(raised|secured|collectively)|"
    r"startups\s+(raised|saw)\s+(a\s+total\s+of|just))", re.IGNORECASE
)


def split_investor_list(raw):
    if not raw:
        return []
    raw = raw.strip().rstrip(".")
    raw = re.sub(r"\s+and\s+", ", ", raw)
    parts = [p.strip() for p in raw.split(",")]
    parts = [p for p in parts if p and not p.lower().startswith("its founders")]
    cleaned = []
    for p in parts:
        p = re.sub(r"^(existing investor[s]?|new investor[s]?)\s+", "", p, flags=re.IGNORECASE)
        cleaned.append(p.strip().rstrip("."))
    return cleaned


def split_compound_sentences(text):
    """Entrackr often joins two independent deal mentions with ', while ' —
    e.g. 'X raised $5M led by A, while Y raised $3M led by B.' Treating
    that as one sentence causes B's clause to bleed into A's investor
    list. Split on ', while ' (capitalized clause follows) into two
    separate pseudo-sentences before spaCy sentence segmentation."""
    return re.sub(r",\s+while\s+([A-Z])", r". \1", text)


def is_fragment(s):
    """Heuristic filter for extraction noise: a clause fragment that
    leaked into a company/investor field instead of a clean name."""
    if not s:
        return True
    if len(s) > 55:
        return True
    if re.search(r"\b(which|while|raised|secured|led by|round|funding|turning|backed)\b", s, re.IGNORECASE):
        return True
    if s[:1].islower():
        return True
    return False


def extract_deals(text, source_url=None, published_date=None):
    text = split_compound_sentences(text)
    doc = nlp(text)
    deals = []

    for sent in doc.sents:
        s = sent.text.strip()
        if not s or "$" not in s:
            continue
        if not any(w in s for w in ["raised", "secured", "round"]):
            continue
        if AGGREGATE_SENTENCE_RE.search(s) or AGGREGATE_COUNT_RE.search(s):
            # skip weekly/aggregate summary sentences — not a single deal
            continue

        amount_match = AMOUNT_RE.search(s)
        round_match = ROUND_RE.search(s)
        if not (amount_match or round_match):
            continue

        sent_doc = nlp(s)
        orgs = [ent.text for ent in sent_doc.ents if ent.label_ == "ORG"]

        verb_hits = [s.find(v) for v in ["raised", "secured", "led the funding"] if v in s]
        verb_hits = [v for v in verb_hits if v != -1]
        verb_pos = min(verb_hits) if verb_hits else len(s)
        pre_verb_text = s[:verb_pos]
        pre_verb_text = re.sub(
            r"^[A-Za-z\s]*-based\s+[a-z][a-zA-Z\s]*?\s+(?=[A-Z])", "", pre_verb_text.strip()
        )
        company_match = re.search(
            r"([A-Z][A-Za-z0-9&.\-]*(?:\s+[A-Z][A-Za-z0-9&.\-]*)*)\s*$", pre_verb_text.strip()
        )
        company = company_match.group(1).strip().rstrip(".") if company_match else (orgs[0] if orgs else None)
        if not company or is_fragment(company):
            continue

        lead_investors, participating_investors = [], []
        led_match = LED_BY_RE.search(s)
        if led_match:
            lead_investors = split_investor_list(led_match.group(1))
            if led_match.group(2):
                participating_investors = split_investor_list(led_match.group(2))
        else:
            part_match = PARTICIPATION_RE.search(s)
            if part_match:
                participating_investors = split_investor_list(part_match.group(1))
            from_match = FROM_INVESTORS_RE.search(s)
            if from_match:
                participating_investors = split_investor_list(from_match.group(1))

        lead_investors = [i for i in lead_investors if not is_fragment(i)]
        participating_investors = [i for i in participating_investors if not is_fragment(i)]

        amt = None
        if amount_match:
            val = float(amount_match.group(1).replace(",", ""))
            unit = amount_match.group(2).lower()
            amt = val * 1000 if unit in ("billion", "bn") else val

        deals.append({
            "company": company,
            "amount_usd_million": amt,
            "round_type": round_match.group(1) if round_match else None,
            "lead_investors": lead_investors,
            "participating_investors": participating_investors,
            "source_sentence": s,
            "source_url": source_url,
            "published_date": published_date,
        })

    return deals


# ---------------- scraping ----------------

def get(url, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                return resp
            print(f"  [warn] status {resp.status_code} for {url}")
        except requests.RequestException as e:
            print(f"  [warn] request failed ({e}) attempt {attempt+1}/{retries}")
        time.sleep(RATE_LIMIT_SECONDS * (attempt + 1))
    return None


def collect_report_urls(max_pages):
    """Walk the paginated Weekly Funding Report listing and collect article URLs."""
    urls = []
    for page in range(1, max_pages + 1):
        page_url = LISTING_URL if page == 1 else f"{LISTING_URL}?page={page}"
        print(f"Listing page {page}: {page_url}")
        resp = get(page_url)
        if resp is None:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        # article links live under /report/weekly-funding-report/<slug>
        for a in soup.select("a[href*='/report/weekly-funding-report/']"):
            href = a.get("href", "")
            if href and href not in urls and "/weekly-funding-report/" in href:
                full = href if href.startswith("http") else BASE + href
                if full not in urls:
                    urls.append(full)
        time.sleep(RATE_LIMIT_SECONDS)
    return urls


def extract_article_body(html, debug=False):
    """Pull the main article text and published date from a report page.

    Entrackr runs on a CMS (Publive) whose container class names are not
    reliable to guess blind, so instead of trusting one CSS selector we:
      1. Grab every <p> tag on the page (broad net).
      2. Drop known boilerplate lines (nav, footer, subscribe prompts,
         social share links, disclaimer, etc.) by pattern match.
      3. Keep only the paragraphs between the H1 title and the
         "Disclaimer:" marker that ends every article body.
    This is slower per-page but far more resilient to markup changes
    than a guessed container selector.
    """
    soup = BeautifulSoup(html, "html.parser")

    if debug:
        Path("debug_last_page.html").write_text(html, encoding="utf-8")
        print(f"  [debug] dumped raw HTML to debug_last_page.html "
              f"({len(soup.find_all('p'))} <p> tags found on page)")

    BOILERPLATE_SNIPPETS = [
        "subscribe to our newsletter", "subscribe now", "quick links",
        "all rights reserved", "you have successfully subscribed",
        "read the next article", "related articles", "latest stories",
        "about us", "terms of use", "privacy policy", "min read",
        "entrackr is a new age media platform", "follow us",
    ]

    def is_boilerplate(text):
        t = text.strip().lower()
        if not t:
            return True
        if re.fullmatch(r"\d+", t.strip()):
            # bare counters/badges (e.g. the "0" notification badge)
            return True
        if len(t) < 25 and not re.search(r"\d", t):
            # short nav-link-like fragments (menu items etc.)
            return True
        if re.match(r"^by\s+[A-Z]", text.strip()) or re.match(r"^[A-Z][a-z]+\s+[A-Z][a-z]+(\s*&\s*[A-Z][a-z]+\s+[A-Z][a-z]+)?$", text.strip()):
            # byline patterns: "By X Y" or bare "X Y" / "X Y & A B" author names
            return True
        if re.match(r"^\d{1,2}\s+\w+\s+\d{4}\s+\d{2}:\d{2}\s+IST", text.strip()):
            # publish-date/time line
            return True
        return any(snippet in t for snippet in BOILERPLATE_SNIPPETS)

    all_paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    # also capture bullet-style lines the reports use (▪️ ...) which may
    # sit in <li> or <div> rather than <p>
    all_paragraphs += [
        li.get_text(" ", strip=True) for li in soup.find_all("li")
        if "▪" in li.get_text()
    ]

    body_lines = [p for p in all_paragraphs if not is_boilerplate(p)]

    # cut off at the disclaimer boilerplate paragraph if present (it's
    # sometimes long enough to survive the length filter above)
    for i, line in enumerate(body_lines):
        if line.lower().startswith("disclaimer") or "bareback media has recently raised funding" in line.lower():
            body_lines = body_lines[:i]
            break

    text = "\n".join(body_lines)

    date = None
    date_tag = soup.find("meta", {"property": "article:published_time"})
    if date_tag:
        date = date_tag.get("content")

    return text, date


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", type=int, default=3, help="listing pages to crawl (~10 reports/page)")
    parser.add_argument("--max-articles", type=int, default=30, help="hard cap on articles fetched this run")
    parser.add_argument("--debug", action="store_true", help="dump raw HTML of each page fetched, for selector debugging")
    args = parser.parse_args()

    all_deals = load_json(OUTFILE, [])
    seen_urls = set(load_json(SEEN_URLS_FILE, []))

    print("Collecting report URLs...")
    report_urls = collect_report_urls(args.pages)
    new_urls = [u for u in report_urls if u not in seen_urls][: args.max_articles]
    print(f"Found {len(report_urls)} total, {len(new_urls)} new to fetch this run.")

    for i, url in enumerate(new_urls, 1):
        print(f"[{i}/{len(new_urls)}] {url}")
        resp = get(url)
        if resp is None:
            continue
        text, date = extract_article_body(resp.text, debug=args.debug)
        if not text or len(text) < 200:
            print(f"  [warn] article body too short/empty (got {len(text) if text else 0} chars), skipping")
            if not args.debug:
                print("  [hint] re-run with --debug on a small batch to inspect why")
            continue

        deals = extract_deals(text, source_url=url, published_date=date)
        print(f"  -> extracted {len(deals)} deal records")
        all_deals.extend(deals)
        seen_urls.add(url)

        # save incrementally so a crash/interrupt doesn't lose progress
        save_json(OUTFILE, all_deals)
        save_json(SEEN_URLS_FILE, list(seen_urls))

        time.sleep(RATE_LIMIT_SECONDS)

    print(f"\nDone. Total deal records collected so far: {len(all_deals)}")
    print(f"Saved to {OUTFILE.resolve()}")


if __name__ == "__main__":
    main()
