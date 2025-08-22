#!/usr/bin/env python3
import argparse
import json
import os
from typing import Any, Dict, List, Set, Tuple

import networkx as nx


def load_graph(path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("nodes", []), data.get("edges", [])


def directed_hard_graph(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> nx.DiGraph:
    G = nx.DiGraph()
    for n in nodes:
        G.add_node(n["id"], **n)
    for e in edges:
        if e.get("kind") == "hard":
            G.add_edge(e["source"], e["target"])
    # drop self-loops
    G.remove_edges_from(nx.selfloop_edges(G))
    return G


def transitive_reduction_with_scc(G: nx.DiGraph) -> nx.DiGraph:
    # Collapse strongly connected components to ensure DAG for TR
    sccs: List[Set[str]] = list(nx.strongly_connected_components(G))
    comp_id_of: Dict[str, int] = {}
    for i, comp in enumerate(sccs):
        for v in comp:
            comp_id_of[v] = i

    # Build component DAG
    CG = nx.DiGraph()
    for i in range(len(sccs)):
        CG.add_node(i)
    original_cross_edges: Dict[Tuple[int, int], List[Tuple[str, str]]] = {}
    for u, v in G.edges():
        cu, cv = comp_id_of[u], comp_id_of[v]
        if cu != cv:
            CG.add_edge(cu, cv)
            original_cross_edges.setdefault((cu, cv), []).append((u, v))

    # Transitive reduction on component DAG
    TR_CG = nx.transitive_reduction(CG) if CG.number_of_edges() else CG

    # Build reduced graph: keep all intra-SCC edges; between SCCs keep one representative per reduced edge
    R = nx.DiGraph()
    R.add_nodes_from(G.nodes(data=True))

    # Keep intra-SCC edges (within each component)
    for i, comp in enumerate(sccs):
        if len(comp) == 1:
            continue
        for u in comp:
            for v in G.successors(u):
                if comp_id_of[v] == i:
                    R.add_edge(u, v)

    # For each edge in reduced component graph, keep one representative original edge
    for cu, cv in TR_CG.edges():
        reps = original_cross_edges.get((cu, cv), [])
        if not reps:
            continue
        # choose deterministically: first sorted
        u, v = sorted(reps)[0]
        R.add_edge(u, v)

    return R


def detect_communities_undirected(R: nx.DiGraph) -> Dict[str, int]:
    UG = R.to_undirected()
    # Greedy modularity communities (built-in, no extra deps)
    communities = list(nx.algorithms.community.greedy_modularity_communities(UG))
    node_to_comm: Dict[str, int] = {}
    for cid, comm in enumerate(communities):
        for v in comm:
            node_to_comm[v] = cid
    # Isolated nodes not included
    for v in R.nodes():
        node_to_comm.setdefault(v, -1)
    return node_to_comm


def palette(n: int) -> List[str]:
    base = [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]
    if n <= len(base):
        return base[:n]
    colors = []
    for i in range(n):
        colors.append(base[i % len(base)])
    return colors


def write_outputs(R: nx.DiGraph, node_to_comm: Dict[str, int], graph_out: str, comm_out: str) -> None:
    # Prepare node list with community and color
    max_comm = max(node_to_comm.values()) if node_to_comm else -1
    colors = palette(max_comm + 1)
    nodes: List[Dict[str, Any]] = []
    for v, data in R.nodes(data=True):
        cid = node_to_comm.get(v, -1)
        color = colors[cid] if cid >= 0 else "#4f46e5"
        nodes.append({
            "id": v,
            "label": data.get("label") or v,
            "community": cid,
            "color": color,
            "subject": data.get("subject"),
        })

    edges: List[Dict[str, Any]] = []
    for u, v in R.edges():
        edges.append({"source": u, "target": v, "kind": "hard"})

    os.makedirs(os.path.dirname(graph_out) or ".", exist_ok=True)
    with open(graph_out, "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes, "edges": edges}, f, ensure_ascii=False, indent=2)

    # communities summary
    comm_map: Dict[int, List[str]] = {}
    for node, cid in node_to_comm.items():
        comm_map.setdefault(cid, []).append(node)
    with open(comm_out, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in sorted(comm_map.items())}, f, ensure_ascii=False, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser(description="Transitive reduction + community detection pipeline")
    ap.add_argument("input", nargs="?", default="data/graph.json", help="Input graph.json (nodes, edges)")
    ap.add_argument("--graph-out", default="data/graph_reduced.json", help="Output reduced graph with communities")
    ap.add_argument("--comm-out", default="data/communities.json", help="Output communities membership")
    args = ap.parse_args()

    nodes, edges = load_graph(args.input)
    G = directed_hard_graph(nodes, edges)
    R = transitive_reduction_with_scc(G)
    node_to_comm = detect_communities_undirected(R)
    write_outputs(R, node_to_comm, args.graph_out, args.comm_out)
    print(f"reduced_nodes={R.number_of_nodes()} reduced_edges={R.number_of_edges()} communities={max(node_to_comm.values())+1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


