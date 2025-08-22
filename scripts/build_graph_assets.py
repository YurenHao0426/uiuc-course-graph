#!/usr/bin/env python3
import argparse
import json
import math
import os
from typing import Any, Dict, List, Tuple

import networkx as nx


def collect_courses_from_ast(ast: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        op = node.get("op")
        if op == "COURSE" and node.get("course"):
            out.append(node["course"])
        for child in node.get("items", []) or []:
            walk(child)
    walk(ast)
    # Unique order-preserving
    seen = set()
    uniq: List[str] = []
    for c in out:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def build_graph(courses: List[Dict[str, Any]], include_coreq: bool = True) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    nodes_map: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    def ensure_node(course_id: str, label: str = None) -> None:
        if course_id not in nodes_map:
            nodes_map[course_id] = {"id": course_id, "label": label or course_id, "subject": course_id.split()[0] if ' ' in course_id else None}

    for c in courses:
        idx = c.get("index")
        name = c.get("name")
        ensure_node(idx, name)
        pr = c.get("prerequisites") or {}
        hard = pr.get("hard") or {"op": "EMPTY"}
        coreq = pr.get("coreq_ok") or {"op": "EMPTY"}
        for pre in collect_courses_from_ast(hard):
            ensure_node(pre)
            edges.append({"source": pre, "target": idx, "kind": "hard"})
        if include_coreq:
            for pre in collect_courses_from_ast(coreq):
                ensure_node(pre)
                edges.append({"source": pre, "target": idx, "kind": "coreq"})

    nodes = [ {"id": n["id"], "label": n["label"], "subject": n.get("subject")} for n in nodes_map.values() ]
    return nodes, edges


def compute_positions(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    seed: int = 42,
    layout: str = "spring",
    iterations: int = 100,
    component_wise: bool = False,
    # SMACOF (MDS) options
    mds_backend: str = "auto",  # auto|sklearn|cuml
    mds_max_iter: int = 300,
    mds_eps: float = 1e-3,
    mds_verbose: int = 1,
    # Overlap resolution options
    resolve_overlap: bool = False,
    node_size_px: float = 6.0,
    min_dist_mul: float = 1.5,
    overlap_max_iters: int = 60,
    overlap_step: float = 0.5,
) -> Dict[str, Dict[str, float]]:
    # Use a force-directed layout over an undirected graph for a compact web-like layout
    G = nx.Graph()
    for n in nodes:
        G.add_node(n["id"]) 
    for e in edges:
        G.add_edge(e["source"], e["target"])  # undirected for layout

    def layout_graph(graph: nx.Graph) -> Dict[str, Tuple[float, float]]:
        if layout == "drl":
            try:
                import igraph as ig  # type: ignore
            except Exception as e:
                raise RuntimeError("python-igraph is required for DRL/OpenOrd-like layout; pip install python-igraph") from e
            nodes_list = list(graph.nodes())
            index_of = {v: i for i, v in enumerate(nodes_list)}
            g = ig.Graph()
            g.add_vertices(len(nodes_list))
            g.vs["name"] = nodes_list
            # unique edges only
            edge_idx = set()
            for u, v in graph.edges():
                iu, iv = index_of[u], index_of[v]
                if iu == iv:
                    continue
                a, b = (iu, iv) if iu < iv else (iv, iu)
                if (a, b) not in edge_idx:
                    edge_idx.add((a, b))
            if edge_idx:
                g.add_edges(list(edge_idx))
            # DRL (OpenOrd-style) is good for community separation
            lay = g.layout_drl()
            coords = [[float(x), float(y)] for x, y in lay]
            return {nodes_list[i]: (coords[i][0], coords[i][1]) for i in range(len(nodes_list))}
        if layout == "fa2":
            try:
                from fa2 import ForceAtlas2  # type: ignore
            except Exception as e:
                raise RuntimeError("fa2 is required for ForceAtlas2 layout; pip install fa2") from e
            fa = ForceAtlas2(
                # LinLog energy model emphasizes community separation
                linLogMode=True,
                gravity=1.0,
                strongGravityMode=True,
                scalingRatio=2.0,
                outboundAttractionDistribution=False,
                barnesHutOptimize=True,
                barnesHutTheta=1.2,
                jitterTolerance=1.0,
                edgeWeightInfluence=1.0,
                adjustSizes=False,
                verbose=False,
            )
            pos = fa.forceatlas2_networkx_layout(graph, pos=None, iterations=max(300, iterations))
            return {n: (float(xy[0]), float(xy[1])) for n, xy in pos.items()}
        if layout == "smacof":
            try:
                import numpy as np
            except Exception as e:
                raise RuntimeError("NumPy is required for smacof layout") from e

            nodes_list = list(graph.nodes())
            n = len(nodes_list)
            if n == 0:
                return {}
            if n == 1:
                return {nodes_list[0]: (0.0, 0.0)}

            # Compute all-pairs shortest path distances (undirected)
            index_of = {v: i for i, v in enumerate(nodes_list)}
            D = np.full((n, n), 0.0, dtype=np.float32)
            large = 1e6
            for i in range(n):
                for j in range(n):
                    if i != j:
                        D[i, j] = large
            for src, lengths in nx.all_pairs_shortest_path_length(graph):
                i = index_of[src]
                for dst, d in lengths.items():
                    j = index_of[dst]
                    if i != j:
                        D[i, j] = float(d)
                        D[j, i] = float(d)

            # Replace remaining large distances with max finite distance * 1.5
            finite = D[D < large]
            maxd = float(finite.max()) if finite.size else 1.0
            D[D >= large] = maxd * 1.5

            backend_used = None
            coords = None
            if mds_backend in ("auto", "cuml"):
                try:
                    from cuml.manifold import MDS as cuMDS  # type: ignore
                    backend_used = "cuml"
                    print("[smacof] using cuML MDS (GPU) ...")
                    m = cuMDS(n_components=2, dissimilarity='precomputed', max_iter=mds_max_iter, random_state=seed, verbose=bool(mds_verbose))
                    coords = m.fit_transform(D)
                    try:
                        coords = coords.get()  # convert cupy to numpy if needed
                    except Exception:
                        pass
                except Exception:
                    if mds_backend == "cuml":
                        raise
            if coords is None:
                from sklearn.manifold import MDS
                backend_used = "sklearn"
                print("[smacof] using scikit-learn MDS (CPU) ...")
                # verbose prints per-iteration stress
                mds = MDS(n_components=2, dissimilarity='precomputed', metric=True, random_state=seed, n_init=1, max_iter=mds_max_iter, eps=mds_eps, verbose=mds_verbose)
                coords = mds.fit_transform(D)
            print(f"[smacof] backend={backend_used} done. shape={coords.shape}")
            
            return {nodes_list[i]: (float(coords[i, 0]), float(coords[i, 1])) for i in range(n)}

        if layout == "random":
            return nx.random_layout(graph, dim=2, seed=seed)
        if layout == "kk":
            return nx.kamada_kawai_layout(graph, dim=2)
        if layout == "none":
            return {n: (0.0, 0.0) for n in graph.nodes}
        # default: spring
        try:
            return nx.spring_layout(graph, seed=seed, dim=2, iterations=iterations)
        except ModuleNotFoundError:
            # SciPy not installed – use kamada_kawai instead
            return nx.kamada_kawai_layout(graph, dim=2)
        except Exception:
            return nx.kamada_kawai_layout(graph, dim=2)

    if component_wise:
        pos_raw: Dict[str, Tuple[float, float]] = {}
        for comp in nx.connected_components(G):
            sub = G.subgraph(comp)
            local = layout_graph(sub)
            pos_raw.update(local)
    else:
        pos_raw = layout_graph(G)

    # Normalize positions to a fixed range for consistent initial viewport
    xs = [p[0] for p in pos_raw.values()]
    ys = [p[1] for p in pos_raw.values()]
    min_x, max_x = (min(xs), max(xs)) if xs else (0.0, 1.0)
    min_y, max_y = (min(ys), max(ys)) if ys else (0.0, 1.0)
    span_x = max(max_x - min_x, 1e-6)
    span_y = max(max_y - min_y, 1e-6)

    # Scale to a large square canvas by default; for SMACOF earlier we used disk mapping.
    # Here keep linear scaling to preserve community geometry (good for ForceAtlas2/SMACOF alike).
    scale = 6000.0
    out: Dict[str, Dict[str, float]] = {}
    for node_id, (x, y) in pos_raw.items():
        x01 = (x - min_x) / span_x  # 0..1
        y01 = (y - min_y) / span_y  # 0..1
        out[node_id] = {"x": (x01 - 0.5) * scale, "y": (y01 - 0.5) * scale}

    if resolve_overlap and out:
        # Simple grid-based overlap removal with minimal displacement
        target_dist = max(1.0, node_size_px * min_dist_mul)
        cell = target_dist
        node_ids = list(out.keys())
        for _ in range(overlap_max_iters):
            # Build spatial hash
            grid: Dict[Tuple[int,int], List[str]] = {}
            for nid in node_ids:
                p = out[nid]
                gx = int(math.floor(p["x"] / cell))
                gy = int(math.floor(p["y"] / cell))
                grid.setdefault((gx, gy), []).append(nid)

            moved = 0.0
            disp: Dict[str, Tuple[float,float]] = {}
            for nid in node_ids:
                px = out[nid]["x"]; py = out[nid]["y"]
                gx = int(math.floor(px / cell)); gy = int(math.floor(py / cell))
                # check neighbors cells
                for dx in (-1,0,1):
                    for dy in (-1,0,1):
                        cell_nodes = grid.get((gx+dx, gy+dy), [])
                        for mid in cell_nodes:
                            if mid <= nid:  # avoid double count and self
                                continue
                            qx = out[mid]["x"]; qy = out[mid]["y"]
                            vx = qx - px; vy = qy - py
                            dist = math.hypot(vx, vy)
                            if dist < target_dist and dist > 1e-6:
                                overlap = target_dist - dist
                                ux = vx / dist; uy = vy / dist
                                mx = -ux * (overlap * 0.5)
                                my = -uy * (overlap * 0.5)
                                disp[nid] = (disp.get(nid, (0.0,0.0))[0] + mx, disp.get(nid, (0.0,0.0))[1] + my)
                                disp[mid] = (disp.get(mid, (0.0,0.0))[0] - mx, disp.get(mid, (0.0,0.0))[1] - my)
            if not disp:
                break
            for nid, (dx, dy) in disp.items():
                out[nid]["x"] += dx * overlap_step
                out[nid]["y"] += dy * overlap_step
                moved += abs(dx) + abs(dy)
            if moved < 1e-3:
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Build slim graph assets and preset positions")
    ap.add_argument("input", nargs="?", default="data/courses_parsed.json", help="Input parsed courses JSON")
    ap.add_argument("--graph-out", default="data/graph.json", help="Output graph JSON (nodes, edges)")
    ap.add_argument("--pos-out", default="data/positions.json", help="Output positions JSON (node -> {x,y})")
    ap.add_argument("--pos-out-alt", nargs='*', default=[], help="Additional positions to generate in the form layout:name (e.g., kk:positions_kk.json spring:positions_spring.json)")
    ap.add_argument("--hard-only", action="store_true", help="Only include hard prerequisite edges (exclude coreq)")
    ap.add_argument("--layout", choices=["spring","kk","random","none","smacof","fa2","drl"], default="fa2", help="Layout algorithm for positions")
    ap.add_argument("--iterations", type=int, default=60, help="Iterations for spring layout (lower is faster)")
    ap.add_argument("--component-wise", action="store_true", help="Layout each connected component separately (can be faster)")
    # Overlap options
    ap.add_argument("--resolve-overlap", action="store_true", help="Run overlap removal post-process")
    ap.add_argument("--node-size", type=float, default=6.0, help="Node visual diameter in px (for spacing)")
    ap.add_argument("--min-dist-mul", type=float, default=1.5, help="Minimum center distance multiplier of node size")
    # SMACOF options
    ap.add_argument("--mds-backend", choices=["auto","sklearn","cuml"], default="auto", help="Backend for SMACOF (stress majorization)")
    ap.add_argument("--mds-max-iter", type=int, default=300, help="Max iterations for SMACOF")
    ap.add_argument("--mds-eps", type=float, default=1e-3, help="Convergence tolerance for SMACOF")
    ap.add_argument("--mds-verbose", type=int, default=1, help="Verbosity for SMACOF (>=1 prints per-iteration stress)")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        courses = json.load(f)

    nodes, edges = build_graph(courses, include_coreq=not args.hard_only)

    os.makedirs(os.path.dirname(args.graph_out) or ".", exist_ok=True)
    with open(args.graph_out, "w", encoding="utf-8") as f:
        json.dump({"nodes": nodes, "edges": edges}, f, ensure_ascii=False, indent=2)

    print(f"building positions: nodes={len(nodes)} edges={len(edges)} layout={args.layout} iter={args.iterations} component_wise={args.component_wise}")
    pos = compute_positions(
        nodes, edges,
        layout=args.layout,
        iterations=args.iterations,
        component_wise=args.component_wise,
        mds_backend=args.mds_backend,
        mds_max_iter=args.mds_max_iter,
        mds_eps=args.mds_eps,
        mds_verbose=args.mds_verbose,
        resolve_overlap=args.resolve_overlap,
        node_size_px=args.node_size,
        min_dist_mul=args.min_dist_mul,
    )
    with open(args.pos_out, "w", encoding="utf-8") as f:
        json.dump(pos, f, ensure_ascii=False, indent=2)

    # Optionally generate additional layouts
    for spec in args.pos_out_alt:
        try:
            lay, path = spec.split(":", 1)
        except ValueError:
            print(f"[warn] invalid --pos-out-alt spec: {spec}")
            continue
        try:
            alt = compute_positions(
                nodes, edges,
                layout=lay,
                iterations=args.iterations,
                component_wise=args.component_wise,
                mds_backend=args.mds_backend,
                mds_max_iter=args.mds_max_iter,
                mds_eps=args.mds_eps,
                mds_verbose=args.mds_verbose,
            )
            with open(path, "w", encoding="utf-8") as f:
                json.dump(alt, f, ensure_ascii=False, indent=2)
            print(f"wrote alt positions: {lay} -> {path}")
        except Exception as e:
            print(f"[warn] failed alt positions {lay}: {e}")

    print(f"nodes: {len(nodes)}, edges: {len(edges)}, positions: {len(pos)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


