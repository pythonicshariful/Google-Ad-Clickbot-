import json
import threading

import app


def test_bot_worker_reloads_keywords_from_disk_each_cycle(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "proxy": {"host": "pr.oxylabs.io", "port": 7777, "username": "user", "password": "pass", "country": "GB", "city": "cheltenham", "enabled": True},
            "search": {"cycle_interval_minutes": 0, "keywords": ["old keyword"]},
            "browser": {"headless": True, "window_width": 1366, "window_height": 768},
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(app, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(app, "stop_event", threading.Event())
    app.stop_event.clear()
    monkeypatch.setattr(app, "write_last_run_info", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "append_session_summary", lambda *args, **kwargs: None)

    seen = []

    def fake_run_cycle(config, logger, cycle_number, use_proxy=True):
        seen.append(list(config["search"]["keywords"]))
        if cycle_number == 1:
            updated = json.loads(config_path.read_text(encoding="utf-8"))
            updated["search"]["keywords"] = ["new keyword"]
            config_path.write_text(json.dumps(updated), encoding="utf-8")
        else:
            app.stop_event.set()
        return 1

    monkeypatch.setattr(app, "run_cycle", fake_run_cycle)
    monkeypatch.setattr(app.time, "sleep", lambda *_args, **_kwargs: None)

    app.bot_worker(use_proxy=False)

    assert seen == [["old keyword"], ["new keyword"]]
