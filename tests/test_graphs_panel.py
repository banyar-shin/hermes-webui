"""Static markup / CSS / JS tests for the Graphs dashboard panel."""

import pathlib

REPO = pathlib.Path(__file__).parent.parent


def read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


# ── HTML tests ──────────────────────────────────────────────────────────────


def test_index_contains_graphs_nav_tab():
    html = read("static/index.html")
    assert 'data-panel="graphs"' in html
    assert "switchPanel('graphs')" in html
    assert 'data-i18n-title="tab_graphs"' in html


def test_index_contains_graphs_panel_view():
    html = read("static/index.html")
    assert 'id="panelGraphs"' in html
    assert 'id="graphPanel"' in html
    assert 'id="graphRepoList"' in html
    assert 'id="graphDetail"' in html
    assert 'id="graphQueryInput"' in html
    assert 'id="graphSendBtn"' in html
    assert 'id="graphResults"' in html


def test_index_contains_graph_workspace_shell():
    html = read("static/index.html")
    assert 'id="graphWorkspace"' in html
    assert 'id="graphMainCanvas"' in html
    assert 'id="graphModeTabs"' in html
    assert 'id="graphSearchInput"' in html
    assert 'id="graphExpandBtn"' in html
    assert 'id="graphPathBtn"' in html


def test_index_has_graph_detail_sections():
    html = read("static/index.html")
    assert 'id="graphNodeList"' in html
    assert 'id="graphChipTray"' in html
    assert 'id="graphDetailHeader"' in html
    assert 'id="graphBackBtn"' in html


def test_index_contains_interactive_graph_view_shell():
    html = read("static/index.html")
    assert 'id="graphCanvasSection"' in html
    assert 'id="graphCanvas"' in html
    assert 'id="graphLegend"' in html
    assert 'id="graphInspector"' in html


# ── CSS tests ───────────────────────────────────────────────────────────────


def test_graph_css_rules_exist():
    css = read("static/style.css")
    for selector in (
        ".graph-panel",
        ".graph-repo-card",
        ".graph-detail",
        ".graph-app-shell",
        ".graph-sidebar-stack",
        ".graph-workspace",
        ".graph-main-canvas",
        ".graph-mode-tabs",
        ".graph-mode-tab",
        ".graph-canvas-shell",
        ".graph-canvas",
        ".graph-legend",
        ".graph-inspector",
        ".graph-node-item",
        ".graph-node-rank",
        ".graph-chip",
        ".graph-composer",
        ".graph-send-btn",
        ".graph-result-card",
        ".graph-result-loading",
        ".graph-spinner",
        "@keyframes graph-spin",
        ".graph-empty",
    ):
        assert selector in css, f"Missing CSS rule: {selector}"


def test_graph_css_light_mode_overrides():
    css = read("static/style.css")
    assert ":root:not(.dark) .graph-repo-card" in css
    assert ":root:not(.dark) .graph-chip" in css


# ── JavaScript tests ────────────────────────────────────────────────────────


def test_panels_js_registers_graphs_in_switch():
    js = read("static/panels.js")
    assert "if (name === 'graphs') await loadGraphs()" in js


def test_panels_js_exposes_graph_functions():
    js = read("static/panels.js")
    for fn in (
        "async function loadGraphs()",
        "function _renderGraphRepoList(",
        "async function selectGraphRepo(",
        "async function _loadGraphOverview(",
        "async function _loadGraphNeighborhood(",
        "async function expandSelectedGraphNode(",
        "async function searchGraphNodes(",
        "async function loadGraphPathBetweenTopNodes(",
        "function _renderGraphVisualization(",
        "function _buildGraphTheme(",
        "function _renderGraphTopNodes(",
        "function _renderGraphSuggestions(",
        "function graphBackToList()",
        "async function submitGraphQuery()",
    ):
        assert fn in js, f"Missing function: {fn}"


def test_panels_js_calls_graph_api_endpoints():
    js = read("static/panels.js")
    assert "api('/api/graphs')" in js
    assert "api(`/api/graphs/detail?repo=${encodeURIComponent(repoId)}&lite=1`)" in js
    assert "api(`/api/graphs/overview?repo=${encodeURIComponent(repoId)}`)" in js
    assert "api(`/api/graphs/neighborhood?repo=${encodeURIComponent(repoId)}&node=${encodeURIComponent(nodeId)}&depth=${depth}`)" in js
    assert "api(`/api/graphs/search?repo=${encodeURIComponent(repoId)}&q=${encodeURIComponent(query)}`)" in js
    assert "api(`/api/graphs/path?repo=${encodeURIComponent(repoId)}&from=${encodeURIComponent(fromId)}&to=${encodeURIComponent(toId)}`)" in js
    assert "api('/api/graphs/expand'" in js
    assert "api('/api/graphs/query'" in js


def test_panels_js_graph_query_sends_post():
    js = read("static/panels.js")
    # Ensure the query call uses POST with JSON body
    assert "method: 'POST'" in js
    assert "JSON.stringify({ repository:" in js or "JSON.stringify({repository:" in js


# ── i18n tests ──────────────────────────────────────────────────────────────


def test_i18n_has_graph_keys_english():
    i18n = read("static/i18n.js")
    for key in (
        "tab_graphs:",
        "graphs_title:",
        "graphs_no_repos:",
        "graphs_top_nodes:",
        "graphs_suggestions:",
        "graphs_ask:",
        "graphs_query_placeholder:",
        "graphs_send:",
        "graphs_querying:",
        "graphs_nodes:",
        "graphs_edges:",
    ):
        assert key in i18n, f"Missing i18n key: {key}"


def test_i18n_has_graph_keys_spanish():
    i18n = read("static/i18n.js")
    assert "tab_graphs: 'Grafos'" in i18n


def test_i18n_has_graph_keys_german():
    i18n = read("static/i18n.js")
    assert "tab_graphs: 'Graphen'" in i18n


# ── Icons tests ─────────────────────────────────────────────────────────────


def test_icons_has_graph_entries():
    icons = read("static/icons.js")
    assert "'network'" in icons
    assert "'git-branch'" in icons
    assert "'sparkles'" in icons
