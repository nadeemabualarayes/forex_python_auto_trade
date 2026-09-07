"""End-to-end dry run of the live loop against the fake terminal (no Telegram, no MT5)."""
import simulate


def test_scenario_drives_every_subsystem(tmp_path):
    result = simulate.run_simulation(send_real_telegram=False, log_dir=str(tmp_path))

    events = [(e["event"], e["note"]) for e in result["journal"]]
    kinds = [e[0] for e in events]

    assert kinds.count("ENTRY") == 3
    assert kinds.count("EXIT") == 3
    assert ("SL_MOVE", "BREAKEVEN") in events
    assert ("SL_MOVE", "TRAIL") in events
    exits = [note.split(" @ ")[0] for kind, note in events if kind == "EXIT"]
    assert exits == ["TP", "SL", "SL"]
    # entry -> stop moves -> exit ordering for the first trade
    assert kinds.index("ENTRY") < kinds.index("SL_MOVE") < kinds.index("EXIT")

    msgs = "\n".join(result["telegram"])
    for needle in ("Trade Opened", "Trade Closed", "circuit breaker", "Heartbeat", "Daily summary"):
        assert needle in msgs, needle
    assert all(m.startswith(simulate.PREFIX) for m in result["telegram"])
    assert result["breaker_tripped"]


def test_random_path_stops_after_requested_trades(tmp_path):
    result = simulate.run_simulation(send_real_telegram=False, log_dir=str(tmp_path), trades=4, seed=1)

    outs = [d for d in result["deals"] if d.entry == simulate._real_mt5.DEAL_ENTRY_OUT]
    assert len(outs) == 4
    kinds = [e["event"] for e in result["journal"]]
    assert kinds.count("EXIT") == 4
    assert kinds.count("ENTRY") >= 4
    # deterministic for a fixed seed
    again = simulate.run_simulation(send_real_telegram=False, log_dir=str(tmp_path / "b"), trades=4, seed=1)
    assert [d.profit for d in again["deals"]] == [d.profit for d in result["deals"]]


def test_random_path_can_run_both_engines(tmp_path):
    import config
    result = simulate.run_simulation(send_real_telegram=False, log_dir=str(tmp_path), trades=4, seed=1, london=True)
    assert result["engines"] == ["scalper", "london"]
    magics = {d.magic for d in result["deals"]}
    assert config.MAGIC_NUMBER in magics                    # scalper still trades
    assert magics <= {config.MAGIC_NUMBER, config.LDN_MAGIC_NUMBER}
    outs = [d for d in result["deals"] if d.entry == simulate._real_mt5.DEAL_ENTRY_OUT]
    assert len(outs) >= 4                                   # two engines may close on the same bar


def test_default_run_keeps_the_scalper_alone(tmp_path):
    result = simulate.run_simulation(send_real_telegram=False, log_dir=str(tmp_path))
    assert result["engines"] == ["scalper"]
