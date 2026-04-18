"""
Hermes Web UI -- Graph dashboard data layer.

Discovers repos with graphify-out/ artifacts under ~/git-repos,
parses graph.json and GRAPH_REPORT.md for dashboard metadata,
and shells out to the graphify CLI for query/path/explain.
"""

import json
import logging
import os
import re
import shutil
import subprocess
from collections import Counter, deque
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

_SEARCH_ROOT = Path.home() / "git-repos"
_GRAPHIFY_DIR_NAME = "graphify-out"
_GRAPH_JSON = "graph.json"
_GRAPH_REPORT = "GRAPH_REPORT.md"
_MAX_DEPTH = 5  # how deep to scan for graphify-out/

# graphify CLI: prefer explicit path, fall back to PATH lookup
_GRAPHIFY_BIN = os.getenv(
    "GRAPHIFY_BIN",
    str(Path.home() / ".local" / "bin" / "graphify"),
)


def _find_graphify_bin() -> Optional[str]:
    """Return the graphify binary path if it exists, else None."""
    if Path(_GRAPHIFY_BIN).is_file():
        return _GRAPHIFY_BIN
    found = shutil.which("graphify")
    return found


# ── Discovery ────────────────────────────────────────────────────────────────


def _repo_identity(repo_dir: Path) -> str:
    """Best-effort stable identity for a repo across git worktrees."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_dir), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            common = proc.stdout.strip()
            if common:
                return str((repo_dir / common).resolve())
    except Exception:
        pass
    return str(repo_dir.resolve())


def discover_graph_repos(root: Optional[Path] = None) -> list[dict[str, Any]]:
    """Walk ``root`` (default ~/git-repos) for repos containing graphify-out/graph.json.

    Returns a lightweight list of repo metadata dicts suitable for a dashboard
    index.  Each entry contains repo name, path, and stats parsed from the
    graph.json + GRAPH_REPORT.md.
    """
    root = root or _SEARCH_ROOT
    if not root.is_dir():
        return []

    results_by_identity: dict[str, dict[str, Any]] = {}

    for dirpath, dirnames, _filenames in os.walk(str(root)):
        depth = dirpath[len(str(root)):].count(os.sep)
        if depth >= _MAX_DEPTH:
            dirnames.clear()
            continue
        # Skip hidden dirs and common noise
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".") and d not in {"node_modules", "__pycache__", "venv", ".venv"}
        ]
        graphify_dir = Path(dirpath) / _GRAPHIFY_DIR_NAME
        graph_json_path = graphify_dir / _GRAPH_JSON
        if graph_json_path.is_file():
            repo_dir = Path(dirpath)
            identity = _repo_identity(repo_dir)
            entry = _build_index_entry(repo_dir, graphify_dir, graph_json_path)
            if not entry:
                continue
            previous = results_by_identity.get(identity)
            if previous is None or entry.get("updated_at", 0) >= previous.get("updated_at", 0):
                results_by_identity[identity] = entry
    results = list(results_by_identity.values())
    results.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
    return results


def _build_index_entry(
    repo_dir: Path,
    graphify_dir: Path,
    graph_json_path: Path,
) -> Optional[dict[str, Any]]:
    """Build a lightweight index entry for one repo."""
    try:
        stat = graph_json_path.stat()
        graph_data = _read_graph_json_stats(graph_json_path)
        report_meta = _parse_report_header(graphify_dir / _GRAPH_REPORT)

        relative_repo = None
        try:
            relative_repo = str(repo_dir.relative_to(_SEARCH_ROOT))
        except Exception:
            relative_repo = repo_dir.name

        top_nodes = graph_data.get("top_nodes", [])
        suggested_questions = report_meta.get("suggested_questions", [])
        summary_line = report_meta.get("summary_line")

        return {
            "id": str(repo_dir),
            "repo": relative_repo,
            "name": repo_dir.name,
            "path": str(repo_dir),
            "graphify_dir": str(graphify_dir),
            "graph_json_size": stat.st_size,
            "graph_mtime": stat.st_mtime,
            "updated_at": stat.st_mtime,
            "description": summary_line or relative_repo,
            "node_count": graph_data.get("node_count", 0),
            "edge_count": graph_data.get("edge_count", 0),
            "community_count": graph_data.get("community_count", 0),
            "top_nodes": top_nodes,
            "suggested_questions": suggested_questions,
            "stats": graph_data,
            "report": report_meta,
            "has_html": (graphify_dir / "graph.html").is_file(),
        }
    except Exception as exc:
        logger.warning("Failed to index %s: %s", repo_dir, exc)
        return None


_GRAPH_COMMUNITY_PALETTE = [
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#BAB0AC",
]


def _build_visualization_payload(graph_json_path: Path) -> dict[str, Any]:
    """Load graph.json and return a visualization-friendly payload."""
    with open(graph_json_path, encoding="utf-8") as f:
        data = json.load(f)

    raw_nodes = data.get("nodes", [])
    raw_links = data.get("links", [])

    degree: Counter[str] = Counter()
    for link in raw_links:
        src = str(link.get("_src") or link.get("source") or "")
        tgt = str(link.get("_tgt") or link.get("target") or "")
        if src:
            degree[src] += 1
        if tgt:
            degree[tgt] += 1

    communities: Counter[int] = Counter()
    nodes: list[dict[str, Any]] = []
    for node in raw_nodes:
        node_id = str(node.get("id") or node.get("label") or "")
        if not node_id:
            continue
        community = int(node.get("community", 0) or 0)
        communities[community] += 1
        node_degree = int(node.get("degree") or degree.get(node_id, 0))
        nodes.append(
            {
                "id": node_id,
                "label": str(node.get("label") or node_id),
                "community": community,
                "community_name": str(node.get("community_name") or f"Community {community}"),
                "file_type": node.get("file_type") or node.get("type") or "node",
                "degree": node_degree,
                "size": float(node.get("size") or max(12, min(40, 12 + node_degree * 1.6))),
                "title": str(node.get("title") or node.get("label") or node_id),
            }
        )

    edges: list[dict[str, Any]] = []
    for idx, link in enumerate(raw_links):
        src = str(link.get("_src") or link.get("source") or "")
        tgt = str(link.get("_tgt") or link.get("target") or "")
        if not src or not tgt:
            continue
        edges.append(
            {
                "id": str(link.get("id") or f"edge-{idx}"),
                "from": src,
                "to": tgt,
                "label": str(link.get("label") or link.get("relation") or ""),
                "confidence": str(link.get("confidence") or ""),
            }
        )

    community_items = [
        {
            "id": community_id,
            "label": f"Community {community_id}",
            "count": count,
            "color": _GRAPH_COMMUNITY_PALETTE[community_id % len(_GRAPH_COMMUNITY_PALETTE)],
        }
        for community_id, count in sorted(communities.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "communities": community_items,
        "directed": bool(data.get("directed", False)),
    }


# ── Graph JSON parsing (lightweight — no full load for index) ────────────────


def _read_graph_json_stats(path: Path) -> dict[str, Any]:
    """Parse graph.json for node/edge/community counts and top-ranked nodes.

    Reads the full file but only extracts aggregate stats and top-5 nodes
    by degree (edge count).
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    nodes = data.get("nodes", [])
    links = data.get("links", [])

    # Community count
    communities: set[int] = set()
    for n in nodes:
        if "community" in n:
            communities.add(n["community"])

    # Degree ranking: count edges per node
    degree: Counter[str] = Counter()
    for link in links:
        src = link.get("_src") or link.get("source", "")
        tgt = link.get("_tgt") or link.get("target", "")
        if src:
            degree[src] += 1
        if tgt:
            degree[tgt] += 1

    # Build label lookup
    label_map: dict[str, str] = {}
    for n in nodes:
        label_map[n.get("id", "")] = n.get("label", n.get("id", ""))

    top_nodes = [
        {"id": nid, "label": label_map.get(nid, nid), "edges": count}
        for nid, count in degree.most_common(5)
    ]

    # Confidence breakdown
    extracted = sum(1 for l in links if l.get("confidence") == "EXTRACTED")
    inferred = sum(1 for l in links if l.get("confidence") == "INFERRED")

    return {
        "node_count": len(nodes),
        "edge_count": len(links),
        "community_count": len(communities),
        "top_nodes": top_nodes,
        "confidence": {
            "extracted": extracted,
            "inferred": inferred,
            "total": len(links),
        },
    }


# ── GRAPH_REPORT.md parsing ──────────────────────────────────────────────────

_RE_SUMMARY_LINE = re.compile(
    r"(\d+)\s+nodes?\s*·\s*(\d+)\s+edges?\s*·\s*(\d+)\s+communit",
    re.IGNORECASE,
)
_RE_CORPUS_LINE = re.compile(
    r"(\d+)\s+files?\s*·\s*~?([\d,]+)\s+words?",
    re.IGNORECASE,
)
_RE_GOD_NODE = re.compile(
    r"^\d+\.\s+`([^`]+)`\s*-\s*(\d+)\s+edges?",
    re.MULTILINE,
)
_RE_SUGGESTED_Q = re.compile(
    r"^-\s+\*\*(.+?)\*\*$",
    re.MULTILINE,
)


def _parse_report_header(report_path: Path) -> dict[str, Any]:
    """Extract structured metadata from GRAPH_REPORT.md."""
    result: dict[str, Any] = {
        "corpus": None,
        "summary_line": None,
        "god_nodes": [],
        "suggested_questions": [],
    }
    if not report_path.is_file():
        return result

    try:
        text = report_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return result

    # Corpus check
    m = _RE_CORPUS_LINE.search(text)
    if m:
        result["corpus"] = {
            "files": int(m.group(1)),
            "words": int(m.group(2).replace(",", "")),
        }

    # Summary line
    m = _RE_SUMMARY_LINE.search(text)
    if m:
        result["summary_line"] = f"{m.group(1)} nodes · {m.group(2)} edges · {m.group(3)} communities"

    # God nodes (top 10 most connected)
    god_nodes = _RE_GOD_NODE.findall(text)
    result["god_nodes"] = [
        {"label": label, "edges": int(edges)}
        for label, edges in god_nodes[:10]
    ]

    # Suggested questions
    sq_section = text.split("## Suggested Questions")
    if len(sq_section) > 1:
        questions = _RE_SUGGESTED_Q.findall(sq_section[1])
        result["suggested_questions"] = questions[:10]

    return result


# ── Detail endpoint ──────────────────────────────────────────────────────────


def get_graph_detail(repo_path: str, *, include_visualization: bool = True) -> Optional[dict[str, Any]]:
    """Return full graph detail for a single repo.

    Includes everything from the index entry plus the full GRAPH_REPORT.md
    text content.
    """
    repo_dir = Path(repo_path)
    graphify_dir = repo_dir / _GRAPHIFY_DIR_NAME
    graph_json_path = graphify_dir / _GRAPH_JSON
    if not graph_json_path.is_file():
        return None

    entry = _build_index_entry(repo_dir, graphify_dir, graph_json_path)
    if not entry:
        return None

    # Add full report text
    report_path = graphify_dir / _GRAPH_REPORT
    if report_path.is_file():
        try:
            entry["report_text"] = report_path.read_text(
                encoding="utf-8", errors="replace"
            )[:100_000]  # cap at 100KB
        except Exception:
            entry["report_text"] = None
    else:
        entry["report_text"] = None

    try:
        entry["visualization"] = _build_visualization_payload(graph_json_path) if include_visualization else None
    except Exception as exc:
        logger.warning("Failed to build graph visualization payload for %s: %s", repo_dir, exc)
        entry["visualization"] = {"nodes": [], "edges": [], "communities": [], "directed": False}

    return entry


def _load_graph_model(repo_path: str) -> Optional[dict[str, Any]]:
    repo_dir = Path(repo_path)
    graph_json_path = repo_dir / _GRAPHIFY_DIR_NAME / _GRAPH_JSON
    if not graph_json_path.is_file():
        return None
    with open(graph_json_path, encoding="utf-8") as f:
        data = json.load(f)

    node_map: dict[str, dict[str, Any]] = {}
    adjacency: dict[str, set[str]] = {}
    edges: list[dict[str, Any]] = []

    for node in data.get("nodes", []):
        node_id = str(node.get("id") or node.get("label") or "")
        if not node_id:
            continue
        normalized = dict(node)
        normalized["id"] = node_id
        normalized["label"] = str(node.get("label") or node_id)
        normalized["community"] = int(node.get("community", 0) or 0)
        normalized["degree"] = int(node.get("degree", 0) or 0)
        normalized["file_type"] = node.get("file_type") or node.get("type") or "node"
        normalized["summary"] = str(node.get("summary") or node.get("description") or node.get("title") or "")
        node_map[node_id] = normalized
        adjacency.setdefault(node_id, set())

    for idx, link in enumerate(data.get("links", [])):
        src = str(link.get("_src") or link.get("source") or "")
        tgt = str(link.get("_tgt") or link.get("target") or "")
        if not src or not tgt:
            continue
        adjacency.setdefault(src, set()).add(tgt)
        adjacency.setdefault(tgt, set()).add(src)
        edges.append(
            {
                "id": str(link.get("id") or f"edge-{idx}"),
                "from": src,
                "to": tgt,
                "label": str(link.get("label") or link.get("relation") or ""),
                "confidence": str(link.get("confidence") or ""),
            }
        )

    for node_id, neighbors in adjacency.items():
        if node_id in node_map and not node_map[node_id].get("degree"):
            node_map[node_id]["degree"] = len(neighbors)

    communities = Counter(node.get("community", 0) for node in node_map.values())
    return {
        "repo_dir": repo_dir,
        "graph_json_path": graph_json_path,
        "directed": bool(data.get("directed", False)),
        "nodes": node_map,
        "edges": edges,
        "adjacency": adjacency,
        "communities": communities,
    }


def _make_community_items(counter: Counter[int], *, limit: Optional[int] = None) -> list[dict[str, Any]]:
    items = [
        {
            "id": community_id,
            "label": f"Community {community_id}",
            "count": count,
            "color": _GRAPH_COMMUNITY_PALETTE[community_id % len(_GRAPH_COMMUNITY_PALETTE)],
        }
        for community_id, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]
    return items[:limit] if limit else items


def _build_slice_payload(model: dict[str, Any], node_ids: list[str], *, highlighted_edges: Optional[set[str]] = None) -> dict[str, Any]:
    highlighted_edges = highlighted_edges or set()
    node_id_set = {nid for nid in node_ids if nid in model["nodes"]}
    nodes = []
    community_counts: Counter[int] = Counter()
    for nid in node_ids:
        node = model["nodes"].get(nid)
        if not node:
            continue
        community = int(node.get("community", 0) or 0)
        community_counts[community] += 1
        degree = int(node.get("degree", 0) or len(model["adjacency"].get(nid, ())))
        nodes.append(
            {
                "id": nid,
                "label": node.get("label") or nid,
                "community": community,
                "community_name": node.get("community_name") or f"Community {community}",
                "file_type": node.get("file_type") or "node",
                "degree": degree,
                "size": float(node.get("size") or max(12, min(40, 12 + degree * 1.6))),
                "title": node.get("title") or node.get("label") or nid,
                "summary": node.get("summary") or "",
            }
        )

    edges = []
    for edge in model["edges"]:
        if edge["from"] in node_id_set and edge["to"] in node_id_set:
            item = dict(edge)
            if edge["id"] in highlighted_edges:
                item["highlighted"] = True
            edges.append(item)

    nodes.sort(key=lambda item: (-item.get("degree", 0), item.get("label", item["id"])))
    return {
        "nodes": nodes,
        "edges": edges,
        "communities": _make_community_items(community_counts),
        "directed": model["directed"],
    }


def _pick_focus_node(model: dict[str, Any]) -> Optional[str]:
    if not model["nodes"]:
        return None
    return max(model["nodes"].values(), key=lambda node: (node.get("degree", 0), node.get("label", ""))).get("id")


def get_graph_overview(repo_path: str, *, node_limit: int = 48) -> Optional[dict[str, Any]]:
    model = _load_graph_model(repo_path)
    if not model:
        return None
    ranked = sorted(model["nodes"].values(), key=lambda node: (-node.get("degree", 0), node.get("label", node["id"])))
    selected = [node["id"] for node in ranked[:node_limit]]
    focus_node = selected[0] if selected else None
    return {
        "mode": "overview",
        "focus": {"node_id": focus_node, "seed_nodes": [focus_node] if focus_node else []},
        "visualization": _build_slice_payload(model, selected),
        "search": search_graph_nodes(repo_path, "", limit=12),
    }


def get_graph_neighborhood(repo_path: str, node_id: str, *, depth: int = 1, limit: int = 120) -> Optional[dict[str, Any]]:
    model = _load_graph_model(repo_path)
    if not model or node_id not in model["nodes"]:
        return None
    depth = max(1, min(int(depth), 4))
    seen = {node_id}
    queue = deque([(node_id, 0)])
    ordered = [node_id]
    while queue and len(ordered) < limit:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        neighbors = sorted(model["adjacency"].get(current, ()), key=lambda nid: (-model["nodes"].get(nid, {}).get("degree", 0), nid))
        for neighbor in neighbors:
            if neighbor in seen:
                continue
            seen.add(neighbor)
            ordered.append(neighbor)
            if len(ordered) >= limit:
                break
            queue.append((neighbor, current_depth + 1))
    return {
        "mode": "focus",
        "focus": {"node_id": node_id, "seed_nodes": [node_id], "depth": depth},
        "visualization": _build_slice_payload(model, ordered),
        "inspector": model["nodes"][node_id],
    }


def expand_graph_neighborhood(repo_path: str, seed_nodes: list[str], *, depth: int = 1, limit: int = 140) -> Optional[dict[str, Any]]:
    model = _load_graph_model(repo_path)
    if not model:
        return None
    valid_seeds = [nid for nid in seed_nodes if nid in model["nodes"]]
    if not valid_seeds:
        return None
    seen = set(valid_seeds)
    ordered = list(valid_seeds)
    queue = deque((nid, 0) for nid in valid_seeds)
    depth = max(1, min(int(depth), 3))
    while queue and len(ordered) < limit:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        neighbors = sorted(model["adjacency"].get(current, ()), key=lambda nid: (-model["nodes"].get(nid, {}).get("degree", 0), nid))
        for neighbor in neighbors:
            if neighbor in seen:
                continue
            seen.add(neighbor)
            ordered.append(neighbor)
            if len(ordered) >= limit:
                break
            queue.append((neighbor, current_depth + 1))
    return {
        "mode": "explore",
        "focus": {"seed_nodes": valid_seeds, "depth": depth},
        "visualization": _build_slice_payload(model, ordered),
    }


def search_graph_nodes(repo_path: str, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    model = _load_graph_model(repo_path)
    if not model:
        return []
    query_norm = (query or "").strip().lower()
    nodes = list(model["nodes"].values())
    if query_norm:
        nodes = [
            node for node in nodes
            if query_norm in str(node.get("label", "")).lower()
            or query_norm in str(node.get("id", "")).lower()
            or query_norm in str(node.get("summary", "")).lower()
        ]
    ranked = sorted(
        nodes,
        key=lambda node: (
            0 if query_norm and str(node.get("label", "")).lower().startswith(query_norm) else 1,
            0 if query_norm and query_norm in str(node.get("label", "")).lower() else 1,
            -node.get("degree", 0),
            str(node.get("label", "")),
        ),
    )
    return [
        {
            "id": node["id"],
            "label": node.get("label") or node["id"],
            "community": node.get("community", 0),
            "degree": node.get("degree", 0),
            "summary": node.get("summary") or "",
            "file_type": node.get("file_type") or "node",
        }
        for node in ranked[:limit]
    ]


def find_graph_path(repo_path: str, from_id: str, to_id: str) -> Optional[dict[str, Any]]:
    model = _load_graph_model(repo_path)
    if not model or from_id not in model["nodes"] or to_id not in model["nodes"]:
        return None
    queue = deque([from_id])
    parents: dict[str, Optional[str]] = {from_id: None}
    while queue:
        current = queue.popleft()
        if current == to_id:
            break
        for neighbor in sorted(model["adjacency"].get(current, ())):
            if neighbor in parents:
                continue
            parents[neighbor] = current
            queue.append(neighbor)
    if to_id not in parents:
        return None
    path_nodes = []
    current = to_id
    while current is not None:
        path_nodes.append(current)
        current = parents[current]
    path_nodes.reverse()
    highlighted_edges: set[str] = set()
    for left, right in zip(path_nodes, path_nodes[1:]):
        for edge in model["edges"]:
            if {edge["from"], edge["to"]} == {left, right}:
                highlighted_edges.add(edge["id"])
                break
    return {
        "mode": "path",
        "focus": {"from": from_id, "to": to_id, "path": path_nodes},
        "visualization": _build_slice_payload(model, path_nodes, highlighted_edges=highlighted_edges),
    }


# ── Graphify CLI execution ───────────────────────────────────────────────────

_ALLOWED_COMMANDS = {"query", "path", "explain"}
_QUERY_TIMEOUT = 60  # seconds


def run_graphify_command(
    repo_path: str,
    command: str,
    args: list[str],
    *,
    budget: Optional[int] = None,
    dfs: bool = False,
) -> dict[str, Any]:
    """Run a graphify CLI command against a repo's graph.json.

    Parameters
    ----------
    repo_path : str
        Absolute path to the repo containing graphify-out/.
    command : str
        One of: query, path, explain.
    args : list[str]
        Positional arguments for the command (e.g., question text, node names).
    budget : int | None
        Token budget cap for ``query`` command.
    dfs : bool
        Use depth-first search for ``query`` command.

    Returns
    -------
    dict with keys: ok, output, error, command, args
    """
    if command not in _ALLOWED_COMMANDS:
        return {"ok": False, "error": f"Unknown command: {command}. Allowed: {', '.join(sorted(_ALLOWED_COMMANDS))}"}

    graphify_bin = _find_graphify_bin()
    if not graphify_bin:
        return {"ok": False, "error": "graphify CLI not found"}

    repo_dir = Path(repo_path)
    graph_json = repo_dir / _GRAPHIFY_DIR_NAME / _GRAPH_JSON
    if not graph_json.is_file():
        return {"ok": False, "error": f"No graph.json found at {graph_json}"}

    cmd = [graphify_bin, command] + list(args)
    cmd += ["--graph", str(graph_json)]

    if command == "query":
        if budget is not None:
            cmd += ["--budget", str(int(budget))]
        if dfs:
            cmd.append("--dfs")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_QUERY_TIMEOUT,
            cwd=str(repo_dir),
        )
        output = proc.stdout.strip()
        stderr = proc.stderr.strip()

        filtered_lines = [line for line in output.splitlines() if not line.strip().startswith('warning: skill is from graphify')]
        output = '\n'.join(filtered_lines).strip()

        if proc.returncode != 0:
            return {
                "ok": False,
                "error": stderr or f"graphify exited with code {proc.returncode}",
                "output": output,
                "command": command,
                "args": args,
            }

        return {
            "ok": True,
            "answer": output,
            "output": output,
            "sources": [],
            "command": command,
            "args": args,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"graphify command timed out after {_QUERY_TIMEOUT}s"}
    except FileNotFoundError:
        return {"ok": False, "error": "graphify binary not executable or not found"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
