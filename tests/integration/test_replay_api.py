from typing import Any

import pytest
from fastapi import HTTPException

import app.api.main as api


class FakeRepository:
    def __init__(self) -> None:
        self.saved: Any = None

    def save(self, result: Any, config: Any) -> None:
        self.saved = result

    def run(self, run_id: str) -> dict[str, object] | None:
        return (
            None
            if run_id == "missing"
            else {"run_id": run_id, "status": "COMPLETED", "performance": {"final_equity": 100}}
        )

    def trades(self, run_id: str) -> list[dict[str, object]]:
        return [{"run_id": run_id}]

    def equity(self, run_id: str) -> list[dict[str, object]]:
        return [{"run_id": run_id}]


def test_replay_api_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRepository()
    monkeypatch.setattr(api, "replay_repository", fake)
    created = api.create_replay(api.ReplayRequest(symbols=["RALLY"], initial_equity=100000))
    assert created["status"] == "COMPLETED" and fake.saved is not None
    assert api.get_replay("ok")["status"] == "COMPLETED"
    assert api.replay_trades("ok") and api.replay_equity("ok")
    assert api.replay_performance_endpoint("ok")["final_equity"] == 100
    with pytest.raises(HTTPException):
        api.get_replay("missing")
    with pytest.raises(HTTPException):
        api.create_replay(api.ReplayRequest(symbols=["UNKNOWN"]))
