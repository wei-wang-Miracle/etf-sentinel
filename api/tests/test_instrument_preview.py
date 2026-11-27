"""新增ETF的行情硬校验、FundDB降级和显式映射边界。"""

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import main
from app.collection import TZ
from app.db import Session
from app.models import Instrument, InstrumentIndexLink, Job, ResearchIndex

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="仅允许独立测试库"
)


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    with Session() as db:
        db.execute(
            text(
                "TRUNCATE instrument_index_links, research_indices, runs, instruments, jobs RESTART IDENTITY CASCADE"
            )
        )
        db.add_all(
            [
                Job(id=1, enabled=False, time="01:00"),
                Job(id=7, enabled=False, time="01:25"),
                ResearchIndex(
                    index_code="000905.SH",
                    index_name="中证500",
                    chatbi_code="000905",
                ),
            ]
        )
        db.commit()
    monkeypatch.setattr(main, "now", lambda: __import__("datetime").datetime(2026, 11, 28, tzinfo=TZ))
    monkeypatch.setattr(main, "fetch_rows", lambda code, start, end: [{
        "STOCK_CODE": code,
        "STOCK_NAME": "中证500ETF",
        "TRADE_DATE": str(date(2026, 11, 27)),
        "OPEN_PRICE": 1,
        "HIGH_PRICE": 1.1,
        "LOW_PRICE": 0.9,
        "CLOSE_PRICE": 1,
        "VOLUME": 1,
        "AMOUNT": 1,
    }])
    monkeypatch.setattr(main, "queue_free_backfill", lambda code: None)
    monkeypatch.setattr(main, "launch", lambda *args, **kwargs: None)


def test_funddb_preview_failure_does_not_block_market_verified_creation(monkeypatch):
    monkeypatch.setattr(main, "fetch_catalog", lambda: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(main, "fetch_fund_detail", lambda code: {"data": {}})
    client = TestClient(main.app)

    preview = client.get("/instruments/preview/510500")
    assert preview.status_code == 200
    assert preview.json()["market_verified"] is True
    assert preview.json()["funddb_profile"] is None
    assert preview.json()["warnings"]

    created = client.post("/instruments", json={"code": "510500"})
    assert created.status_code == 201
    with Session() as db:
        assert db.get(Instrument, "510500") is not None
        assert db.scalars(select(InstrumentIndexLink)).all() == []


def test_index_link_requires_explicit_confirmation_and_evidence(monkeypatch):
    client = TestClient(main.app)
    created = client.post("/instruments", json={"code": "510500"})
    assert created.status_code == 201
    with Session() as db:
        assert db.scalars(select(InstrumentIndexLink)).all() == []

    with Session() as db:
        db.delete(db.get(Instrument, "510500"))
        db.commit()
    rejected = client.post(
        "/instruments",
        json={
            "code": "510500",
            "confirm_index_link": True,
            "tracking_index_code": "000905.SH",
        },
    )
    assert rejected.status_code == 422

    accepted = client.post(
        "/instruments",
        json={
            "code": "510500",
            "confirm_index_link": True,
            "tracking_index_code": "000905.SH",
            "mapping_evidence": "基金合同与指数代码一致",
        },
    )
    assert accepted.status_code == 201
    with Session() as db:
        link = db.get(InstrumentIndexLink, ("510500", "000905.SH"))
        assert link is not None
        assert link.mapping_evidence == "基金合同与指数代码一致"
