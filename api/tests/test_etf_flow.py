"""配置内 ETF 档案与份额流采集的持久化边界。"""

import os
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.collection import now
from app.db import Session
from app.etf_flow import collect_etf_flows
from app.models import EtfCatalogProfile, EtfFlowDaily, Instrument, Job, Run

pytestmark = pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="仅允许独立测试库"
)


@pytest.fixture(autouse=True)
def reset():
    with Session() as db:
        db.execute(text("TRUNCATE etf_catalog_profiles, etf_flow_daily, instruments, jobs RESTART IDENTITY CASCADE"))
        db.add_all([
            Instrument(code="510500", enabled=True),
            Instrument(code="518880", enabled=False),
            Job(id=7, enabled=False, time="01:25"),
        ])
        db.commit()


def _run_id():
    with Session() as db:
        run = Run(job_id=7, trigger="manual", started_at=now(), logs=[])
        db.add(run)
        db.commit()
        return run.id


def _catalog(*, revision=False):
    row = {
        "instrument_code": "510500",
        "fund_full_name": "中证500ETF",
        "category_primary": "股票型ETF",
        "category_tag": "中证500",
        "tracking_index_code": "000905.SH",
        "tracking_index_name": "中证500",
        "setup_date": date(2013, 2, 6),
        "management_fee_pct": Decimal("0.5"),
        "custody_fee_pct": Decimal("0.1"),
        "linked_otc_code": "160119",
        "source_url": "https://ai2.jiucaishuo.com/api/fundsale/etf",
        "flow": {
            "trade_date": date(2026, 11, 27),
            "unit_shares_100m": Decimal("3.4"),
            "aum_100m": Decimal("12.5"),
            "net_share_flow_7d_100m": Decimal("0.3" if revision else "0.2"),
            "net_share_flow_30d_100m": Decimal("-0.3"),
            "discount_premium_pct": Decimal("0.12"),
            "purchase_status": "开放申购",
            "redeem_status": "开放赎回",
        },
    }
    return [row]


def test_only_enabled_configured_instruments_are_saved_and_revisions_are_idempotent():
    collect_etf_flows(_run_id(), fetch_catalog=lambda: _catalog(), fetch_detail=lambda _: {"tracking_index_code": "000905.SH", "index_corr": Decimal("0.97")})
    collect_etf_flows(_run_id(), fetch_catalog=lambda: _catalog(revision=True), fetch_detail=lambda _: {"tracking_index_code": "000905.SH", "index_corr": Decimal("0.97")})

    with Session() as db:
        assert db.scalars(select(EtfCatalogProfile)).all()[0].instrument_code == "510500"
        assert db.get(EtfCatalogProfile, "510500").index_corr == Decimal("0.97")
        assert db.get(EtfFlowDaily, ("510500", date(2026, 11, 27))).net_share_flow_7d_100m == Decimal("0.3")
        assert db.get(EtfCatalogProfile, "518880") is None
        assert db.get(Run, 2).status == "success"
