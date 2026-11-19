"""独立数据库验证算法模板比较、版本保存与显式启停。"""

import os
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.backtest_data import trading_days
from app.collection import now
from app.db import Session
from app.main import app
from app.models import BacktestSource, Candle, Instrument, Job

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="需要独立测试库"
)
client = TestClient(app)
START = date(2025, 6, 1)
END = date(2026, 10, 30)
DAYS, _ = trading_days(str(START), str(END))
BODY = {
    "instrument_code": "510500",
    "start_date": DAYS[75],
    "end_date": DAYS[-1],
    "templates": [
        {"id": "range_breakout", "version": "1.0.0"},
        {"id": "bottom_confirmation", "version": "1.0.0"},
    ],
}


@pytest.fixture(autouse=True)
def sample():
    """只在独立测试数据库中准备连续日行情及权益快照。"""
    with Session() as db:
        db.execute(
            text("TRUNCATE instruments, sentiment_categories, accounts RESTART IDENTITY CASCADE")
        )
        db.merge(Job(id=5, time="08:30", enabled=True))
        for code in ("510500", "510330"):
            db.add(Instrument(code=code, name=f"测试ETF {code}"))
            db.flush()
            for index, raw_day in enumerate(DAYS):
                base = Decimal("6.0") + Decimal(index % 24 - 12) * Decimal("0.012")
                close = base * Decimal("1.003" if index % 7 else "0.985")
                db.add(
                    Candle(
                        code=code,
                        date=date.fromisoformat(raw_day),
                        open=base,
                        high=base * Decimal("1.02"),
                        low=base * Decimal("0.98"),
                        close=close,
                        adjusted_close=close,
                        volume=10000 + index * 50,
                        amount=base * 10000,
                        collected_at=now(),
                    )
                )
            db.add(
                BacktestSource(
                    instrument_code=code,
                    source_url=f"https://example.com/{code}",
                    checked_through_date=date.fromisoformat(DAYS[-1]),
                    collected_at=now(),
                    source_sha256="a" * 64,
                    source_html="测试权益证据",
                    corporate_actions={"dividends": [], "splits": []},
                )
            )
        db.commit()


def compare(body=None):
    response = client.post("/strategies/comparisons", json=body or BODY)
    assert response.status_code == 200, response.text
    return response.json()


def save(comparison, key="template:range_breakout:1.0.0"):
    response = client.post(
        "/strategies", json={"comparison_id": comparison["id"], "track_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_catalog_and_comparison_use_frozen_algorithms_without_binding():
    catalog = client.get("/strategies/catalog").json()
    assert len(catalog["templates"]) == 3
    assert all(template["status"] == "experimental" for template in catalog["templates"])
    assert "conditions" not in catalog and "sentiment_categories" not in catalog

    result = compare()
    assert result["complete"], [(row["key"], row.get("reason")) for row in result["tracks"]]
    breakout, bottom, hold = result["tracks"]
    assert breakout["template"]["rule"]["family"] == "breakout"
    assert bottom["template"]["rule"]["family"] == "bottom"
    assert hold["key"] == "hold"
    assert hold["evidence_type"] == "historical"
    assert breakout["diagnostics"]["completed_rounds"] == len(breakout["diagnostics"]["rounds"])
    assert result["data_cutoff"] == DAYS[-1]
    assert result["settings"]["initial_cash"] == "50000"
    assert client.get("/strategies").json() == []
    denied = client.post("/strategies", json={"comparison_id": result["id"], "track_key": "hold"})
    assert denied.status_code == 422


def test_client_cannot_submit_rule_or_old_template():
    injected = {**BODY, "templates": [{**BODY["templates"][0], "rule": {"buy": {}}}]}
    assert client.post("/strategies/comparisons", json=injected).status_code == 422
    legacy = {**BODY, "templates": [{"id": "etf_multifactor", "version": "1.0.0"}]}
    assert client.post("/strategies/comparisons", json=legacy).status_code == 422


def test_same_algorithm_supports_multiple_etfs_and_preserves_binding_identity():
    result = compare()
    first = save(result)
    assert save(result)["id"] == first["id"]
    assert first["algorithm_template_id"] == "range_breakout"

    repeated = save(compare({**BODY, "start_date": DAYS[76]}))
    assert repeated["strategy_id"] == first["strategy_id"]
    assert repeated["version"] == first["version"] + 1

    other = save(compare({**BODY, "instrument_code": "510330"}))
    assert other["instrument_code"] == "510330"
    assert other["template"] == first["template"]
    assert other["strategy_id"] != first["strategy_id"]

    second_algorithm = save(result, "template:bottom_confirmation:1.0.0")
    assert second_algorithm["strategy_id"] != first["strategy_id"]
    assert client.post(f"/strategies/{first['id']}/enable", json={}).status_code == 200
    switch = f"/strategies/{second_algorithm['id']}/enable"
    assert client.post(switch, json={}).status_code == 409
    assert client.post(switch, json={"replace_active": True}).status_code == 200
    assert [row["id"] for row in client.get("/strategies").json() if row["active"]] == [second_algorithm["id"]]


def test_saved_version_stays_inactive_until_explicit_enable_and_recomputes():
    original = compare()
    version = save(original)
    assert not version["active"]
    assert version["template"]["version"] == "1.0.0"

    verified = client.post(f"/strategies/comparisons/{original['id']}/verify")
    assert verified.status_code == 200 and verified.json()["identical"]

    enabled = client.post(f"/strategies/{version['id']}/enable", json={})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["active"]
    assert enabled.json()["readiness"]["status"] == "waiting"


def test_catalog_default_range_uses_post_split_prices_and_verified_end():
    split_day, verified_end = DAYS[40], DAYS[-4]
    with Session() as db:
        source = db.get(BacktestSource, "510500")
        source.corporate_actions = {"dividends": [], "splits": [{"effective_date": split_day, "ratio": "1:2"}]}
        source.checked_through_date = date.fromisoformat(verified_end)
        db.commit()
    catalog = client.get("/strategies/catalog").json()
    instrument = next(row for row in catalog["instruments"] if row["instrument_code"] == "510500")
    assert instrument["default_start"] == DAYS[101]
    assert instrument["default_end"] == verified_end
    result = compare({**BODY, "start_date": instrument["default_start"], "end_date": instrument["default_end"]})
    assert result["complete"], result["tracks"]

    early = compare({**BODY, "start_date": DAYS[100], "end_date": verified_end})
    assert early["tracks"][0]["status"] == "failed"
    assert "至少60" in early["tracks"][0]["reason"]
    assert early["tracks"][-1]["status"] == "success"
