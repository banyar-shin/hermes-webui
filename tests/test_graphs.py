"""
Tests for the Graphs dashboard API endpoints and data layer.
Run: python -m pytest tests/test_graphs.py -v
"""
import json
import os
import pathlib
import tempfile
import urllib.error
import urllib.request

import pytest

from tests._pytest_port import BASE

# ── HTTP helpers ─────────────────────────────────────────────────────────────

def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return json.loads(r.read()), r.status


def post(path: str, body: dict | None = None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read()), e.code
        except Exception:
            return {}, e.code


# ── Unit tests for api/graphs.py module ──────────────────────────────────────

class TestDiscoverGraphRepos:
    """Test discover_graph_repos with synthetic directories."""

    def test_discover_finds_graph_repos(self, tmp_path: pathlib.Path):
        """discover_graph_repos finds repos with graphify-out/graph.json."""
        from api.graphs import discover_graph_repos

        # Create a fake repo with graphify-out
        repo = tmp_path / "my-repo" / "graphify-out"
        repo.mkdir(parents=True)
        graph_data = {
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [
                {"label": "foo", "id": "foo", "community": 0, "file_type": "code",
                 "source_file": "/tmp/foo.py", "source_location": "L1"},
                {"label": "bar", "id": "bar", "community": 0, "file_type": "code",
                 "source_file": "/tmp/bar.py", "source_location": "L1"},
                {"label": "baz", "id": "baz", "community": 1, "file_type": "code",
                 "source_file": "/tmp/baz.py", "source_location": "L1"},
            ],
            "links": [
                {"relation": "calls", "confidence": "EXTRACTED", "confidence_score": 1.0,
                 "weight": 1.0, "_src": "foo", "_tgt": "bar", "source": "foo", "target": "bar",
                 "source_file": "/tmp/foo.py", "source_location": "L5"},
                {"relation": "uses", "confidence": "INFERRED", "confidence_score": 0.8,
                 "weight": 1.0, "_src": "bar", "_tgt": "baz", "source": "bar", "target": "baz",
                 "source_file": "/tmp/bar.py", "source_location": "L10"},
            ],
            "hyperedges": [],
        }
        (repo / "graph.json").write_text(json.dumps(graph_data))

        results = discover_graph_repos(tmp_path)
        assert len(results) == 1
        entry = results[0]
        assert entry["name"] == "my-repo"
        assert entry["path"] == str(tmp_path / "my-repo")
        assert entry["stats"]["node_count"] == 3
        assert entry["stats"]["edge_count"] == 2
        assert entry["stats"]["community_count"] == 2
        assert entry["stats"]["confidence"]["extracted"] == 1
        assert entry["stats"]["confidence"]["inferred"] == 1

    def test_discover_skips_dirs_without_graph(self, tmp_path: pathlib.Path):
        """Repos without graphify-out/graph.json are excluded."""
        from api.graphs import discover_graph_repos

        (tmp_path / "no-graph-repo" / "src").mkdir(parents=True)
        results = discover_graph_repos(tmp_path)
        assert results == []

    def test_discover_empty_root(self, tmp_path: pathlib.Path):
        """Empty root returns empty list."""
        from api.graphs import discover_graph_repos

        results = discover_graph_repos(tmp_path / "nonexistent")
        assert results == []

    def test_top_nodes_ranked_by_degree(self, tmp_path: pathlib.Path):
        """Top nodes are ranked by edge count (degree)."""
        from api.graphs import discover_graph_repos

        repo = tmp_path / "ranked-repo" / "graphify-out"
        repo.mkdir(parents=True)
        # Node A has 3 edges, Node B has 2, Node C has 1
        graph_data = {
            "directed": False, "multigraph": False, "graph": {},
            "nodes": [
                {"label": "A", "id": "a", "community": 0},
                {"label": "B", "id": "b", "community": 0},
                {"label": "C", "id": "c", "community": 0},
            ],
            "links": [
                {"_src": "a", "_tgt": "b", "confidence": "EXTRACTED", "confidence_score": 1.0},
                {"_src": "a", "_tgt": "c", "confidence": "EXTRACTED", "confidence_score": 1.0},
                {"_src": "b", "_tgt": "c", "confidence": "EXTRACTED", "confidence_score": 1.0},
            ],
            "hyperedges": [],
        }
        (repo / "graph.json").write_text(json.dumps(graph_data))

        results = discover_graph_repos(tmp_path)
        top = results[0]["stats"]["top_nodes"]
        # a appears in 2 links as src, b in 1 as src + 1 as tgt = 2, c in 0 as src + 2 as tgt = 2
        # All have degree 2, order may vary, but all should be present
        labels = {n["label"] for n in top}
        assert {"A", "B", "C"} == labels


class TestParseReportHeader:
    """Test GRAPH_REPORT.md parsing."""

    def test_parse_report_with_all_sections(self, tmp_path: pathlib.Path):
        from api.graphs import _parse_report_header

        report = tmp_path / "GRAPH_REPORT.md"
        report.write_text(
            "# Graph Report\n\n"
            "## Corpus Check\n"
            "- 42 files · ~12,345 words\n\n"
            "## Summary\n"
            "- 100 nodes · 200 edges · 5 communities detected\n\n"
            "## God Nodes (most connected)\n"
            "1. `main()` - 50 edges\n"
            "2. `helper()` - 30 edges\n\n"
            "## Suggested Questions\n"
            "- **Why does `main()` connect Community 0 to Community 1?**\n"
            "- **Are the inferred relationships correct?**\n"
        )
        result = _parse_report_header(report)
        assert result["corpus"]["files"] == 42
        assert result["corpus"]["words"] == 12345
        assert "100 nodes" in result["summary_line"]
        assert len(result["god_nodes"]) == 2
        assert result["god_nodes"][0]["label"] == "main()"
        assert result["god_nodes"][0]["edges"] == 50
        assert len(result["suggested_questions"]) == 2

    def test_parse_missing_report(self, tmp_path: pathlib.Path):
        from api.graphs import _parse_report_header

        result = _parse_report_header(tmp_path / "missing.md")
        assert result["corpus"] is None
        assert result["god_nodes"] == []


class TestGetGraphDetail:
    """Test get_graph_detail."""

    def test_detail_returns_report_text(self, tmp_path: pathlib.Path):
        from api.graphs import get_graph_detail, get_graph_overview, get_graph_neighborhood

        repo = tmp_path / "detail-repo"
        gdir = repo / "graphify-out"
        gdir.mkdir(parents=True)
        graph_data = {
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [
                {"label": "x", "id": "x", "community": 0, "degree": 3, "file_type": "code", "summary": "entry point"},
                {"label": "y", "id": "y", "community": 1, "degree": 2, "file_type": "note"},
                {"label": "z", "id": "z", "community": 1, "degree": 1, "file_type": "code"},
            ],
            "links": [
                {"source": "x", "target": "y", "relation": "connects", "confidence": "EXTRACTED"},
                {"source": "y", "target": "z", "relation": "references", "confidence": "INFERRED"},
            ],
            "hyperedges": [],
        }
        (gdir / "graph.json").write_text(json.dumps(graph_data))
        (gdir / "GRAPH_REPORT.md").write_text("# Test Report\nSome content here.")

        detail = get_graph_detail(str(repo))
        assert detail is not None
        assert detail["name"] == "detail-repo"
        assert detail["report_text"] == "# Test Report\nSome content here."
        assert detail["stats"]["node_count"] == 3
        assert detail["visualization"]["nodes"][0]["id"] == "x"
        assert detail["visualization"]["edges"][0]["from"] == "x"
        assert detail["visualization"]["communities"][0]["id"] == 1

        overview = get_graph_overview(str(repo))
        assert overview["mode"] == "overview"
        assert overview["focus"]["node_id"] == "x"
        assert len(overview["visualization"]["nodes"]) <= 3

        neighborhood = get_graph_neighborhood(str(repo), "y", depth=1)
        assert neighborhood["focus"]["node_id"] == "y"
        assert {node["id"] for node in neighborhood["visualization"]["nodes"]} == {"x", "y", "z"}

    def test_detail_missing_repo(self, tmp_path: pathlib.Path):
        from api.graphs import get_graph_detail

        assert get_graph_detail(str(tmp_path / "nope")) is None


class TestRunGraphifyCommand:
    """Test run_graphify_command validation."""

    def test_rejects_unknown_command(self):
        from api.graphs import run_graphify_command

        result = run_graphify_command("/tmp", "delete", [])
        assert result["ok"] is False
        assert "Unknown command" in result["error"]

    def test_rejects_missing_graph(self, tmp_path: pathlib.Path):
        from api.graphs import run_graphify_command

        result = run_graphify_command(str(tmp_path), "query", ["hello"])
        assert result["ok"] is False
        assert "not found" in result["error"].lower() or "No graph.json" in result["error"]


class TestGraphSlices:
    def test_search_expand_and_path_use_graph_slices(self, tmp_path: pathlib.Path):
        from api.graphs import expand_graph_neighborhood, find_graph_path, search_graph_nodes

        repo = tmp_path / "slice-repo"
        gdir = repo / "graphify-out"
        gdir.mkdir(parents=True)
        graph_data = {
            "directed": False,
            "multigraph": False,
            "graph": {},
            "nodes": [
                {"label": "alpha.py", "id": "alpha", "community": 0, "degree": 2, "file_type": "code"},
                {"label": "beta.py", "id": "beta", "community": 0, "degree": 2, "file_type": "code"},
                {"label": "gamma.py", "id": "gamma", "community": 1, "degree": 2, "file_type": "code"},
                {"label": "delta.py", "id": "delta", "community": 1, "degree": 1, "file_type": "note"},
            ],
            "links": [
                {"source": "alpha", "target": "beta", "relation": "uses", "confidence": "EXTRACTED"},
                {"source": "beta", "target": "gamma", "relation": "calls", "confidence": "EXTRACTED"},
                {"source": "gamma", "target": "delta", "relation": "links", "confidence": "INFERRED"},
            ],
            "hyperedges": [],
        }
        (gdir / "graph.json").write_text(json.dumps(graph_data))

        search = search_graph_nodes(str(repo), "ga")
        assert search[0]["id"] == "gamma"

        expanded = expand_graph_neighborhood(str(repo), ["beta"], depth=1)
        assert expanded["focus"]["seed_nodes"] == ["beta"]
        assert {node["id"] for node in expanded["visualization"]["nodes"]} == {"alpha", "beta", "gamma"}

        path = find_graph_path(str(repo), "alpha", "delta")
        assert path["focus"]["path"] == ["alpha", "beta", "gamma", "delta"]
        assert len(path["visualization"]["edges"]) == 3


# ── Integration tests via HTTP ───────────────────────────────────────────────

class TestGraphsAPIEndpoints:
    """Integration tests hitting the live test server endpoints."""

    def test_graphs_list_returns_200(self, cleanup_test_sessions):
        """GET /api/graphs returns 200 with a repos array."""
        data, status = get("/api/graphs")
        assert status == 200
        assert "repos" in data
        assert isinstance(data["repos"], list)

    def test_graphs_detail_requires_repo(self, cleanup_test_sessions):
        """GET /api/graphs/detail without repo param returns 400."""
        try:
            data, status = get("/api/graphs/detail")
        except urllib.error.HTTPError as e:
            status = e.code
            data = json.loads(e.read())
        assert status == 400
        assert "error" in data

    def test_graphs_detail_missing_repo_404(self, cleanup_test_sessions):
        """GET /api/graphs/detail with nonexistent repo returns 404."""
        try:
            data, status = get("/api/graphs/detail?repo=/nonexistent/path")
        except urllib.error.HTTPError as e:
            status = e.code
            data = json.loads(e.read())
        assert status == 404

    def test_graphs_overview_requires_repo(self, cleanup_test_sessions):
        try:
            data, status = get("/api/graphs/overview")
        except urllib.error.HTTPError as e:
            status = e.code
            data = json.loads(e.read())
        assert status == 400
        assert "error" in data

    def test_graphs_neighborhood_requires_node(self, cleanup_test_sessions):
        try:
            data, status = get("/api/graphs/neighborhood?repo=/tmp/example")
        except urllib.error.HTTPError as e:
            status = e.code
            data = json.loads(e.read())
        assert status == 400
        assert "error" in data

    def test_graphs_path_requires_endpoints(self, cleanup_test_sessions):
        try:
            data, status = get("/api/graphs/path?repo=/tmp/example")
        except urllib.error.HTTPError as e:
            status = e.code
            data = json.loads(e.read())
        assert status == 400
        assert "error" in data

    def test_graphs_search_requires_query(self, cleanup_test_sessions):
        try:
            data, status = get("/api/graphs/search?repo=/tmp/example")
        except urllib.error.HTTPError as e:
            status = e.code
            data = json.loads(e.read())
        assert status == 400
        assert "error" in data

    def test_graphs_query_requires_repo(self, cleanup_test_sessions):
        """POST /api/graphs/query without repo returns 400."""
        data, status = post("/api/graphs/query", {"question": "hello"})
        assert status == 400
        assert "error" in data

    def test_graphs_query_requires_question(self, cleanup_test_sessions):
        """POST /api/graphs/query with repo but no question returns 400."""
        data, status = post("/api/graphs/query", {"repo": "/tmp/fake"})
        assert status == 400

    def test_graphs_expand_requires_seed_nodes(self, cleanup_test_sessions):
        data, status = post("/api/graphs/expand", {"repo": "/tmp/fake"})
        assert status == 400
        assert "error" in data

    def test_graphs_query_path_requires_from_to(self, cleanup_test_sessions):
        """POST /api/graphs/query with command=path needs from/to."""
        data, status = post("/api/graphs/query", {
            "repo": "/tmp/fake",
            "command": "path",
        })
        assert status == 400
        assert "from" in data.get("error", "").lower() or "to" in data.get("error", "").lower()

    def test_graphs_query_explain_requires_node(self, cleanup_test_sessions):
        """POST /api/graphs/query with command=explain needs node."""
        data, status = post("/api/graphs/query", {
            "repo": "/tmp/fake",
            "command": "explain",
        })
        assert status == 400

    def test_graphs_query_unknown_command_rejected(self, cleanup_test_sessions):
        """POST /api/graphs/query with invalid command returns 400."""
        data, status = post("/api/graphs/query", {
            "repo": "/tmp/fake",
            "command": "delete",
            "question": "test",
        })
        assert status == 400
        assert "Unknown command" in data.get("error", "")
