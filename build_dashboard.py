"""
Stage 3 — Dashboard builder.

Reads graph_data.json (output of build_graph.py) and produces a
self-contained network_dashboard.html — no server needed, data is
inlined directly into the page so it works via double-click/file://.

Re-run this any time you regenerate graph_data.json (e.g. after
scraping more weeks of data) to refresh the dashboard.

Usage:
    pip install networkx
    python build_dashboard.py graph_data.json
"""
import json
import sys

import networkx as nx


def compute_layout(nodes, edges):
    """Spring layout in Python (networkx) — Plotly.js has no built-in
    force-directed physics, so positions are precomputed here and
    passed to the front end as static x/y coordinates."""
    g = nx.Graph()
    for n in nodes:
        g.add_node(n["id"])
    for e in edges:
        g.add_edge(e["source"], e["target"], weight=e["weight"])

    pos = nx.spring_layout(g, k=0.6, iterations=80, weight="weight", seed=42)
    return {node: {"x": round(x, 4), "y": round(y, 4)} for node, (x, y) in pos.items()}


def build_html(data, positions):
    nodes = data["nodes"]
    edges = data["edges"]
    summary = data["summary"]
    predicted = data["predicted_links"]

    top_degree = sorted(nodes, key=lambda n: n["degree"], reverse=True)[:12]
    top_betweenness = sorted(nodes, key=lambda n: n["betweenness"], reverse=True)[:12]

    payload = {
        "nodes": nodes,
        "edges": edges,
        "positions": positions,
        "summary": summary,
        "predicted": predicted,
        "top_degree": top_degree,
        "top_betweenness": top_betweenness,
    }
    payload_json = json.dumps(payload)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VC Co-Investment Network Intelligence</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>
  :root {{
    --navy-950: #060b1a;
    --navy-900: #0a1128;
    --navy-800: #101a3a;
    --navy-700: #17244d;
    --ice-400: #6fd8ff;
    --ice-300: #9fe6ff;
    --ice-glow: rgba(111, 216, 255, 0.35);
    --text-hi: #eaf2fb;
    --text-mid: #9fb0cc;
    --text-dim: #64749a;
    --amber: #ffb454;
    --coral: #ff6b81;
    --mint: #5eead4;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: radial-gradient(ellipse at top left, var(--navy-800), var(--navy-950) 60%);
    color: var(--text-hi);
    font-family: 'Inter', sans-serif;
    display: flex;
    min-height: 100vh;
  }}
  aside {{
    width: 240px;
    flex-shrink: 0;
    background: var(--navy-900);
    border-right: 1px solid rgba(111,216,255,0.08);
    padding: 32px 24px;
    position: sticky;
    top: 0;
    height: 100vh;
  }}
  .brand {{
    font-weight: 800;
    font-size: 1.05rem;
    letter-spacing: -0.01em;
    color: var(--text-hi);
    line-height: 1.3;
  }}
  .brand span {{ color: var(--ice-400); }}
  .brand-sub {{
    margin-top: 6px;
    font-size: 0.78rem;
    color: var(--text-dim);
  }}
  nav {{ margin-top: 48px; display: flex; flex-direction: column; gap: 4px; }}
  nav a {{
    color: var(--text-mid);
    text-decoration: none;
    font-size: 0.88rem;
    font-weight: 500;
    padding: 9px 12px;
    border-radius: 8px;
    transition: background 0.15s, color 0.15s;
  }}
  nav a:hover, nav a.active {{ background: var(--navy-700); color: var(--ice-300); }}

  main {{ flex: 1; padding: 40px 48px; max-width: 1400px; }}
  h1 {{ font-size: 1.6rem; font-weight: 700; letter-spacing: -0.015em; }}
  .subtitle {{ color: var(--text-mid); margin-top: 6px; font-size: 0.92rem; max-width: 640px; }}

  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin: 32px 0 36px;
  }}
  .kpi-card {{
    background: linear-gradient(160deg, var(--navy-800), var(--navy-900));
    border: 1px solid rgba(111,216,255,0.1);
    border-radius: 14px;
    padding: 20px 22px;
  }}
  .kpi-value {{
    font-size: 2rem;
    font-weight: 800;
    color: var(--ice-300);
    font-variant-numeric: tabular-nums;
  }}
  .kpi-label {{
    margin-top: 4px;
    font-size: 0.8rem;
    color: var(--text-mid);
  }}

  .panel {{
    background: var(--navy-900);
    border: 1px solid rgba(111,216,255,0.09);
    border-radius: 16px;
    padding: 24px 26px 12px;
    margin-bottom: 28px;
  }}
  .panel-title {{
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-hi);
    margin-bottom: 4px;
  }}
  .panel-desc {{
    font-size: 0.82rem;
    color: var(--text-dim);
    margin-bottom: 16px;
  }}

  .two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{
    text-align: left;
    color: var(--text-dim);
    font-weight: 500;
    font-size: 0.72rem;
    padding: 8px 10px;
    border-bottom: 1px solid rgba(111,216,255,0.1);
  }}
  td {{
    padding: 10px 10px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
    color: var(--text-mid);
  }}
  td.name {{ color: var(--text-hi); font-weight: 500; }}
  td.num {{ font-family: 'JetBrains Mono', monospace; color: var(--ice-300); text-align: right; }}
  tr:last-child td {{ border-bottom: none; }}

  .badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.7rem;
    font-weight: 600;
    background: rgba(111,216,255,0.12);
    color: var(--ice-300);
  }}
</style>
</head>
<body>

<aside>
  <div class="brand">VC Network<br><span>Intelligence</span></div>
  <div class="brand-sub">Co-investment graph &amp; syndicate analysis</div>
  <nav>
    <a class="active" href="#network">Network Graph</a>
    <a href="#centrality">Investor Rankings</a>
    <a href="#syndicate">Syndicate Predictions</a>
  </nav>
</aside>

<main>
  <h1>VC Co-Investment Network Intelligence</h1>
  <p class="subtitle">Investor relationships derived from real funding announcements — mapped, scored, and used to predict future syndicate partners.</p>

  <div class="kpi-row">
    <div class="kpi-card"><div class="kpi-value" id="kpi-investors">—</div><div class="kpi-label">Investors tracked</div></div>
    <div class="kpi-card"><div class="kpi-value" id="kpi-companies">—</div><div class="kpi-label">Companies funded</div></div>
    <div class="kpi-card"><div class="kpi-value" id="kpi-edges">—</div><div class="kpi-label">Co-investment links</div></div>
    <div class="kpi-card"><div class="kpi-value" id="kpi-communities">—</div><div class="kpi-label">Investor communities</div></div>
  </div>

  <div class="panel" id="network">
    <div class="panel-title">Co-Investment Network</div>
    <div class="panel-desc">Each node is an investor; an edge means they've backed the same company together. Node color marks its detected community, node size reflects deal activity.</div>
    <div id="network-graph" style="height: 560px;"></div>
  </div>

  <div class="two-col">
    <div class="panel" id="centrality">
      <div class="panel-title">Most Active Investors</div>
      <div class="panel-desc">Ranked by degree — number of distinct co-investors</div>
      <table>
        <thead><tr><th>Investor</th><th style="text-align:right">Connections</th><th style="text-align:right">Deals</th></tr></thead>
        <tbody id="table-degree"></tbody>
      </table>
    </div>

    <div class="panel">
      <div class="panel-title">Bridge Investors</div>
      <div class="panel-desc">Ranked by betweenness — connects otherwise separate investor clusters</div>
      <table>
        <thead><tr><th>Investor</th><th style="text-align:right">Betweenness</th></tr></thead>
        <tbody id="table-betweenness"></tbody>
      </table>
    </div>
  </div>

  <div class="panel" id="syndicate">
    <div class="panel-title">Predicted Syndicate Pairs</div>
    <div class="panel-desc">Investor pairs most likely to co-invest next, based on shared-neighbor structure (Adamic-Adar index) — not yet observed co-investing together</div>
    <table>
      <thead><tr><th>Investor A</th><th>Investor B</th><th style="text-align:right">Likelihood score</th></tr></thead>
      <tbody id="table-predicted"></tbody>
    </table>
  </div>
</main>

<script>
const DATA = {payload_json};

document.getElementById('kpi-investors').textContent = DATA.summary.investor_count;
document.getElementById('kpi-companies').textContent = DATA.summary.company_count;
document.getElementById('kpi-edges').textContent = DATA.summary.co_investment_edge_count;
document.getElementById('kpi-communities').textContent = DATA.summary.community_count;

// ---- Network graph ----
const communityColors = [
  '#6fd8ff', '#5eead4', '#ffb454', '#ff6b81', '#c4b5fd',
  '#fbbf24', '#34d399', '#f472b6', '#818cf8', '#f97316'
];

const edgeX = [], edgeY = [];
DATA.edges.forEach(e => {{
  const s = DATA.positions[e.source], t = DATA.positions[e.target];
  if (!s || !t) return;
  edgeX.push(s.x, t.x, null);
  edgeY.push(s.y, t.y, null);
}});

const edgeTrace = {{
  x: edgeX, y: edgeY, mode: 'lines',
  line: {{ color: 'rgba(111,216,255,0.15)', width: 1 }},
  hoverinfo: 'none', type: 'scatter'
}};

const nodeX = [], nodeY = [], nodeText = [], nodeColor = [], nodeSize = [];
DATA.nodes.forEach(n => {{
  const p = DATA.positions[n.id];
  if (!p) return;
  nodeX.push(p.x); nodeY.push(p.y);
  nodeText.push(`${{n.id}}<br>${{n.deal_count}} deals · ${{n.degree}} connections`);
  nodeColor.push(communityColors[n.community % communityColors.length]);
  nodeSize.push(8 + Math.min(n.degree, 15) * 2.2);
}});

const nodeTrace = {{
  x: nodeX, y: nodeY, mode: 'markers', type: 'scatter',
  text: nodeText, hoverinfo: 'text',
  marker: {{
    color: nodeColor, size: nodeSize,
    line: {{ color: 'rgba(6,11,26,0.8)', width: 1 }}
  }}
}};

Plotly.newPlot('network-graph', [edgeTrace, nodeTrace], {{
  paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
  showlegend: false, margin: {{ t: 10, b: 10, l: 10, r: 10 }},
  xaxis: {{ visible: false }}, yaxis: {{ visible: false }},
  hoverlabel: {{ bgcolor: '#101a3a', font: {{ color: '#eaf2fb', family: 'Inter' }}, bordercolor: '#6fd8ff' }}
}}, {{ displayModeBar: false, responsive: true }});

// ---- Tables ----
const degreeBody = document.getElementById('table-degree');
DATA.top_degree.forEach(n => {{
  degreeBody.innerHTML += `<tr><td class="name">${{n.id}}</td><td class="num">${{n.degree}}</td><td class="num">${{n.deal_count}}</td></tr>`;
}});

const betweennessBody = document.getElementById('table-betweenness');
DATA.top_betweenness.forEach(n => {{
  betweennessBody.innerHTML += `<tr><td class="name">${{n.id}}</td><td class="num">${{n.betweenness.toFixed(4)}}</td></tr>`;
}});

const predictedBody = document.getElementById('table-predicted');
DATA.predicted.slice(0, 15).forEach(p => {{
  predictedBody.innerHTML += `<tr><td class="name">${{p.investor_a}}</td><td class="name">${{p.investor_b}}</td><td class="num">${{p.adamic_adar_score.toFixed(3)}}</td></tr>`;
}});
</script>

</body>
</html>
"""


def main():
    if len(sys.argv) < 2:
        print("Usage: python build_dashboard.py graph_data.json")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    positions = compute_layout(data["nodes"], data["edges"])
    html = build_html(data, positions)

    with open("network_dashboard.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Saved network_dashboard.html — open it directly in a browser (no server needed)")


if __name__ == "__main__":
    main()
