"""新增配置内ETF档案与日度份额流。"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    """只为已配置ETF创建FundDB档案与份额流存储。"""
    op.create_table(
        "etf_catalog_profiles",
        sa.Column("instrument_code", sa.String(length=6), sa.ForeignKey("instruments.instrument_code"), primary_key=True, comment="ETF证券代码，关联instruments.instrument_code；仅已配置标的可写入"),
        sa.Column("fund_full_name", sa.Text(), nullable=True, comment="FundDB基金全称；源未提供时为空"),
        sa.Column("category_primary", sa.String(length=100), nullable=True, comment="FundDB一级分类；仅供观察，不作为策略分类"),
        sa.Column("category_tag", sa.String(length=100), nullable=True, comment="FundDB二级分类或主题标签；仅供观察"),
        sa.Column("tracking_index_code", sa.String(length=32), nullable=True, comment="FundDB建议跟踪指数完整代码；不自动建立InstrumentIndexLink"),
        sa.Column("tracking_index_name", sa.String(length=100), nullable=True, comment="FundDB建议跟踪指数名称；仅供人工核验"),
        sa.Column("index_corr", sa.Numeric(precision=10, scale=6), nullable=True, comment="FundDB基金详情中建议指数相关度，闭区间0至1；不构成映射证据"),
        sa.Column("setup_date", sa.Date(), nullable=True, comment="基金成立日期，按FundDB源值保存；可空"),
        sa.Column("management_fee_pct", sa.Numeric(precision=12, scale=6), nullable=True, comment="管理费率，百分数源口径，如0.5表示0.5%；可空"),
        sa.Column("custody_fee_pct", sa.Numeric(precision=12, scale=6), nullable=True, comment="托管费率，百分数源口径，如0.1表示0.1%；可空"),
        sa.Column("linked_otc_code", sa.String(length=32), nullable=True, comment="FundDB联接基金代码；可空"),
        sa.Column("source_url", sa.Text(), nullable=False, comment="本档案外部数据源URL，不含访问凭据"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, comment="本档案首次采集或字段修订的本地时间，带时区"),
        comment="已配置ETF的FundDB档案快照；不向instruments外扩展全市场基金目录",
    )
    op.create_table(
        "etf_flow_daily",
        sa.Column("instrument_code", sa.String(length=6), sa.ForeignKey("instruments.instrument_code"), primary_key=True, comment="ETF证券代码，关联instruments.instrument_code；仅已配置标的可写入"),
        sa.Column("trade_date", sa.Date(), primary_key=True, comment="FundDB规模或份额数据对应日期；非采集日期"),
        sa.Column("unit_shares_100m", sa.Numeric(precision=24, scale=6), nullable=True, comment="最新基金份额，单位亿份，允许源值为零；可空"),
        sa.Column("aum_100m", sa.Numeric(precision=24, scale=6), nullable=True, comment="最新基金规模，单位亿元，允许源值为零；可空"),
        sa.Column("net_share_flow_7d_100m", sa.Numeric(precision=24, scale=6), nullable=True, comment="近7日份额变动，单位亿份，正负表示申购赎回净变化；可空"),
        sa.Column("net_share_flow_30d_100m", sa.Numeric(precision=24, scale=6), nullable=True, comment="近30日份额变动，单位亿份，正负表示申购赎回净变化；可空"),
        sa.Column("discount_premium_pct", sa.Numeric(precision=16, scale=8), nullable=True, comment="FundDB源折溢价率，百分数源口径，正负均有效；可空"),
        sa.Column("purchase_status", sa.String(length=40), nullable=True, comment="源申购状态原文，如开放申购；可空"),
        sa.Column("redeem_status", sa.String(length=40), nullable=True, comment="源赎回状态原文，如开放赎回；可空"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, comment="本截面首次采集或字段修订的本地时间，带时区"),
        comment="已配置ETF的FundDB日度份额流与折溢价；仅供观察，不进入当前策略因子",
    )
    op.create_index("ix_etf_flow_daily_trade_date", "etf_flow_daily", ["trade_date"])
    op.execute("INSERT INTO jobs (job_id, schedule_enabled, scheduled_time) VALUES (7, true, '01:25')")


def downgrade():
    """撤销FundDB观察数据与任务7。"""
    op.execute("DELETE FROM runs WHERE job_id = 7")
    op.execute("DELETE FROM jobs WHERE job_id = 7")
    op.drop_index("ix_etf_flow_daily_trade_date", table_name="etf_flow_daily")
    op.drop_table("etf_flow_daily")
    op.drop_table("etf_catalog_profiles")
