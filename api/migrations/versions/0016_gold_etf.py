"""将华安黄金 ETF 加入统一行情标的配置。"""

from datetime import date

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

INSTRUMENTS = {"518880": "华安黄金ETF"}


def upgrade():
    """只插入缺失标的，保留已有设置和行情。"""
    table = sa.table(
        "instruments",
        sa.column("instrument_code"),
        sa.column("instrument_name"),
        sa.column("collection_enabled"),
        sa.column("collection_start_date"),
    )
    op.execute(
        insert(table)
        .values(
            [
                {
                    "instrument_code": code,
                    "instrument_name": name,
                    "collection_enabled": True,
                    "collection_start_date": date(2020, 1, 1),
                }
                for code, name in INSTRUMENTS.items()
            ]
        )
        .on_conflict_do_nothing(index_elements=["instrument_code"])
    )


def downgrade():
    """保留新增标的和行情，避免降级删除用户数据。"""
