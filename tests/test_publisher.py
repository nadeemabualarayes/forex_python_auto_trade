"""PagesPublisher pushes a one-commit gh-pages branch; tested against a local bare repo as 'origin'."""
import json
import os
import subprocess
import time

import pytest

import config
from publisher import PagesPublisher, stage_site


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bare_remote(tmp_path):
    remote = tmp_path / "remote.git"
    _git("init", "-q", "--bare", str(remote), cwd=tmp_path)
    return str(remote)


def test_stage_site_writes_page_and_data(tmp_path):
    stage = tmp_path / "site"
    stage_site(str(stage), {"day": {"net_pnl": 1.0}, "trades": []})
    assert (stage / "index.html").exists()
    assert (stage / ".nojekyll").exists()
    assert json.loads((stage / "status.json").read_text())["day"]["net_pnl"] == 1.0


def test_publish_pushes_single_commit_branch(tmp_path, bare_remote, monkeypatch):
    monkeypatch.setattr(config, "PAGES_BRANCH", "gh-pages")
    pub = PagesPublisher(remote=bare_remote, stage_dir=str(tmp_path / "stage"), interval=0)
    assert pub.publish({"day": {"net_pnl": 2.5}}) is True
    assert pub.publish({"day": {"net_pnl": 3.5}}) is True          # second publish amends, not appends
    log = _git("log", "--oneline", "gh-pages", cwd=bare_remote)
    assert len(log.strip().splitlines()) == 1
    data = _git("show", "gh-pages:status.json", cwd=bare_remote)
    assert json.loads(data)["day"]["net_pnl"] == 3.5
    assert "index.html" in _git("ls-tree", "--name-only", "gh-pages", cwd=bare_remote)


def test_maybe_publish_respects_interval(tmp_path, bare_remote):
    pub = PagesPublisher(remote=bare_remote, stage_dir=str(tmp_path / "stage"), interval=3600)
    assert pub.maybe_publish({"a": 1}, now_mono=100.0) is True     # first call publishes immediately
    assert pub.maybe_publish({"a": 2}, now_mono=200.0) is False    # too soon
    pub.join()                                                     # let the first push finish
    assert pub.maybe_publish({"a": 3}, now_mono=100.0 + 3600) is True
    pub.join()


def test_publish_failure_is_reported_not_raised(tmp_path):
    pub = PagesPublisher(remote=str(tmp_path / "missing.git"), stage_dir=str(tmp_path / "stage"), interval=0)
    assert pub.publish({"a": 1}) is False
