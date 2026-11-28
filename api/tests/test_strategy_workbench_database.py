"""独立数据库验证策略比较、因子目录及显式采用和暂停。"""

import os
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.algorithm_templates import turning_events, turning_profile
from app.backtest_data import trading_days
from app.collection import now
from app.db import Session
from app.main import app
from app.models import BacktestSource, Candle, Instrument, Job
from app.research_factors import FACTORS
from app.strategy_inputs import market_snapshot

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
    "strategies": ["range_breakout", "bottom_confirmation"],
}


@pytest.fixture(autouse=True)
def sample():
    """只在独立测试数据库中准备连续日行情及权益快照。"""
    with Session() as db:
        db.execute(
            text("TRUNCATE instruments, sentiment_categories, accounts RESTART IDENTITY CASCADE")
        )
        db.merge(Job(id=5, time="08:30", enabled=True))
        for code, category in (("510500", "中盘宽基"), ("510330", "大盘宽基")):
            db.add(Instrument(code=code, name=f"测试ETF {code}", research_category=category))
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


def adopt(result, strategy="range_breakout", **kwargs):
    return client.post("/strategies/adopt", json={"comparison_id": result["id"], "strategy_id": strategy, **kwargs})


def test_catalog_compare_and_verify_without_automatic_adoption():
    catalog = client.get("/strategies/catalog").json()
    assert {item["id"] for item in catalog["strategies"]} == {
        "range_breakout",
        "bottom_confirmation",
        "hybrid_reversal",
        "trend_pullback",
        "volatility_contraction_breakout",
        "value_sentiment_reversal",
        "gem_bottom_contraction",
    }
    assert catalog["assignments"] == []
    factors = client.get("/factors").json()
    assert {item["id"] for item in factors["factors"]} == set(FACTORS)
    assert next(item for item in catalog["strategies"] if item["id"] == "range_breakout")["factors"][0]["id"] == "box_breakout_up"
    result = compare()
    assert result["complete"], result["tracks"]
    assert [row["strategy_id"] for row in result["tracks"]] == [*BODY["strategies"], "hold"]
    assert client.get("/strategies/catalog").json()["assignments"] == []
    assert client.get("/strategies").status_code == 404
    assert client.get("/strategy-lab/observations").status_code == 404
    assert adopt(result, "hold").status_code == 422
    assert client.post(f"/strategies/comparisons/{result['id']}/verify").json()["identical"] is True
    with Session() as db:
        rows = db.execute(text("SELECT strategy_id, factor_id FROM strategy_comparison_factors WHERE comparison_id = :id"), {"id": result["id"]})
        assert {tuple(row) for row in rows} == {
            ("range_breakout", "box_breakout_up"), ("range_breakout", "turning_top"),
            ("bottom_confirmation", "turning_bottom"), ("bottom_confirmation", "turning_top"),
        }


def test_comparison_rejects_user_rules_retired_and_research_strategies():
    for invalid in ({**BODY, "templates": []}, {**BODY, "strategies": ["etf_multifactor"]},
                    {**BODY, "strategies": ["left_reversal_research"]}):
        assert client.post("/strategies/comparisons", json=invalid).status_code == 422


def test_adopt_replace_pause_and_resume_keep_one_assignment_per_etf():
    result = compare()
    response = adopt(result)
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["active"] and adopt(result).json() == first
    assert adopt(result, "bottom_confirmation").status_code == 409
    replaced = adopt(result, "bottom_confirmation", replace_active=True).json()
    assert replaced["id"] == first["id"] and replaced["strategy_id"] == "bottom_confirmation"
    assert client.post("/strategies/510500/pause").json()["active"] is False
    assert adopt(result, "bottom_confirmation").json()["active"] is True
    other = adopt(compare({**BODY, "instrument_code": "510330"})).json()
    assert other["id"] != first["id"]
    assert len(client.get("/strategies/catalog").json()["assignments"]) == 2


def test_generate_only_for_adopted_etf_and_keeps_old_signal_after_replacement(monkeypatch):
    from app import strategy_lab, strategy_workbench

    day = date.fromisoformat(DAYS[-1])
    execution = date.fromisoformat(trading_days(day, date(2026, 11, 10))[0][1])
    ts = datetime.combine(execution, datetime.min.time(), ZoneInfo("Asia/Shanghai")).replace(hour=8)
    monkeypatch.setattr(strategy_lab, "now", lambda: ts)
    monkeypatch.setattr(strategy_workbench, "now", lambda: ts)
    with Session() as db:
        db.get(BacktestSource, "510500").collected_at = ts
        db.execute(text("UPDATE candles SET collected_at = :ts"), {"ts": ts})
        db.commit()
    result = compare()
    assert client.post("/strategy-lab/signals/generate").json()["created"] == []
    assert adopt(result).status_code == 200
    generated = client.post("/strategy-lab/signals/generate").json()
    assert len(generated["created"]) == 1, generated
    signal = generated["created"][0]
    assert signal["strategy_id"] == "range_breakout" and signal["plan"]["quantity_status"] == "unknown"
    assert client.post("/strategy-lab/signals/generate").json()["existing"][0]["id"] == signal["id"]
    assert adopt(result, "bottom_confirmation", replace_active=True).status_code == 200
    assert client.get("/strategy-lab/signals").json()[0]["strategy_name"] == "箱体突破"
    monkeypatch.setattr(strategy_lab, "now", lambda: ts.replace(hour=9, minute=30))
    assert "已开盘" in client.post("/strategy-lab/signals/generate").json()["blocked"][0]["reason"]


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


def test_chart_confirmations_use_history_before_display_start_and_verified_cutoff():
    with Session() as db:
        for index, day in enumerate(DAYS):
            price = Decimal(10000 - min(index, 70) * 25 + max(0, min(index - 70, 60)) * 70
                            - min(100, max(0, index - 130)) * 60) / 1000
            row = db.get(Candle, ("510500", date.fromisoformat(day)))
            row.open = row.close = row.adjusted_close = price
            row.high, row.low = price + Decimal(".01"), price - Decimal(".01")
        db.get(BacktestSource, "510500").checked_through_date = date(2025, 12, 26)
        db.delete(db.get(BacktestSource, "510330"))
        db.commit()

    with Session() as db:
        market = market_snapshot(
            db,
            "510500",
            date(2025, 12, 26),
            interval_start=date(2025, 9, 1),
        )
    expected_events = turning_events(
        market["rows"],
        market["actions"]["dividends"],
        turning_profile("510500")["parameters"],
    )

    response = client.get("/candles/510500/factors?start=2025-09-01&end=2026-01-01")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert {(item["trade_date"], item["factor_id"]) for item in payload["events"] if item["factor_id"].startswith("turning_")} == {
        (day, f"turning_{kind}") for day, kind in expected_events.items() if day >= "2025-09-01"
    }
    assert payload["data_cutoff"] == "2025-12-26" and payload["partial"] is True
    assert all("2025-09-01" <= row["trade_date"] <= payload["data_cutoff"] for row in payload["events"])
    assert client.get("/candles/510330/factors?start=2025-09-01&end=2026-01-01").status_code == 422
    assert client.get("/candles/510330?start=2025-09-01&end=2026-01-01").status_code == 200


def test_chart_uses_front_adjustment_and_turning_events_accept_verified_split():
    split_day = DAYS[99]
    with Session() as db:
        source = db.get(BacktestSource, "510500")
        source.corporate_actions = {
            "dividends": [],
            "splits": [{"effective_date": split_day, "ratio": "1:2"}],
        }
        for day in DAYS[100:]:
            row = db.get(Candle, ("510500", date.fromisoformat(day)))
            row.open /= 2
            row.high /= 2
            row.low /= 2
            row.close /= 2
            row.volume *= 2
        db.commit()

    chart = client.get(
        f"/candles/510500?start={DAYS[99]}&end={DAYS[101]}"
    )
    assert chart.status_code == 200, chart.text
    with Session() as db:
        expected = [
            float(db.get(Candle, ("510500", date.fromisoformat(day))).adjusted_close / 2)
            for day in DAYS[99:102]
        ]
    assert [row["close"] for row in chart.json()] == pytest.approx(expected)

    events = client.get(
        f"/candles/510500/factors?start={DAYS[99]}&end={DAYS[101]}"
    )
    assert events.status_code == 200, events.text
    assert events.json()["data_cutoff"] == DAYS[101]
