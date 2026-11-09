"""独立测试库验证盘前计划的人工成交关联、源修订与主动跳过。"""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from test_research_database import sample  # noqa: F401

from app.collection import now
from app.db import Session
from app.main import app
from app.models import (
    AccountEntrust,
    StrategyObservation,
    StrategyResearchBatch,
    StrategySignal,
)

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="需要独立测试库"
)
client = TestClient(app)


def freeze_clock(monkeypatch):
    """固定服务时钟到执行日盘中，人工确认只受计划时点约束。"""
    from app import strategy_lab

    stamp = datetime(2026, 7, 1, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(strategy_lab, "now", lambda: stamp)
    return stamp


def frozen_sell_signal():
    """直接落库一条盘前卖出计划，核对保留的人工确认链路。"""
    stamp = datetime(2026, 7, 1, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    with Session() as db:
        batch = StrategyResearchBatch(
            created_at=stamp,
            input_snapshot={"kind": "single_etf"},
            result_snapshot={},
            input_sha256="a" * 64,
        )
        db.add(batch)
        db.flush()
        observation = StrategyObservation(
            research_batch_id=batch.research_batch_id,
            instrument_code="159205",
            created_at=stamp,
            active=False,
            rule_snapshot={},
        )
        db.add(observation)
        db.flush()
        signal = StrategySignal(
            observation_id=observation.observation_id,
            instrument_code="159205",
            generated_at=stamp,
            data_cutoff=date(2026, 6, 30),
            execution_date=date(2026, 7, 1),
            plan_snapshot={
                "action": "sell",
                "requested_quantity": "1000",
                "quantity_status": "available",
            },
            evidence_snapshot={},
        )
        db.add(signal)
        db.commit()
        return signal.signal_id


def test_execution_needs_confirmed_date_unique_link_and_revision_tracking(monkeypatch):
    signal_id = frozen_sell_signal()
    freeze_clock(monkeypatch)
    with Session() as db:
        db.add(
            AccountEntrust(
                account_id=1,
                instrument_code="159205",
                curr_date=date(2026, 7, 1),
                entrust_no="sell-1",
                entrust_side="2",
                business_amount=500,
                business_price=10,
                business_balance=5000,
                clear_balance=4999,
                fee_amount=1,
                data_date=date(2026, 7, 1),
                collected_at=now(),
            )
        )
        db.commit()
    candidates = client.get(f"/strategy-lab/signals/{signal_id}/candidates").json()
    assert [r["entrust_no"] for r in candidates] == ["sell-1"]
    payload = {
        "curr_date": "2026-07-01",
        "entrust_no": "sell-1",
        "confirmed_trade_date": "2026-07-01",
        "confirmation_note": "已核对券商当日成交明细",
        "confirm_plan_preceded_trade": True,
    }
    assert (
        client.post(
            f"/strategy-lab/signals/{signal_id}/link",
            json={**payload, "confirm_plan_preceded_trade": False},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/strategy-lab/signals/{signal_id}/link",
            json={**payload, "confirmed_trade_date": "2026-06-30"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/strategy-lab/signals/{signal_id}/link", json=payload
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/strategy-lab/signals/{signal_id}/link", json=payload
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/strategy-lab/signals/{signal_id}/skip", json={"note": "已关联后不能再跳过"}
        ).status_code
        == 409
    )
    item = client.get("/strategy-lab/signals").json()[0]
    assert item["execution"]["status"] == "partial"
    with Session() as db:
        db.get(AccountEntrust, (1, date(2026, 7, 1), "sell-1")).business_amount = 1200
        db.commit()
    item = client.get("/strategy-lab/signals").json()[0]
    assert item["execution"]["status"] == "excess"
    assert item["execution"]["links"][0]["source_revised"]


def test_skip_records_reason_and_never_implies_execution(monkeypatch):
    signal_id = frozen_sell_signal()
    freeze_clock(monkeypatch)
    assert (
        client.post(
            f"/strategy-lab/signals/{signal_id}/skip", json={"note": "  "}
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/strategy-lab/signals/{signal_id}/skip",
            json={"note": "当日决定不跟随该计划"},
        ).status_code
        == 200
    )
    item = client.get("/strategy-lab/signals").json()[0]
    assert item["execution"]["status"] == "skipped"
    assert item["skip_note"] == "当日决定不跟随该计划"
    assert (
        client.post(
            f"/strategy-lab/signals/{signal_id}/skip", json={"note": "重复跳过"}
        ).status_code
        == 409
    )