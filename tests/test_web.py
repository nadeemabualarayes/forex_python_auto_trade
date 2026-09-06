"""StatusServer serves the page and the latest snapshot on a real socket (port 0 = any free port)."""
import json
import urllib.request

import pytest

from web import StatusServer


@pytest.fixture
def server():
    s = StatusServer(host="127.0.0.1", port=0)
    assert s.start()
    yield s
    s.stop()


def _get(server, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.bound_port}{path}", timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def test_serves_dashboard_html(server):
    status, ctype, body = _get(server, "/")
    assert status == 200 and ctype.startswith("text/html")
    assert b"status.json" in body                     # the page polls the JSON endpoint (relative path)


def test_status_json_reflects_latest_update(server):
    server.update({"market_open": True, "day": {"net_pnl": 3.5}, "positions": [], "traders": []})
    status, ctype, body = _get(server, "/status.json")
    assert status == 200 and ctype == "application/json"
    data = json.loads(body)
    assert data["day"]["net_pnl"] == 3.5
    assert data["trades"] == []                       # journal absent in tests -> empty list


def test_unknown_path_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(server, "/nope")
    assert exc.value.code == 404


def test_start_fails_cleanly_when_port_is_taken(server):
    other = StatusServer(host="127.0.0.1", port=server.bound_port)
    assert other.start() is False


def test_dashboard_scripts_parse(tmp_path):
    """A parse error in the inline script blanks the whole dashboard (it happened: duplicate const)."""
    import os, re, shutil, subprocess
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "index.html"), encoding="utf-8").read()
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    assert blocks, "no inline scripts found"
    for i, js in enumerate(blocks):
        p = tmp_path / f"block{i}.js"
        p.write_text(js, encoding="utf-8")
        r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
