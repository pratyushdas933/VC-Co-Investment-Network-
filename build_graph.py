"""
Stage 2 — Graph construction & network analysis.

Reads funding_deals_clean.json (output of clean_deals.py) and builds:
  1. Investor co-investment graph (investor <-> investor, edge weight =
     number of shared deals)
  2. Bipartite investor -> company graph (who invested in what)

Then runs:
  - Centrality: degree, betweenness, eigenvector/PageRank
  - Community detection: Louvain modularity clustering
  - Basic link-prediction scoring (Adamic-Adar) for the syndicate
    recommendation stage later

Outputs:
  - graph_data.json — a JSON contract (nodes, edges, communities,
    centrality scores) ready to feed a dashboard, matching the same
    pattern as your HR Leave Intelligence dashboard_data.json
  - investor_graph.graphml — the raw graph, importable into Gephi if
    you want to explore it visually outside this pipeline

Usage:
    pip install networkx python-louvain
    python build_graph.py funding_deals_clean.json
"""
import json
import sys
from collections import defaultdict
from itertools import combinations

import networkx as nx
import community as community_louvain  # python-louvain package


def load_deals(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_graphs(deals):
    """Returns (co_investment_graph, bipartite_graph, company_meta)."""
    co_graph = nx.Graph()
    bip_graph = nx.Graph()  # investor nodes + company nodes, edge = investment
    company_meta = {}

    # count shared deals per investor pair, and per-investor deal counts
    pair_counts = defaultdict(int)
    investor_deal_count = defaultdict(int)

    for deal in deals:
        company = deal["company"]
        investors = list(dict.fromkeys(  # dedupe, preserve order
            deal.get("lead_investors", []) + deal.get("participating_investors", [])
        ))
        if not investors:
            continue

        company_meta[company] = {
            "amount_usd_million": deal.get("amount_usd_million"),
            "round_type": deal.get("round_type"),
        }

        for inv in investors:
            bip_graph.add_node(inv, kind="investor")
            bip_graph.add_node(company, kind="company")
            bip_graph.add_edge(inv, company, role="lead" if inv in deal.get("lead_investors", []) else "participant")
            investor_deal_count[inv] += 1

        # every pair of investors in the same deal gets a co-investment edge
        for a, b in combinations(sorted(investors), 2):
            pair_counts[(a, b)] += 1

    for (a, b), weight in pair_counts.items():
        co_graph.add_edge(a, b, weight=weight)

    # make sure investors who only ever invested solo still appear as nodes
    for inv, count in investor_deal_count.items():
        if inv not in co_graph:
            co_graph.add_node(inv)
        co_graph.nodes[inv]["deal_count"] = count

    return co_graph, bip_graph, company_meta


def compute_centrality(co_graph):
    degree = dict(co_graph.degree())
    betweenness = nx.betweenness_centrality(co_graph, weight="weight")
    try:
        eigenvector = nx.eigenvector_centrality(co_graph, weight="weight", max_iter=1000)
    except nx.PowerIterationFailedConvergence:
        # falls back to PageRank if eigenvector doesn't converge (common on
        # graphs with disconnected components / bipartite-like structure)
        eigenvector = nx.pagerank(co_graph, weight="weight")
    pagerank = nx.pagerank(co_graph, weight="weight")
    return degree, betweenness, eigenvector, pagerank


def detect_communities(co_graph):
    if co_graph.number_of_edges() == 0:
        return {n: 0 for n in co_graph.nodes()}
    return community_louvain.best_partition(co_graph, weight="weight")


def top_adamic_adar_pairs(co_graph, top_n=20):
    """Link prediction: which non-connected investor pairs are most
    likely to co-invest next, based on shared-neighbor structure."""
    non_edges = list(nx.non_edges(co_graph))
    if not non_edges:
        return []
    scores = list(nx.adamic_adar_index(co_graph, non_edges))
    scores.sort(key=lambda x: x[2], reverse=True)
    return scores[:top_n]


def build_json_contract(co_graph, bip_graph, company_meta, degree, betweenness,
                         eigenvector, pagerank, communities, aa_pairs):
    nodes = []
    for n in co_graph.nodes():
        nodes.append({
            "id": n,
            "degree": degree.get(n, 0),
            "betweenness": round(betweenness.get(n, 0), 5),
            "eigenvector": round(eigenvector.get(n, 0), 5),
            "pagerank": round(pagerank.get(n, 0), 5),
            "community": communities.get(n, -1),
            "deal_count": co_graph.nodes[n].get("deal_count", 0),
        })

    edges = [
        {"source": a, "target": b, "weight": d["weight"]}
        for a, b, d in co_graph.edges(data=True)
    ]

    # investor -> companies they backed (for the syndicate recommendation stage)
    investor_portfolios = defaultdict(list)
    for u, v, d in bip_graph.edges(data=True):
        # bip_graph edges always go investor<->company; figure out which is which
        u_kind = bip_graph.nodes[u].get("kind")
        inv, comp = (u, v) if u_kind == "investor" else (v, u)
        investor_portfolios[inv].append({"company": comp, "role": d.get("role")})

    predicted_links = [
        {"investor_a": a, "investor_b": b, "adamic_adar_score": round(score, 4)}
        for a, b, score in aa_pairs
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "investor_portfolios": investor_portfolios,
        "company_meta": company_meta,
        "predicted_links": predicted_links,
        "summary": {
            "investor_count": co_graph.number_of_nodes(),
            "co_investment_edge_count": co_graph.number_of_edges(),
            "company_count": len(company_meta),
            "community_count": len(set(communities.values())),
        },
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python build_graph.py funding_deals_clean.json")
        sys.exit(1)

    deals = load_deals(sys.argv[1])
    print(f"Loaded {len(deals)} deal records")

    co_graph, bip_graph, company_meta = build_graphs(deals)
    print(f"Co-investment graph: {co_graph.number_of_nodes()} investors, "
          f"{co_graph.number_of_edges()} co-investment edges")
    print(f"Bipartite graph: {bip_graph.number_of_nodes()} total nodes "
          f"(investors + companies), {bip_graph.number_of_edges()} investment edges")

    degree, betweenness, eigenvector, pagerank = compute_centrality(co_graph)
    communities = detect_communities(co_graph)
    aa_pairs = top_adamic_adar_pairs(co_graph)

    print(f"\nDetected {len(set(communities.values()))} investor communities")

    print("\nTop 10 investors by degree (most active co-investors):")
    for inv, d in sorted(degree.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {inv}: {d} connections, {co_graph.nodes[inv].get('deal_count', 0)} deals")

    print("\nTop 10 investors by betweenness (bridge/connector investors):")
    for inv, b in sorted(betweenness.items(), key=lambda x: x[1], reverse=True)[:10]:
        if b > 0:
            print(f"  {inv}: {b:.4f}")

    print("\nTop 10 predicted future co-investment pairs (Adamic-Adar):")
    for a, b, score in aa_pairs[:10]:
        if score > 0:
            print(f"  {a} <-> {b}: {score:.3f}")

    contract = build_json_contract(
        co_graph, bip_graph, company_meta, degree, betweenness, eigenvector,
        pagerank, communities, aa_pairs,
    )
    with open("graph_data.json", "w", encoding="utf-8") as f:
        json.dump(contract, f, indent=2, ensure_ascii=False)
    print("\nSaved graph_data.json (dashboard-ready JSON contract)")

    nx.write_graphml(co_graph, "investor_graph.graphml")
    print("Saved investor_graph.graphml (open in Gephi for visual exploration)")


if __name__ == "__main__":
    main()
