"""创建首期行情结构并预置五只标的。"""

from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """创建固定版本的表结构和初始配置。"""
    op.create_table(
        "instruments",
        sa.Column("code", sa.String(6), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
    )
    fields = [
        sa.Column(
            "code", sa.String(6), sa.ForeignKey("instruments.code"), primary_key=True
        ),
        sa.Column("date", sa.Date(), primary_key=True),
    ]
    fields += [
        sa.Column(n, sa.Numeric(24, 8), nullable=False)
        for n in ["open", "high", "low", "close"]
    ]
    fields += [
        sa.Column(n, sa.Numeric(30, 4), nullable=False) for n in ["volume", "amount"]
    ]
    fields += [
        sa.Column("change_pct", sa.Numeric(20, 8)),
        sa.Column("adjusted_close", sa.Numeric(24, 8)),
        sa.Column("source_updated_at", sa.String()),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    ]
    op.create_table("candles", *fields)
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("time", sa.String(), nullable=False),
        sa.Column("last_scheduled_date", sa.Date()),
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("logs", sa.JSON(), nullable=False),
    )
    op.create_table(
        "collection_windows",
        sa.Column(
            "code", sa.String(6), sa.ForeignKey("instruments.code"), primary_key=True
        ),
        sa.Column("start", sa.Date(), primary_key=True),
        sa.Column("end", sa.Date(), nullable=False),
    )
    table = sa.table(
        "instruments",
        sa.column("code"),
        sa.column("name"),
        sa.column("enabled"),
        sa.column("start_date"),
    )
    op.bulk_insert(
        table,
        [
            {
                "code": c,
                "name": "名称待采集",
                "enabled": True,
                "start_date": date(2020, 1, 1),
            }
            for c in ["510500", "512100", "159531", "159205", "588080"]
        ],
    )
    op.execute("INSERT INTO jobs (id, enabled, time) VALUES (1, true, '01:00')")


def downgrade():
    """按依赖顺序撤销首期结构。"""
    for table in ["collection_windows", "runs", "jobs", "candles", "instruments"]:
        op.drop_table(table)
