"""验证新增 ETF 可幂等加入统一标的配置。"""

import importlib.util
import os
from datetime import date
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text

from app.db import Session, engine
from app.models import Instrument


def load_migration():
    path = Path(__file__).parents[1] / "migrations/versions/0017_add_etf_instruments.py"
    spec = importlib.util.spec_from_file_location("additional_instruments_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_declares_requested_etf_instruments():
    migration = load_migration()

    assert migration.INSTRUMENTS == {
        "515880": "国泰中证全指通信设备ETF",
        "560780": "广发中证半导体材料设备ETF",
    }


@pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="仅允许独立测试库"
)
def test_adds_requested_etfs_without_overwriting_existing_configuration():
    migration = load_migration()

    with Session() as db:
        db.execute(text("TRUNCATE instruments RESTART IDENTITY CASCADE"))
        db.add(
            Instrument(
                code="510500",
                name="自定义名称",
                enabled=False,
                start_date=date(2024, 1, 1),
            )
        )
        db.commit()

    with (
        engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.upgrade()
        migration.upgrade()

    with Session() as db:
        items = db.scalars(select(Instrument).order_by(Instrument.code)).all()
        assert [item.code for item in items] == ["510500", "515880", "560780"]
        existing = db.get(Instrument, "510500")
        assert existing.name == "自定义名称"
        assert existing.enabled is False
        assert existing.start_date == date(2024, 1, 1)
        for code in ("515880", "560780"):
            instrument = db.get(Instrument, code)
            assert instrument.enabled is True
            assert instrument.start_date == date(2020, 1, 1)
