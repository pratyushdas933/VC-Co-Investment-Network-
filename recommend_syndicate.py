"""
Stage 4 — Syndicate Recommendation Tool.

Given a lead investor (and optionally a sector), recommends other
investors likely to join the syndicate — combining:
  1. Direct co-investment history (have they backed deals together before?)
  2. Adamic-Adar shared-neighbor score (structurally similar investors,
     even without direct history — same signal as build_graph.py's link
     prediction, but queryable per-investor instead of a global top-20 list)
  3. Same-community bonus (Louvain cluster membership)
  4. Sector affinity (has the candidate invested in this sector before?)

Sector tagging: the source data has no explicit sector field, so this
script tags each deal with a lightweight keyword-based sector guess
from its source_sentence. This is a heuristic, not ground truth — good
enough for recommendation weighting, not for precise classification.

Usage:
    python recommend_syndicate.py funding_deals_clean.json \\
        --investor "Nexus Venture Partners" --sector fintech

    python recommend_syndicate.py funding_deals_clean.json \\
        --company "Runable"     # infers lead investor + sector from
                                 # that company's own deal record
"""
import argparse
import json
import re
from collections import defaultdict
from itertools import combinations

import networkx as nx

SECTOR_KEYWORDS = {
    "fintech": ["fintech", "lending", "wealth management", "insurance", "payments", "neobank", "credit"],
    "saas": ["saas", "software", "enterprise ai", "b2b platform"],
    "healthtech": ["healthtech", "health", "medtech", "diagnostics", "pharma", "wellness"],
    "edtech": ["edtech", "education", "learning platform"],
    "agritech": ["agritech", "farm produce", "agriculture"],
    "logistics_mobility": ["logistics", "mobility", "electric motorcycle", "electric vehicle", "delivery", "ev "],
    "aerospace_deeptech": ["aerospace", "deeptech", "space", "drone", "robotics", "semiconductor"],
    "consumer_d2c": ["d2c", "direct-to-consumer", "beauty", "skincare", "fashion", "consumer brand"],
    "foodtech": ["foodtech", "coffee chain", "restaurant", "cloud kitchen", "food delivery"],
    "cleantech_climate": ["cleantech", "climate", "solar", "renewable", "sustainability"],
    "proptech": ["proptech", "real estate", "home improvement", "housing finance"],
    "media_gaming": ["gaming", "media platform", "content platform", "entertainment"],
    "ai": ["ai services", "agentic ai", "artificial intelligence", "ai infrastructure", "ai marketing"],
}


def tag_sector(sentence):
    s = sentence.lower()
    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(kw in s for kw in keywords):
            return sector
    return "other"


def load_deals(path):
    with open(path, encoding="utf-8") as f:
        deals = json.load(f)
    for d in deals:
        d["sector"] = tag_sector(d.get("source_sentence", ""))
    return deals


def build_graph_and_index(deals):
    """Returns (co_graph, investor_sectors, company_to_deal)."""
    co_graph = nx.Graph()
    pair_counts = defaultdict(int)
    investor_sectors = defaultdict(lambda: defaultdict(int))  # investor -> {sector: count}
    company_to_deal = {}

    for deal in deals:
        investors = list(dict.fromkeys(
            deal.get("lead_investors", []) + deal.get("participating_investors", [])
        ))
        if not investors:
            continue
        company_to_deal[deal["company"]] = deal

        for inv in investors:
            co_graph.add_node(inv)
            investor_sectors[inv][deal["sector"]] += 1

        for a, b in combinations(sorted(investors), 2):
            pair_counts[(a, b)] += 1

    for (a, b), weight in pair_counts.items():
        co_graph.add_edge(a, b, weight=weight)

    return co_graph, investor_sectors, company_to_deal


def recommend(co_graph, investor_sectors, communities, lead_investor, sector=None, top_n=10,
              weights=(0.35, 0.35, 0.15, 0.15)):
    """
    weights = (direct_history, adamic_adar, same_community, sector_affinity)
    Each component is normalized to 0-1 before weighting, so the final
    score is roughly comparable across candidates.
    """
    w_direct, w_aa, w_comm, w_sector = weights

    if lead_investor not in co_graph:
        return None, f"'{lead_investor}' not found in the investor graph (no recorded deals)."

    candidates = [n for n in co_graph.nodes() if n != lead_investor]

    # 1. direct co-investment weight (already an edge weight, if it exists)
    direct = {c: co_graph[lead_investor][c]["weight"] if co_graph.has_edge(lead_investor, c) else 0
              for c in candidates}
    max_direct = max(direct.values()) or 1

    # 2. Adamic-Adar for non-connected pairs (0 if already connected, since
    #    direct history already captures that signal)
    aa_scores = {c: 0.0 for c in candidates}
    non_edges = [(lead_investor, c) for c in candidates if not co_graph.has_edge(lead_investor, c)]
    if non_edges:
        for u, v, score in nx.adamic_adar_index(co_graph, non_edges):
            other = v if u == lead_investor else u
            aa_scores[other] = score
    max_aa = max(aa_scores.values()) or 1

    # 3. same community bonus
    lead_comm = communities.get(lead_investor)
    same_comm = {c: 1.0 if communities.get(c) == lead_comm else 0.0 for c in candidates}

    # 4. sector affinity — how much of the candidate's activity is in this sector
    sector_aff = {c: 0.0 for c in candidates}
    if sector:
        for c in candidates:
            counts = investor_sectors.get(c, {})
            total = sum(counts.values()) or 1
            sector_aff[c] = counts.get(sector, 0) / total

    scored = []
    for c in candidates:
        score = (
            w_direct * (direct[c] / max_direct)
            + w_aa * (aa_scores[c] / max_aa)
            + w_comm * same_comm[c]
            + w_sector * sector_aff[c]
        )
        if score > 0:
            scored.append({
                "investor": c,
                "score": round(score, 4),
                "direct_deals_with_lead": direct[c],
                "adamic_adar": round(aa_scores[c], 3),
                "same_community": bool(same_comm[c]),
                "sector_deal_share": round(sector_aff[c], 2) if sector else None,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n], None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("deals_file")
    parser.add_argument("--investor", help="lead investor to build a syndicate around")
    parser.add_argument("--sector", help="target sector (e.g. fintech, saas, healthtech) — optional")
    parser.add_argument("--company", help="instead of --investor, infer lead investor + sector from an existing company's deal record")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    deals = load_deals(args.deals_file)
    co_graph, investor_sectors, company_to_deal = build_graph_and_index(deals)

    # Louvain community detection (same as build_graph.py) so results are
    # consistent with the dashboard's community coloring
    import community as community_louvain
    communities = community_louvain.best_partition(co_graph, weight="weight") if co_graph.number_of_edges() else {}

    lead_investor, sector = args.investor, args.sector

    if args.company:
        deal = company_to_deal.get(args.company)
        if not deal:
            print(f"Company '{args.company}' not found in dataset.")
            print("Available companies:", ", ".join(sorted(company_to_deal.keys())[:20]), "...")
            return
        leads = deal.get("lead_investors") or deal.get("participating_investors")
        if not leads:
            print(f"No investor recorded for '{args.company}'.")
            return
        lead_investor = leads[0]
        sector = deal["sector"]
        print(f"Company: {args.company}")
        print(f"  Inferred lead investor: {lead_investor}")
        print(f"  Inferred sector: {sector}\n")

    if not lead_investor:
        print("Provide --investor NAME or --company NAME. Example:")
        print(f'  python {sys.argv[0]} funding_deals_clean.json --investor "Nexus Venture Partners" --sector fintech')
        return

    results, error = recommend(co_graph, investor_sectors, communities, lead_investor, sector, top_n=args.top)
    if error:
        print(error)
        print("\nInvestors available in this dataset (sample):")
        print(", ".join(sorted(co_graph.nodes())[:25]), "...")
        return

    print(f"Syndicate recommendations for lead investor: {lead_investor}"
          + (f" (sector: {sector})" if sector else ""))
    print("-" * 78)
    print(f"{'Investor':<32}{'Score':>8}{'Prior deals':>13}{'Shared-nbr':>12}{'Same cluster':>14}")
    print("-" * 78)
    for r in results:
        print(f"{r['investor']:<32}{r['score']:>8.3f}{r['direct_deals_with_lead']:>13}"
              f"{r['adamic_adar']:>12.3f}{str(r['same_community']):>14}")


if __name__ == "__main__":
    import sys
    main()
