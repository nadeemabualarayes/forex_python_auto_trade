"""Startup exit codes: Task Scheduler only restarts on a non-zero exit."""
import main


def test_run_returns_failure_code_when_mt5_init_fails(monkeypatch):
    monkeypatch.setattr(main, "init_mt5", lambda symbols: [])
    monkeypatch.setattr(main, "send_telegram", lambda *a, **k: None)
    assert main.run() == 1
