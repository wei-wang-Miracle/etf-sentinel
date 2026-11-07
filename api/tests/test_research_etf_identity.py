"""使用隔离内存数据库验证 ETF 主体、持仓范围和关联估值，不访问外部服务。"""

from datetime import UTC, date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import (
    account_routes,
    index_valuation_routes,
    research_routes,
    sentiment_routes,
)
from app.models import (
    Account,
    AccountHoldingSnapshot,
    Base,
    IndexValuationDaily,
    Instrument,
    InstrumentIndexLink,
    ResearchIndex,
)


@pytest.fixture()
def fixture(monkeypatch):
    """真实执行关系查询，但所有写入限定于本测试独立内存数据库。"""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    for module in (
        research_routes,
        account_routes,
        index_valuation_routes,
        sentiment_routes,
    ):
        monkeypatch.setattr(module, "Session", factory)
    monkeypatch.setattr(
        research_routes,
        "trading_days",
        lambda *_: (["2026-06-01", "2026-06-02"], "test"),
    )
    timestamp = datetime(2026, 6, 2, tzinfo=UTC)
    with factory() as db:
        db.add(Account(account_id=1, created_at=timestamp))
        db.add_all(
            [
                Instrument(code=code, name=f"ETF{code}")
                for code in ("159205", "159531", "510500", "512100")
            ]
        )
        db.add(
            ResearchIndex(
                index_code="000905.SH", index_name="中证500", chatbi_code="000905"
            )
        )
        db.flush()
        for code in ("159205", "159531", "510500"):
            db.add(
                InstrumentIndexLink(
                    instrument_code=code,
                    index_code="000905.SH",
                    mapping_evidence="测试",
                    verified_date=date(2026, 6, 2),
                )
            )
        for code, day, quantity in (
            ("159205", 1, 100),
            ("159205", 2, 0),
            ("159531", 2, 200),
            ("510500", 2, 300),
            ("512100", 2, 400),
        ):
            db.add(
                AccountHoldingSnapshot(
                    account_id=1,
                    instrument_code=code,
                    data_date=date(2026, 6, day),
                    current_amount=quantity,
                    collected_at=timestamp,
                )
            )
        for day, value in ((1, 10), (2, 20)):
            db.add(
                IndexValuationDaily(
                    index_code="000905.SH",
                    metric_key="pe",
                    trade_date=date(2026, 6, day),
                    metric_value=value,
                    value_status="valid",
                    collected_at=timestamp,
                )
            )
        db.commit()
    app = FastAPI()
    app.include_router(research_routes.router)
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def test_universe_uses_only_latest_positive_configured_holdings(fixture):
    client, _ = fixture
    response = client.get("/research/universe")
    assert response.status_code == 200
    data = response.json()
    assert data["held_codes"] == ["159531", "510500", "512100"]
    assert data["holdings_as_of"] == "2026-06-02"
    assert data["default_code"] == "159531"
    assert len(data["items"]) == 4
    assert all(item["type"] == "etf" for item in data["items"])


def test_old_index_object_resolves_to_held_etf_and_preserves_source(fixture):
    client, _ = fixture
    result = client.get("/research/object?object_type=index&code=000905.SH").json()
    assert result["object"] == {"type": "etf", "code": "159531", "name": "ETF159531"}
    assert result["redirected_from"] == {"type": "index", "code": "000905.SH"}
    assert result["linked"]["index_code"] == "000905.SH"
    assert result["summary"]["investment_status"] == "holding"
    assert any("关联" in message for message in result["warnings"])


def test_zero_quantity_is_not_a_current_holding(fixture):
    client, _ = fixture
    result = client.get("/research/object?object_type=etf&code=159205").json()
    assert result["summary"]["investment_status"] == "not_traded"
    assert result["summary"]["holding"] is None


def test_valuation_rows_and_legends_are_etfs_with_shared_index_evidence(fixture):
    client, _ = fixture
    response = client.get(
        "/research/compare?dimension=valuation&start=2026-06-01&end=2026-06-02"
    )
    assert response.status_code == 200
    result = response.json()
    items = {item["code"]: item for item in result["items"]}
    assert set(items) == {"159531", "510500", "512100"}
    assert all(item["object_type"] == "etf" for item in items.values())
    assert items["159531"]["rank"] == items["510500"]["rank"]
    assert items["159531"]["index_code"] == "000905.SH"
    assert items["159531"]["shared_index_codes"] == ["159531", "510500"]
    assert items["512100"]["status"] == "missing"
    assert result["universe"]["independent_sources"] == 1
    assert all(row["code"] in items for row in result["series"])
    assert any("共享" in warning for warning in result["warnings"])


def test_all_scope_and_empty_held_scope_do_not_silently_substitute(fixture):
    client, factory = fixture
    path = "/research/compare?dimension=valuation&start=2026-06-01&end=2026-06-02"
    assert len(client.get(path + "&scope=all").json()["items"]) == 4
    with factory() as db:
        db.execute(delete(AccountHoldingSnapshot))
        db.commit()
    result = client.get(path).json()
    assert result["items"] == []
    assert any("持仓" in warning for warning in result["warnings"])
    assert client.get("/research/universe").json()["held_codes"] == []


def test_invalid_scope_is_rejected(fixture):
    client, _ = fixture
    response = client.get(
        "/research/compare?dimension=valuation&start=2026-06-01&end=2026-06-02&scope=invalid"
    )
    assert response.status_code == 422


def test_unmapped_legacy_index_never_becomes_research_object(fixture):
    client, _ = fixture
    response = client.get("/research/object?object_type=index&code=999999.SH")
    assert response.status_code == 404
    assert "关联" in response.json()["detail"]


def test_sentiment_is_market_background_independent_of_held_etf_scope(fixture):
    from app.models import SentimentCategory

    client, factory = fixture
    with factory() as db:
        db.add(
            SentimentCategory(
                category_key="industry",
                category_name="行业背景",
                collected_at=datetime(2026, 6, 2, tzinfo=UTC),
            )
        )
        db.commit()
    path = "/research/compare?dimension=sentiment&start=2026-06-01&end=2026-06-02"
    result = client.get(path).json()
    assert result["items"][0]["object_type"] == "sentiment"
    assert result["items"][0]["code"] == "industry"
    assert result["universe"]["scope"] == "market"
    assert result == client.get(path + "&scope=all").json()


def test_holdings_and_trends_keep_uncovered_etfs_in_scope(fixture):
    client, _ = fixture
    for dimension in ("holdings", "trend"):
        result = client.get(
            f"/research/compare?dimension={dimension}&start=2026-06-01&end=2026-06-02"
        ).json()
        assert {item["code"] for item in result["items"]} == {
            "159531",
            "510500",
            "512100",
        }
        assert all(item["rank"] is None for item in result["items"])
