"""独立测试库验证全市场恐贪、五维子因子与任务6。"""

import os
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.collection import now
from app.db import Session
from app.main import app
from app.market_sentiment import collect_market_sentiment
from app.models import Job, MarketFearGreedDaily, MarketRegimeFactorDaily, Run

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="仅允许独立测试库"
)


@pytest.fixture(autouse=True)
def reset():
    """测试数据只进入独立数据库，任务6与其他任务隔离。"""
    with Session() as db:
        db.execute(
            text("TRUNCATE market_fear_greed_daily, market_regime_factor_daily, jobs RESTART IDENTITY CASCADE")
        )
        db.add_all(
            [
                Job(id=1, enabled=False, time="01:00"),
                Job(id=6, enabled=False, time="01:15"),
            ]
        )
        db.commit()


def _run_id():
    with Session() as db:
        run = Run(job_id=6, trigger="manual", started_at=now(), logs=[])
        db.add(run)
        db.commit()
        return run.id


def _source(*, score=20, volatility=23, revision=False):
    def fetch():
        return {
            "date": "2026-11-27",
            "value": score,
            "desc": "恐惧",
            "history": [
                {"date": "2020-08-03", "value": 25},
                {"date": "2026-11-27", "value": score},
            ],
            "factors": [
                {
                    "key": key,
                    "name": name,
                    "series": [
                        {
                            "date": "2026-11-27",
                            "value": volatility if key == "volatility" else -11,
                            "pct_year": 80 if revision else 50,
                            "pct_all": 90,
                        }
                    ],
                }
                for key, name in (
                    ("volatility", "指数波动：50ETF期权波动率"),
                    ("bx", "避险天堂：股债回报差"),
                    ("premium", "升贴水率：沪深300股指期货升贴水"),
                    ("wz", "两市成交额"),
                    ("strength", "股价强度：创新高个股数量占比"),
                )
            ],
        }

    return fetch


def test_incremental_revision_does_not_delete_prior_regime_history():
    with Session() as db:
        db.add(
            MarketRegimeFactorDaily(
                factor_key="volatility",
                trade_date=date(2025, 1, 2),
                factor_name="指数波动：50ETF期权波动率",
                raw_value=Decimal("18.5"),
                source_pct_year=Decimal(40),
                source_pct_all=Decimal(50),
                collected_at=now(),
            )
        )
        db.commit()

    collect_market_sentiment(_run_id(), _source())
    collect_market_sentiment(_run_id(), _source(volatility=24, revision=True))

    with Session() as db:
        assert db.scalar(select(func.count()).select_from(MarketFearGreedDaily)) == 2
        assert db.get(
            MarketRegimeFactorDaily, ("volatility", date(2025, 1, 2))
        ).raw_value == Decimal("18.5")
        assert db.get(
            MarketRegimeFactorDaily, ("volatility", date(2026, 11, 27))
        ).raw_value == Decimal(24)
        assert db.get(Run, 2).status == "success"


def test_local_api_exposes_total_series_factors_and_independent_job():
    collect_market_sentiment(_run_id(), _source(score=0))
    client = TestClient(app)

    overview = client.get("/market-sentiment/overview").json()
    assert overview["latest"]["fear_greed_score"] == 0
    assert overview["regime_factors"]["volatility"]["raw_value"] == 23
    series = client.get(
        "/market-sentiment/series?start=2026-11-01&end=2026-11-27"
    ).json()
    assert series["fear_greed"][-1]["fear_greed_score"] == 0
    assert series["regime_factors"]["premium"][-1]["raw_value"] == -11
    assert client.put(
        "/market-sentiment/job", json={"enabled": True, "time": "02:15"}
    ).status_code == 200
    assert client.get("/market-sentiment/job").json()["time"] == "02:15"
    assert client.get("/job").json()["time"] == "01:00"
