from __future__ import annotations

import json

from apps.api.boards import import_boards_from_json, load_runtime_boards
from apps.api.config import Settings
from apps.api.models import Board
from collectors.ats_adapters.config import load_board_entries, set_runtime_boards


def test_load_runtime_boards_only_enabled(session):
    session.add_all(
        [
            Board(provider="greenhouse", board_token="acme", enabled=True),
            Board(provider="greenhouse", board_token="off", enabled=False),
            Board(
                provider="workday",
                board_token="nvidia",
                config={"tenant": "nvidia", "host": "wd5", "site": "Board"},
                enabled=True,
            ),
        ]
    )
    session.commit()

    grouped = load_runtime_boards(session)
    assert [entry["token"] for entry in grouped["greenhouse"]] == ["acme"]
    assert grouped["workday"][0]["tenant"] == "nvidia"
    assert grouped["workday"][0]["site"] == "Board"


def test_runtime_boards_override(monkeypatch):
    set_runtime_boards({"greenhouse": [{"token": "runtime"}]})
    try:
        assert load_board_entries(Settings(), "greenhouse") == [{"token": "runtime"}]
    finally:
        set_runtime_boards(None)
    # Falls back to the JSON file once cleared.
    assert isinstance(load_board_entries(Settings(), "greenhouse"), list)


def test_import_boards_from_json(session, tmp_path):
    path = tmp_path / "ats.json"
    path.write_text(
        json.dumps(
            {"greenhouse": ["acme"], "workday": [{"tenant": "nvidia", "host": "wd5", "site": "X"}]}
        ),
        encoding="utf-8",
    )
    settings = Settings(ats_companies_file=str(path))
    assert import_boards_from_json(session, settings) == 2
    assert import_boards_from_json(session, settings) == 0  # idempotent
