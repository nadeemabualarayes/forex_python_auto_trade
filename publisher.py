"""Publish the dashboard + latest status.json to a one-commit `gh-pages` branch for GitHub Pages.

The bot keeps a small staging repo under logs/pages/, amends its single commit on every
publish and force-pushes it, so the main branch history stays clean. Pushes run on a
daemon thread so a slow network never stalls the trading loop.
"""
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime

import config
from journal import log

ROOT = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(ROOT, "web", "index.html")
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}     # fail instead of prompting for a password


def stage_site(stage_dir: str, status: dict) -> None:
    """Write index.html, status.json and .nojekyll into stage_dir."""
    os.makedirs(stage_dir, exist_ok=True)
    shutil.copyfile(INDEX_HTML, os.path.join(stage_dir, "index.html"))
    with open(os.path.join(stage_dir, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, default=str)
    open(os.path.join(stage_dir, ".nojekyll"), "a").close()


def origin_url() -> str | None:
    r = subprocess.run(["git", "-C", ROOT, "remote", "get-url", "origin"], capture_output=True, text=True)
    return r.stdout.strip() or None


class PagesPublisher:
    def __init__(self, remote: str | None = None, stage_dir: str | None = None,
                 interval: float | None = None, branch: str | None = None):
        self.remote = remote or config.PAGES_REMOTE or origin_url()
        self.stage_dir = stage_dir or os.path.join(config.LOG_DIR, "pages")
        self.interval = config.PAGES_PUBLISH_SECONDS if interval is None else interval
        self.branch = branch or config.PAGES_BRANCH
        self.last_attempt: float | None = None       # time.monotonic()
        self.last_ok: datetime | None = None
        self._thread: threading.Thread | None = None

    # -- scheduling --------------------------------------------------------------
    def maybe_publish(self, status: dict, now_mono: float | None = None) -> bool:
        """Start a background publish if the interval has elapsed. Returns True when one was started."""
        now = time.monotonic() if now_mono is None else now_mono
        if self.last_attempt is not None and now - self.last_attempt < self.interval:
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self.last_attempt = now
        self._thread = threading.Thread(target=self.publish, args=(status,), name="pages", daemon=True)
        self._thread.start()
        return True

    def join(self, timeout: float = 30.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    # -- the work ----------------------------------------------------------------
    def publish(self, status: dict) -> bool:
        """Synchronous: stage, commit (amend), force-push. Never raises."""
        if not self.remote:
            log.warning("pages: no remote configured, skipping")
            return False
        try:
            stage_site(self.stage_dir, status)
            self._git_push()
            self.last_ok = datetime.now()
            log.info("pages: published to %s (%s)", self.remote, self.branch)
            return True
        except subprocess.TimeoutExpired:
            log.warning("pages: git timed out, will retry next interval")
        except subprocess.CalledProcessError as e:
            log.warning("pages: git failed: %s", (e.stderr or e.stdout or "").strip()[-400:])
        except Exception as e:
            log.warning("pages: publish failed: %s", e)
        return False

    def _git(self, *args, timeout: float = 60.0) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", self.stage_dir, *args], capture_output=True, text=True,
                              check=True, timeout=timeout, env=GIT_ENV)

    def _git_push(self) -> None:
        if not os.path.isdir(os.path.join(self.stage_dir, ".git")):
            self._git("init", "-q")
            self._git("symbolic-ref", "HEAD", f"refs/heads/{self.branch}")
        self._git("add", "-A")
        has_head = subprocess.run(["git", "-C", self.stage_dir, "rev-parse", "-q", "--verify", "HEAD"],
                                  capture_output=True).returncode == 0
        msg = f"status {datetime.now():%Y-%m-%d %H:%M:%S}"
        commit = ["-c", "user.name=forex-bot", "-c", "user.email=forex-bot@localhost",
                  "commit", "-q", "--allow-empty", "-m", msg]
        if has_head:
            commit.append("--amend")
        self._git(*commit)
        self._git("push", "-q", "--force", self.remote, f"HEAD:refs/heads/{self.branch}", timeout=120.0)
