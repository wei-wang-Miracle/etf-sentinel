"""新增 ETF 跨源停牌核验记录表，供因子图放行真实停牌或份额折算停牌日。"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    """创建跨源停牌核验明细表及完整中文注释。"""
    op.create_table(
        "instrument_verified_suspensions",
        sa.Column(
            "instrument_code",
            sa.String(length=6),
            sa.ForeignKey("instruments.instrument_code"),
            primary_key=True,
            comment="ETF证券代码，关联instruments.instrument_code",
        ),
        sa.Column(
            "trade_date",
            sa.Date(),
            primary_key=True,
            comment="跨源核验确认无交易的交易所交易日期（Asia/Shanghai交易日），非采集日期",
        ),
        sa.Column(
            "sources",
            sa.JSON(),
            nullable=False,
            comment="共同确认当日无交易的数据源名称列表（至少两个独立源），如[\"eastmoney\",\"sina\",\"tencent\"]",
        ),
        sa.Column(
            "calendar_version",
            sa.String(length=100),
            nullable=False,
            comment="执行停牌审计时使用的交易所日历版本标识",
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="本条停牌核验写入或来源集合修订的本地时间，带时区",
        ),
        comment="跨源核验确认无交易的ETF真实停牌日（含份额折算停牌）；仅供日历连续性放行，不补造行情",
    )


def downgrade():
    """移除跨源停牌核验明细表。"""
    op.drop_table("instrument_verified_suspensions")
