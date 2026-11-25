"""验证黄金 ETF 可幂等加入统一行情标的配置。"""

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


def test_migration_declares_gold_etf_as_a_new_instrument():
    path = Path(__file__).parents[1] / "migrations/versions/0016_gold_etf.py"
    spec = importlib.util.spec_from_file_location("gold_etf_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert migration.INSTRUMENTS == {"518880": "华安黄金ETF"}


@pytest.mark.skipif(
    os.getenv("PGDATABASE") != "etf_sentinel_test", reason="仅允许独立测试库"
)
def test_adds_gold_etf_without_overwriting_existing_configuration():
    path = Path(__file__).parents[1] / "migrations/versions/0016_gold_etf.py"
    spec = importlib.util.spec_from_file_location("gold_etf_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

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
        assert [item.code for item in items] == ["510500", "518880"]
        existing = db.get(Instrument, "510500")
        assert existing.name == "自定义名称"
        assert existing.enabled is False
        assert existing.start_date == date(2024, 1, 1)
        gold = db.get(Instrument, "518880")
        assert gold.enabled is True
        assert gold.start_date == date(2020, 1, 1)
