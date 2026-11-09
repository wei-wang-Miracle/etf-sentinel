"""独立测试库验证单ETF策略版本、统一比较与快照复算。"""

import os
from copy import deepcopy
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from test_strategy_conditions import condition, rule

from app.collection import now
from app.db import Session
from app.main import app
from app.models import BacktestSource, Candle, Instrument, Job

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="需要独立测试库"
)
client = TestClient(app)
BODY = {
    "instrument_code": "510500",
    "start_date": "2026-06-03",
    "end_date": "2026-06-08",
    "initial_cash": "10000",
    "commission_rate": "0",
    "minimum_commission": "0",
    "slippage_bps": "0",
    "current": {"name": "测试均线", "rule": rule()},
    "version_ids": [],
}


@pytest.fixture(autouse=True)
def sample():
    """只清理独立测试库，准备可手算完整日历数据。"""
    with Session() as db:
        db.execute(
            text(
                "TRUNCATE instruments, sentiment_categories, accounts RESTART IDENTITY CASCADE"
            )
        )
        db.merge(Job(id=5, time="08:30", enabled=True))
        db.add_all(
            [
                Instrument(code="510500", name="测试ETF"),
                Instrument(code="512100", name="另只ETF"),
            ]
        )
        db.flush()
        for day, price in zip((1, 2, 3, 4, 5, 8), (10, 12, 11, 9, 11, 13)):
            db.add(
                Candle(
                    code="510500",
                    date=date(2026, 6, day),
                    open=price,
                    high=price + 1,
                    low=price - 1,
                    close=price,
                    adjusted_close=price,
                    volume=10000,
                    amount=100000,
                    collected_at=now(),
                )
            )
        db.add(
            BacktestSource(
                instrument_code="510500",
                source_url="https://example.com/510500",
                checked_through_date=date(2026, 6, 8),
                collected_at=now(),
                source_sha256="a" * 64,
                source_html="测试证据",
                corporate_actions={"dividends": [], "splits": []},
            )
        )
        db.commit()


def compare(body=None):
    response = client.post("/strategies/comparisons", json=body or BODY)
    assert response.status_code == 200, response.text
    return response.json()


def save(comparison, **patch):
    response = client.post(
        "/strategies",
        json={
            "instrument_code": "510500",
            "name": "测试均线",
            "comparison_id": comparison["id"],
            "track_key": "current",
            **patch,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_comparison_versions_preserve_original_and_recompute_shared_assumptions():
    first = compare()
    assert first["complete"] and len(first["tracks"]) == 2
    version = save(first)
    assert not version["active"] and version["version"] == 1
    second = compare({**BODY, "initial_cash": "20000", "version_ids": [version["id"]]})
    assert len(second["tracks"]) == 3
    assert all(
        Decimal(t["account"]["daily"][0]["equity"]) <= 24000 for t in second["tracks"]
    )
    unchanged = client.get("/strategies").json()[0]
    assert unchanged["settings"]["initial_cash"] == "10000"
    newer = save(second, strategy_id=version["strategy_id"])
    assert newer["version"] == 2 and newer["id"] != version["id"]
    assert client.get(f"/strategies/comparisons/{first['id']}").json() == first


def test_snapshot_survives_revision_and_half_capital_includes_reserve():
    body = deepcopy(BODY)
    body["current"]["rule"]["allocation"] = 50
    comparison = compare(body)
    assert len(comparison["tracks"]) == 3
    account = comparison["tracks"][0]["account"]
    assert all(Decimal(day["cash"]) >= 5000 for day in account["daily"])
    with Session() as db:
        candle = db.get(Candle, ("510500", date(2026, 6, 8)))
        candle.close = candle.adjusted_close = Decimal(14)
        candle.high = Decimal(15)
        db.commit()
    result = client.post(f"/strategies/comparisons/{comparison['id']}/verify")
    assert result.status_code == 200 and result.json()["identical"]
    assert compare(body)["input_sha256"] != comparison["input_sha256"]
    assert (
        client.get(f"/strategies/comparisons/{comparison['id']}").json()["market_rows"]
        == comparison["market_rows"]
    )
    from app.backtest import run_backtest
    from app.backtest_routes import digest
    from app.models import BacktestRun

    for track in comparison["tracks"]:
        with Session() as db:
            item = db.get(BacktestRun, track["backtest_id"])
            snapshot = item.input_snapshot
            assert digest(snapshot) == item.input_sha256
            assert (
                run_backtest(
                    snapshot["rows"],
                    snapshot["actions"]["dividends"],
                    snapshot["settings"],
                )
                == item.result_snapshot
            )


def test_failed_candidate_is_visible_and_does_not_prevent_other_results():
    spec = rule([condition("sentiment", category_key="missing")])
    result = compare({**BODY, "current": {"name": "缺情绪", "rule": spec}})
    assert not result["complete"]
    assert result["tracks"][0]["status"] == "failed"
    assert result["tracks"][0]["evidence_type"] == "revised"
    assert "reason" in result["tracks"][0]
    assert result["tracks"][1]["status"] == "success"
    response = client.post(
        "/strategies",
        json={
            "instrument_code": "510500",
            "name": "不可保存",
            "comparison_id": result["id"],
            "track_key": "current",
        },
    )
    assert response.status_code == 422


def test_draft_and_cross_etf_rejection():
    draft = {
        "name": "草稿",
        "rule": rule(),
        "settings": {
            k: v for k, v in BODY.items() if k not in ("current", "version_ids")
        },
        "strategy_id": None,
    }
    assert client.put("/strategies/drafts/510500", json=draft).status_code == 200
    assert client.get("/strategies/drafts/510500").json()["rule"] == rule()
    version = save(compare())
    response = client.post(
        "/strategies/comparisons",
        json={**BODY, "instrument_code": "512100", "version_ids": [version["id"]]},
    )
    assert response.status_code == 422


def test_enable_requires_explicit_replacement_and_pause_preserves_history():
    first = save(compare())
    second = save(compare())
    response = client.post(
        f"/strategies/{first['id']}/enable", json={"replace_active": False}
    )
    assert response.status_code == 200, response.text
    assert response.json()["active"]
    repeated = client.post(
        f"/strategies/{first['id']}/enable", json={"replace_active": False}
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["observation_id"] == response.json()["observation_id"]
    assert repeated.json()["readiness"] == response.json()["readiness"]
    assert repeated.json()["next_run"] == response.json()["next_run"]
    conflict = client.post(
        f"/strategies/{second['id']}/enable", json={"replace_active": False}
    )
    assert conflict.status_code == 409
    replaced = client.post(
        f"/strategies/{second['id']}/enable", json={"replace_active": True}
    )
    assert replaced.status_code == 200 and replaced.json()["active"]
    assert not next(
        x for x in client.get("/strategies").json() if x["id"] == first["id"]
    )["active"]
    assert client.post(f"/strategies/{second['id']}/pause").status_code == 200
    assert len(client.get("/strategies").json()) == 2


def freeze_plan_clock(monkeypatch):
    """固定盘前时钟并将本地采集证据移至生成之前。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import strategy_lab, strategy_workbench

    stamp = datetime(2026, 6, 9, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(strategy_lab, "now", lambda: stamp)
    monkeypatch.setattr(strategy_workbench, "now", lambda: stamp)
    with Session() as db:
        for row in db.query(Candle).all():
            row.collected_at = stamp.replace(hour=1)
        source = db.get(BacktestSource, "510500")
        source.collected_at = stamp.replace(hour=1)
        db.commit()
    return stamp


def test_unheld_etf_has_direction_without_inventing_zero_position(monkeypatch):
    version = save(compare())
    freeze_plan_clock(monkeypatch)
    assert (
        client.post(
            f"/strategies/{version['id']}/enable", json={"replace_active": False}
        ).status_code
        == 200
    )
    result = client.post("/strategy-lab/signals/generate").json()
    assert len(result["created"]) == 1, result
    plan = result["created"][0]["plan"]
    assert plan["quantity_status"] == "unknown"
    assert plan["actual_quantity"] is None
    assert plan["conditions"]["buy"]
    assert result["created"][0]["execution"]["status"] == "quantity_unknown"
    repeat = client.post("/strategy-lab/signals/generate").json()
    assert (
        not repeat["created"]
        and repeat["existing"][0]["id"] == result["created"][0]["id"]
    )


def test_custom_signal_is_blocked_after_open(monkeypatch):
    from datetime import timedelta

    from app import strategy_lab

    version = save(compare())
    stamp = freeze_plan_clock(monkeypatch)
    client.post(f"/strategies/{version['id']}/enable", json={"replace_active": False})
    monkeypatch.setattr(strategy_lab, "now", lambda: stamp + timedelta(hours=2))
    result = client.post("/strategy-lab/signals/generate").json()
    assert not result["created"] and result["blocked"]


def test_external_revision_is_research_only_and_forward_filters_collection_time(
    monkeypatch,
):
    from datetime import timedelta

    from app.models import SentimentCategory, SentimentDaily
    from app.strategy_inputs import external_snapshot

    spec = rule([condition("sentiment", "lt", "20", category_key="market")])
    stamp = freeze_plan_clock(monkeypatch)
    with Session() as db:
        db.add(
            SentimentCategory(
                category_key="market", category_name="市场背景", collected_at=stamp
            )
        )
        db.flush()
        for day in (2, 3, 4, 5, 8):
            db.add(
                SentimentDaily(
                    category_key="market",
                    trade_date=date(2026, 6, day),
                    fear_greed_score=0,
                    collected_at=stamp + timedelta(hours=1),
                )
            )
        db.commit()
        historical = external_snapshot(db, "510500", [spec], date(2026, 6, 8))
        forward = external_snapshot(db, "510500", [spec], date(2026, 6, 8), stamp)
        assert historical["sentiment:market"] and not forward["sentiment:market"]
    result = compare({**BODY, "current": {"name": "情绪研究", "rule": spec}})
    assert result["tracks"][0]["evidence_type"] == "revised"
    assert result["tracks"][0]["status"] == "success"


def add_empty_snapshot(stamp):
    """完整空集合是明确零仓，不能回退旧历史仓位。"""
    from app.models import Account, AccountSyncRun

    with Session() as db:
        db.merge(Account(account_id=1, created_at=stamp))
        db.add(
            AccountSyncRun(
                account_id=1,
                status="success",
                started_at=stamp.replace(hour=1),
                ended_at=stamp.replace(hour=1),
                holdings_snapshot={
                    "instrument_codes": [],
                    "source_date": None,
                    "collected_at": stamp.replace(hour=1).isoformat(),
                },
            )
        )
        db.commit()


def test_complete_empty_snapshot_and_continuing_position_do_not_rebalance(monkeypatch):
    from datetime import timedelta

    from app import strategy_lab

    version = save(compare())
    stamp = freeze_plan_clock(monkeypatch)
    add_empty_snapshot(stamp)
    client.post(f"/strategies/{version['id']}/enable", json={"replace_active": False})
    first = client.post("/strategy-lab/signals/generate").json()["created"][0]
    assert first["plan"]["quantity_status"] == "available"
    assert Decimal(first["plan"]["actual_quantity"]) == 0
    assert first["plan"]["funding_check_required"]
    next_stamp = stamp + timedelta(days=1)
    with Session() as db:
        db.add(
            Candle(
                code="510500",
                date=date(2026, 6, 9),
                open=30,
                high=31,
                low=29,
                close=30,
                adjusted_close=30,
                volume=10000,
                amount=300000,
                collected_at=next_stamp.replace(hour=1),
            )
        )
        source = db.get(BacktestSource, "510500")
        source.checked_through_date = date(2026, 6, 9)
        source.collected_at = next_stamp.replace(hour=1)
        db.commit()
    add_empty_snapshot(next_stamp)
    monkeypatch.setattr(strategy_lab, "now", lambda: next_stamp)
    second = client.post("/strategy-lab/signals/generate").json()["created"][0]
    assert second["plan"]["target_quantity"] == first["plan"]["target_quantity"]
    assert not second["plan"]["new_trigger"]
    assert "沿用" in second["plan"]["position_basis"]


def test_dependency_preparation_crossing_open_cannot_publish_late_plan(monkeypatch):
    from datetime import timedelta

    from app import strategy_lab, strategy_plans
    from app.models import Run

    version = save(compare())
    stamp = freeze_plan_clock(monkeypatch)
    client.post(f"/strategies/{version['id']}/enable", json={"replace_active": False})
    with Session() as db:
        run = Run(job_id=5, trigger="manual", started_at=stamp, logs=[])
        db.add(run)
        db.commit()
        run_id = run.id

    def prepare():
        monkeypatch.setattr(strategy_lab, "now", lambda: stamp + timedelta(hours=2))
        return []

    monkeypatch.setattr(strategy_plans, "prepare_signal_dependencies", prepare)
    strategy_lab.collect_signals(run_id)
    assert not client.get("/strategy-lab/signals").json()
    with Session() as db:
        assert any("开盘" in line["message"] for line in db.get(Run, run_id).logs)


def test_signal_uses_one_snapshot_for_holding_set_and_sync_evidence(monkeypatch):
    from app import strategy_plans
    from app.models import (
        Account,
        AccountHoldingSnapshot,
        AccountSyncRun,
        StrategySignal,
    )

    version = save(compare())
    stamp = freeze_plan_clock(monkeypatch)
    collected = stamp.replace(hour=1)
    with Session() as db:
        db.merge(Account(account_id=1, created_at=collected))
        db.flush()
        db.add(
            AccountHoldingSnapshot(
                account_id=1,
                instrument_code="510500",
                data_date=date(2026, 6, 8),
                current_amount=100,
                enable_amount=100,
                collected_at=collected,
            )
        )
        db.add(
            AccountSyncRun(
                account_id=1,
                status="success",
                started_at=collected,
                ended_at=collected,
                holdings_snapshot={
                    "instrument_codes": ["510500"],
                    "source_date": "2026-06-08",
                    "collected_at": collected.isoformat(),
                },
            )
        )
        db.commit()
    client.post(f"/strategies/{version['id']}/enable", json={"replace_active": False})
    original = strategy_plans.latest_holdings

    def concurrent_snapshot(db):
        result = original(db)
        add_empty_snapshot(stamp.replace(hour=2))
        return result

    monkeypatch.setattr(strategy_plans, "latest_holdings", concurrent_snapshot)
    result = client.post("/strategy-lab/signals/generate").json()
    assert len(result["created"]) == 1, result
    signal = result["created"][0]
    assert Decimal(signal["plan"]["actual_quantity"]) == 100
    with Session() as db:
        evidence = db.get(StrategySignal, signal["id"]).evidence_snapshot
        assert evidence["holdings_snapshot"]["instrument_codes"] == ["510500"]


def test_concurrent_generation_keeps_one_plan_and_returns_existing(monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    from app import strategy_lab

    version = save(compare())
    freeze_plan_clock(monkeypatch)
    client.post(f"/strategies/{version['id']}/enable", json={"replace_active": False})
    entered, release = threading.Event(), threading.Event()
    original = strategy_lab.make_plan

    def slow_plan(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(strategy_lab, "make_plan", slow_plan)

    def request():
        return TestClient(app).post("/strategy-lab/signals/generate")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(request)
        assert entered.wait(3)
        second = pool.submit(request)
        time.sleep(0.05)
        release.set()
        responses = [first.result(), second.result()]
    assert all(response.status_code == 200 for response in responses)
    assert sum(len(response.json()["created"]) for response in responses) == 1
    assert sum(len(response.json()["existing"]) for response in responses) == 1


def test_pause_racing_generation_does_not_publish_or_raise_server_error(monkeypatch):
    import time
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import select

    from app.models import StrategyObservation

    version = save(compare())
    freeze_plan_clock(monkeypatch)
    enabled = client.post(f"/strategies/{version['id']}/enable", json={'replace_active': False}).json()
    with Session() as db:
        observation = db.scalar(select(StrategyObservation).where(StrategyObservation.observation_id == enabled['observation_id']).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: TestClient(app).post('/strategy-lab/signals/generate'))
            time.sleep(0.05)
            observation.active = False
            db.commit()
            response = future.result()
    assert response.status_code == 200
    assert not response.json()['created']
    assert response.json()['blocked']
