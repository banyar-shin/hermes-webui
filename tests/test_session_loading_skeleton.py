from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSIONS_JS = (REPO_ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
STYLE_CSS = (REPO_ROOT / "static" / "style.css").read_text(encoding="utf-8")


def test_sessions_js_tracks_pending_selection_optimistically():
    assert "let _pendingSessionSelection=null;" in SESSIONS_JS
    assert "const activeSid=_pendingSessionSelection||(S.session&&S.session.session_id);" in SESSIONS_JS
    assert "(isPending?' loading':'')" in SESSIONS_JS


def test_sessions_js_shows_boneyard_loading_skeleton_before_fetch_resolves():
    assert "const SESSION_LOADING_BONES={" in SESSIONS_JS
    assert "const WORKSPACE_LOADING_BONES={" in SESSIONS_JS
    assert "function showSessionLoadingSkeleton(sessionMeta){" in SESSIONS_JS
    assert "_renderBoneyardSkeleton(messages, SESSION_LOADING_BONES, 'session-loading-shell');" in SESSIONS_JS
    assert "_renderBoneyardSkeleton(fileTree, WORKSPACE_LOADING_BONES, 'workspace-loading-shell');" in SESSIONS_JS


def test_sessions_js_ignores_stale_session_load_responses():
    assert "const requestSeq=++_sessionLoadRequestSeq;" in SESSIONS_JS
    assert "if(requestSeq!==_sessionLoadRequestSeq) return;" in SESSIONS_JS


def test_style_css_has_loading_sidebar_and_boneyard_rules():
    assert ".session-item.loading" in STYLE_CSS
    assert ".boneyard-skeleton" in STYLE_CSS
    assert ".boneyard-bone::after" in STYLE_CSS
    assert "@keyframes boneyard-shimmer" in STYLE_CSS
