import pytest

"""Tests for the dashboard<->engine conversion in server.py.

These don't need FastAPI installed — to_engine_profile / dashboard_coherence
live at module level and only touch the engine core.
"""

from persona import validate
from persona.server import to_engine_profile, dashboard_coherence


BASE = {
    "id": "abc123",
    "name": "Test",
    "os": "Windows",
    "screen": "1920x1080",
    "cores": 8,
    "memory": 16,
    "webglRenderer": "ANGLE (NVIDIA GeForce RTX 3060 Direct3D11)",
    "locale": "en-US",
    "timezone": "America/New_York",
    "browserVersion": "128.0.0.0",
    "userAgent": "Mozilla/5.0 test",
}


def test_converts_os_and_screen():
    fp = to_engine_profile(BASE).fingerprint
    assert fp.os == "windows"
    assert (fp.screen_width, fp.screen_height) == (1920, 1080)
    assert fp.viewport_height < fp.screen_height


def test_maps_gpu_to_real_engine_string():
    fp = to_engine_profile(BASE).fingerprint
    assert "RTX 3060" in fp.webgl_renderer
    assert fp.webgl_vendor.startswith("Google Inc.")


def test_converted_profile_is_coherent():
    # A well-formed dashboard profile must produce a launchable, valid fingerprint.
    assert validate(to_engine_profile(BASE).fingerprint) == []
    assert dashboard_coherence(BASE) == []


def test_proxy_is_converted():
    d = dict(BASE, proxy={"type": "SOCKS5", "host": "h.proxy.io", "port": "1080",
                          "user": "u", "pass": "p", "country": "US"})
    prof = to_engine_profile(d)
    assert prof.proxy is not None
    assert prof.proxy.server == "socks5://h.proxy.io:1080"
    assert prof.proxy.username == "u"


def test_validate_tolerates_missing_id():
    d = {k: v for k, v in BASE.items() if k != "id"}
    # should not raise even without an id (used by the /validate endpoint)
    assert isinstance(dashboard_coherence(d), list)


def test_legacy_dashboard_gpu_labels_become_real_renderer_strings():
    # Labels older dashboards wrote are not what any Chrome reports.
    d = dict(BASE, webglRenderer="ANGLE (NVIDIA GeForce RTX 3060 Direct3D11)",
             webglVendor="Google Inc. (NVIDIA)")
    fp = to_engine_profile(d).fingerprint
    assert fp.webgl_renderer == "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"
    mac = dict(BASE, os="macOS", webglRenderer="ANGLE (Apple M1, OpenGL 4.1)",
               webglVendor="Google Inc. (NVIDIA)")      # stale vendor from an OS switch
    fp = to_engine_profile(mac).fingerprint
    assert fp.webgl_renderer.startswith("ANGLE (Apple, ANGLE Metal Renderer: Apple M1")
    assert fp.webgl_vendor == "Google Inc. (Apple)"


def test_folder_crud_and_rename_edge_cases(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from persona.server import TOKEN_HEADER, create_app

    app = create_app(data_dir=str(tmp_path), start_scheduler=False)
    client = TestClient(app, base_url="http://localhost",
                        headers={TOKEN_HEADER: app.state.api_token})

    # Check initial config has empty folders
    r = client.get("/api/config")
    assert r.status_code == 200
    assert r.json()["folders"] == []

    # POST /api/folders with {"name": "Alpha"} -> returns ["Alpha"]
    r = client.post("/api/folders", json={"name": "Alpha"})
    assert r.status_code == 200
    assert r.json()["folders"] == ["Alpha"]

    # POST /api/folders with {"name": "Beta"} -> returns ["Alpha", "Beta"]
    r = client.post("/api/folders", json={"name": "Beta"})
    assert r.status_code == 200
    assert r.json()["folders"] == ["Alpha", "Beta"]

    # POST /api/folders/rename with {"src": "Alpha", "dst": "AlphaRenamed"} -> returns ["AlphaRenamed", "Beta"]
    r = client.post("/api/folders/rename", json={"src": "Alpha", "dst": "AlphaRenamed"})
    assert r.status_code == 200
    assert r.json()["folders"] == ["AlphaRenamed", "Beta"]

    # POST /api/folders/rename with {"src": "Beta", "dst": "AlphaRenamed"} -> HTTP 409 conflict
    r = client.post("/api/folders/rename", json={"src": "Beta", "dst": "AlphaRenamed"})
    assert r.status_code == 409

    # POST /api/folders/rename with {"src": "Same", "dst": "Same"} -> returns current folders without error
    r = client.post("/api/folders/rename", json={"src": "Same", "dst": "Same"})
    assert r.status_code == 200
    assert r.json()["folders"] == ["AlphaRenamed", "Beta"]

    # POST /api/folders/rename with {"src": "GhostFolder", "dst": "NewFolder"} -> returns ["AlphaRenamed", "Beta", "NewFolder"]
    r = client.post("/api/folders/rename", json={"src": "GhostFolder", "dst": "NewFolder"})
    assert r.status_code == 200
    assert r.json()["folders"] == ["AlphaRenamed", "Beta", "NewFolder"]

    # DELETE /api/folders/Beta -> deletes folder properly
    r = client.delete("/api/folders/Beta")
    assert r.status_code == 200
    assert r.json()["folders"] == ["AlphaRenamed", "NewFolder"]
