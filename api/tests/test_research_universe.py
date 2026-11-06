"""验证国家队标的并入行情池且保留原配置及同日对照。"""

import importlib.util
import os
from datetime import date, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import collection
from app.collection import TZ, now
from app.db import Session, engine
from app.main import app
from app.models import Instrument, Job, NationalTeamDaily, NationalTeamInstrument, Run
from app.national_team import INSTRUMENT_CODES

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="仅允许独立测试库"
)


def test_expand_universe_preserves_settings_and_collects_all(monkeypatch):
    """插入缺失标的可重复执行，原配置保留，新增行情可用于持仓对照。"""
    path = Path(__file__).parents[1] / "migrations/versions/0005_research_universe.py"
    spec = importlib.util.spec_from_file_location("universe_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Session() as db:
        db.execute(
            text(
                "TRUNCATE instruments, jobs, national_team_instruments RESTART IDENTITY CASCADE"
            )
        )
        db.add_all(
            [
                Instrument(
                    code="510500",
                    name="原名称",
                    enabled=False,
                    start_date=date(2024, 1, 1),
                ),
                Instrument(code="159531"),
                Instrument(code="159205"),
            ]
        )
        db.add(Job(id=1, enabled=False, time="01:00"))
        db.commit()
    with (
        engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.upgrade()
        migration.upgrade()
    with Session() as db:
        items = db.scalars(select(Instrument)).all()
        assert len(items) == 20
        assert set(INSTRUMENT_CODES) <= {r.code for r in items}
        original = db.get(Instrument, "510500")
        assert not original.enabled and original.name == "原名称"
        assert original.start_date == date(2024, 1, 1)
        assert db.get(Instrument, "510300").start_date == date(2020, 1, 1)
        for item in items:
            item.enabled = True
            item.start_date = date(2026, 11, 1)
        run = Run(job_id=1, trigger="manual", started_at=now(), logs=[])
        db.add(run)
        db.commit()
        rid = run.id
    monkeypatch.setattr(collection, "now", lambda: datetime(2026, 11, 6, tzinfo=TZ))
    calls = []

    def source(code, start, end):
        calls.append(code)
        return [
            {
                "STOCK_CODE": code,
                "TRADE_DATE": str(start),
                "OPEN_PRICE": 1,
                "HIGH_PRICE": 2,
                "LOW_PRICE": 1,
                "CLOSE_PRICE": 2,
                "VOLUME": 100,
                "AMOUNT": 200,
            }
        ]

    collection.collect(rid, source)
    assert len(set(calls)) == 20
    client = TestClient(app)
    assert all(r["count"] == 1 for r in client.get("/instruments").json())
    assert (
        len(client.get("/candles/510300?start=2026-11-01&end=2026-11-05").json()) == 1
    )

    with Session() as db:
        db.add(
            NationalTeamInstrument(
                instrument_code="510300",
                instrument_name="测试基金",
                index_name="沪深300",
                estimation_start_date=date(2026, 1, 1),
                source_url="https://example.com",
                source_available=True,
                last_success_at=now(),
            )
        )
        db.flush()
        db.add(
            NationalTeamDaily(
                instrument_code="510300",
                trade_date=date(2026, 11, 1),
                estimated_holding_pct=50,
                collected_at=now(),
            )
        )
        db.commit()
    result = client.get(
        "/national-team/series/510300?start=2026-11-01&end=2026-11-05"
    ).json()
    assert result["holdings"][0]["estimated_holding_pct"] == 50
    assert result["holdings"][0]["trade_date"] == result["candles"][0]["date"]
    assert result["candles"][0]["close"] == 2
