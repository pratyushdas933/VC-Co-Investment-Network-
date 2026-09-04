# VC Co-Investment Network Intelligence

A graph-based analytics platform that scrapes real Indian startup funding
news, builds an investor co-investment network, and uses network science
(centrality, community detection, link prediction) to answer questions a
static spreadsheet can't: who are the real power players in a given
sector, which investor cliques move together, and who's likely to
co-invest next — plus a syndicate recommendation tool that suggests
co-investors for a given lead investor or company.

<img width="1072" height="637" alt="Screenshot 2026-09-03 231051" src="https://github.com/user-attachments/assets/638e8d56-ada9-47ed-b32e-bb6ca402b9e0" />
<img width="1092" height="776" alt="Screenshot 2026-09-03 231044" src="https://github.com/user-attachments/assets/50087c7a-cf6c-4d54-b3dc-637535384a7f" />
<img width="1124" height="841" alt="Screenshot 2026-09-03 231036" src="https://github.com/user-attachments/assets/43164d7b-7109-4bbd-bb0b-4f70a8648c5f" />


Built as a portfolio project for VC/startup-advisory AI/BI work — the
kind of tool a due-diligence or transaction-advisory team would use to
understand investor relationships at a glance, rather than piecing it
together deal-by-deal.

## Pipeline

Each stage's output feeds the next. Run them in order (or just the
later stages if you already have the earlier files).

```
scrape_entrackr.py  →  clean_deals.py  →  build_graph.py  →  build_dashboard.py
                                                            →  recommend_syndicate.py
```

| Script | Input | Output | What it does |
|---|---|---|---|
| `scrape_entrackr.py` | — (crawls the web) | `funding_deals.json`, `seen_urls.json` | Crawls Entrackr's Weekly Funding Report archive, extracts deal mentions (company, amount, round, investors) from article prose using regex + spaCy NER |
| `clean_deals.py` | `funding_deals.json` | `funding_deals_clean.json` | Retroactively filters extraction noise (clause fragments, pronoun leaks, currency artifacts, generic category words misread as company names) without needing to re-scrape |
| `build_graph.py` | `funding_deals_clean.json` | `graph_data.json`, `investor_graph.graphml` | Builds the investor co-investment graph (NetworkX), computes degree/betweenness/eigenvector/PageRank centrality, runs Louvain community detection, scores Adamic-Adar link predictions |
| `build_dashboard.py` | `graph_data.json` | `network_dashboard.html` | Renders a self-contained, dark-themed interactive dashboard (Plotly force-directed graph + ranking tables) — no server needed, just open it in a browser |
| `recommend_syndicate.py` | `funding_deals_clean.json` | (CLI output) | Given a lead investor (or a company name to infer one from), recommends likely co-investors by blending direct co-investment history, shared-neighbor structure, community membership, and sector affinity |

## Setup

```bash
pip install requests beautifulsoup4 spacy networkx python-louvain
python -m spacy download en_core_web_sm
```

## Usage

```bash
# 1. Scrape (only needed to refresh/expand the dataset)
python scrape_entrackr.py --pages 8 --max-articles 60

# 2. Clean
python clean_deals.py funding_deals.json funding_deals_clean.json

# 3. Build the graph + run network analysis
python build_graph.py funding_deals_clean.json

# 4. Build the dashboard
python build_dashboard.py graph_data.json
# then open network_dashboard.html in a browser

# 5. Query syndicate recommendations
python recommend_syndicate.py funding_deals_clean.json --investor "Accel"
python recommend_syndicate.py funding_deals_clean.json --company "Airbound"
```

## Current dataset snapshot

- 352 raw deal mentions scraped → **197 clean records** after noise filtering
- **178 investors**, 101 co-investment edges, 107 detected communities, 142 companies
- Source: Entrackr Weekly Funding Report archive, ~8 months of coverage
- Spot-checked against independent sources (Tracxn, Wikipedia, company sites):
  top-ranked investors (Accel, GMO Venture Partners, InnoVen Capital,
  Rebright Partners, Mitsui Sumitomo Insurance VC, Lachy Groom) all
  confirmed real and active in this space — one even cross-verified down
  to the exact company and round (Lachy Groom's investment in Airbound)

## Known limitations (worth being upfront about)

- **Rule-based extraction, not perfect.** Around 44% of raw scraped
  records get dropped during cleaning — mostly aggregate "this week, N
  startups raised..." summary sentences and multi-company "roundup"
  sentences that don't cleanly parse into a single deal (e.g. "X led
  the pack with $Y from A, B, C, followed by W, Y, Z, among others" —
  ambiguous which investors belong to which company). This is a normal
  tradeoff for regex + NER extraction from prose (vs. a structured
  API); a more accurate but heavier alternative would be an LLM-based
  extraction pass.
- **One known company/investor role-swap bug** on a small number of
  compound sentences (e.g. "X, an on-demand goods transport agency,
  which raised $Y led by Z" can pick the wrong entity as the company).
  Affects roughly 0.5% of cleaned records — flagged rather than
  silently left in.
- **Community structure is currently thin** — with only ~8 months of
  weekly coverage, most investors appear in just one deal, so Louvain
  detects many small/singleton communities rather than a few large,
  meaningful clusters. This is a data-volume ceiling, not a bug —
  scraping a longer time span would densify it, since real syndicate
  patterns take months/years to repeat.
- **Sector tags are heuristic**, not ground truth — keyword-matched
  from each deal's source sentence (used by `recommend_syndicate.py`),
  not a verified industry classification.

## Tech stack

Python · spaCy (NER) · BeautifulSoup (scraping) · NetworkX (graph
construction + centrality) · python-louvain (community detection) ·
Plotly.js (dashboard visualization)
