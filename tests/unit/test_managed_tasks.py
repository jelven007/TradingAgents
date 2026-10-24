import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from tradingagents.application import runs
from tradingagents.application.worker import BudgetCallback, run_one
from tradingagents.domain.tasks import TaskInput
from tradingagents.infrastructure.tasks import BudgetExceeded, LeaseLost, TaskStore


def payload(**limits):
    return TaskInput.model_validate({
        "workspace": "research", "experiment": "baseline", "config": {},
        "mandate": {"ticker": "NVDA", "analysis_date": "2026-01-09", "benchmark": "SPY",
                    "prediction_horizon_trading_days": 5, "quote_currency": "USD",
                    "valid_until": "2099-01-01"}, "limits": limits,
    })


def test_concurrent_submit_claim_and_scoped_idempotency(tmp_path):
    store = TaskStore(tmp_path / "db")
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: store.submit(payload(), "author", "same"), range(16)))
        assert len(set(ids)) == 1
        claims = list(pool.map(lambda i: store.claim(str(i)), range(16)))
    assert sum(c is not None for c in claims) == 1
    assert store.get(ids[0])["attempt_count"] == 1
    assert store.submit(payload(), "other", "same") != ids[0]
    with pytest.raises(ValueError, match="conflicts"):
        store.submit(payload(max_calls=1), "author", "same")


def test_expired_attempt_fenced_and_budget_survives_reclaim(tmp_path):
    now = [100.0]
    store = TaskStore(tmp_path / "db", clock=lambda: now[0])
    task = store.submit(payload(max_calls=1), "author", "x")
    first = store.claim("w", lease_seconds=5)
    store.reserve_call(task, first["attempt"], "call", "test-model")
    now[0] = 106
    second = store.claim("w2", lease_seconds=5)
    assert first["attempt"] != second["attempt"]
    for action in (lambda: store.heartbeat(task, first["attempt"]),
                   lambda: store.fail(task, first["attempt"], "old"),
                   lambda: store.reserve_call(task, first["attempt"], "late", "model")):
        with pytest.raises(LeaseLost):
            action()
    with pytest.raises(BudgetExceeded):
        store.reserve_call(task, second["attempt"], "new", "model")
    call = store.get(task)["calls"][0]
    assert call["status"] == "unknown" and call["actual_microusd"] is None
    assert call["reserved_microusd"] > 0
    now[0] = 112
    assert store.claim("third") is None
    assert store.get(task)["status"] == "failed"


def test_concurrent_budget_reservation_and_model_callback_fail_closed(tmp_path):
    store = TaskStore(tmp_path / "db")
    task = store.submit(payload(max_calls=3), "author", "x")
    row = store.claim("w")
    callback = BudgetCallback(store, task, row["attempt"])
    model = FakeListChatModel(responses=["one"], callbacks=[callback])

    def invoke(_):
        try:
            model.invoke("input")
            return True
        except BudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(invoke, range(12)))
    assert sum(results) == 3
    calls = store.get(task)["calls"]
    assert len(calls) == 3 and all(c["status"] == "returned" for c in calls)
    assert all(c["actual_microusd"] is None for c in calls)
    assert store.get(task)["error_type"] == "BudgetExceeded"


def test_money_reservation_and_cancel_keep_usage(tmp_path):
    store = TaskStore(tmp_path / "db")
    task = store.submit(payload(budget_microusd=6, reserve_per_call_microusd=4), "author", "x")
    row = store.claim("w")
    store.reserve_call(task, row["attempt"], "call", "model")
    with pytest.raises(BudgetExceeded):
        store.reserve_call(task, row["attempt"], "other", "model")
    store.cancel(task, "operator")
    store.finish_call("call", usage={"input_tokens": 7, "output_tokens": 2, "secret": "never"})
    result = store.get(task)
    assert result["status"] == "cancelled" and len(result["calls"]) == 1
    assert "secret" not in result["calls"][0]["usage"]
    with pytest.raises(LeaseLost):
        store.heartbeat(task, row["attempt"])
    assert store.claim("next") is None


def test_concurrency_and_deadline_are_global_and_do_not_reset(tmp_path):
    now = [100.0]
    store = TaskStore(tmp_path / "db", clock=lambda: now[0])
    first = store.submit(payload(max_seconds=10), "a", "first")
    store.claim("w1", max_concurrency=1, lease_seconds=5)
    second = store.submit(payload(), "a", "second")
    assert store.claim("w2", max_concurrency=1) is None
    now[0] = 106
    store.reap()
    assert store.get(first)["status"] == "queued"
    now[0] = 111
    assert store.claim("w2")["id"] == second
    assert store.get(first)["status"] == "timed_out"


def _hang(db_path, root, task_id, attempt):
    store = TaskStore(Path(db_path))
    store.reserve_call(task_id, attempt, "started-before-timeout", "offline-hanging-provider")
    time.sleep(10)
    Path(root, "must-not-write").write_text("late")


def _crash(db_path, root, task_id, attempt):
    raise RuntimeError("scripted child failure")


@pytest.mark.parametrize(("target", "limits", "status"), [
    (_hang, {"max_seconds": 2}, "timed_out"), (_crash, {}, "failed"),
])
def test_spawned_worker_terminates_hang_or_records_crash(tmp_path, target, limits, status):
    store = TaskStore(tmp_path / "db")
    task = store.submit(payload(**limits), "author", "x")
    started = time.monotonic()
    assert run_one(store, tmp_path, "w", poll_seconds=0.1, process_target=target) == task
    assert time.monotonic() - started < 8
    assert store.get(task)["status"] == status
    assert not (tmp_path / "must-not-write").exists()
    if target is _hang:
        assert store.get(task)["calls"][0]["actual_microusd"] is None
        assert store.get(task)["calls"][0]["status"] == "unknown"


def test_task_input_is_frozen_and_version_change_fails_before_graph(tmp_path):
    source = {"workspace": "research", "experiment": "test", "config": {"secret": "original"},
              "mandate": payload().mandate.model_dump()}
    store = TaskStore(tmp_path / "db")
    task = store.submit(TaskInput.model_validate(source), "author", "key")
    source["config"]["secret"] = "changed"
    row = store.get(task)
    assert row["payload"]["config"]["secret"] == "original"
    wrong_version = {**row["implementation"], "source_sha256": "changed"}
    path = runs.RunScope("research", "test", task, "attempt").path(tmp_path)
    with pytest.raises(ValueError, match="implementation changed"):
        runs.execute_research(tmp_path, runs.RunScope("research", "test", task, "attempt"),
                              payload().mandate, row["payload"]["config"],
                              expected_implementation=wrong_version)
    assert not path.exists()
