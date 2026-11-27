"""新增全市场恐贪与五维环境因子。"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

NEW_FACTORS = (
    ("market_fear_extreme", "全市场极度恐惧", "全市场环境", "state", "此前最近可得全市场恐贪总分不高于25。"),
    ("market_greed_extreme", "全市场极度贪婪", "全市场环境", "state", "此前最近可得全市场恐贪总分不低于75。"),
    ("market_ivix_high", "50ETF波指高位", "全市场环境", "state", "此前最近可得50ETF期权波动率不低于22，或本地历史样本充足时处于高分位。"),
    ("market_ivix_calm", "50ETF波指低波平稳", "全市场环境", "state", "此前最近可得50ETF期权波动率不高于16，且未出现快速上升。"),
    ("market_breadth_weak", "全A创新高广度极弱", "全市场环境", "state", "此前最近可得创新高个股占比不高于1%。"),
    ("market_futures_deep_discount", "股指期货深度贴水", "全市场环境", "state", "此前最近可得沪深300股指期货年化升贴水率不高于-10%。"),
)


def upgrade():
    """创建原始观测表、登记任务6和全市场环境因子目录。"""
    op.create_table(
        "market_fear_greed_daily",
        sa.Column("trade_date", sa.Date(), primary_key=True, comment="数据源交易日期，按源值保存，不统一截为北京时间昨日"),
        sa.Column("fear_greed_score", sa.Numeric(8, 4), nullable=False, comment="全市场恐贪总分，闭区间0至100，零为有效值"),
        sa.Column("source_label", sa.String(32), nullable=True, comment="源最新快照情绪标签；仅源日期与总分完全匹配时写入，其余历史日期为空"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, comment="本条首次入库或源值实际修订的本地采集时间，带时区；未变化不重写"),
        comment="全市场恐贪指数源日频序列；零分有效，不从当前快照推断历史情绪标签",
    )
    op.create_table(
        "market_regime_factor_daily",
        sa.Column("factor_key", sa.String(32), primary_key=True, comment="源子因子标识：volatility、bx、premium、wz、strength；与trade_date组成主键"),
        sa.Column("trade_date", sa.Date(), primary_key=True, comment="数据源交易日期，按源值保存；与factor_key组成主键"),
        sa.Column("factor_name", sa.String(100), nullable=False, comment="源中文名称，不自行重命名或猜测指标含义"),
        sa.Column("raw_value", sa.Numeric(24, 6), nullable=False, comment="源原始读数，允许正负数；具体单位随factor_key和源口径保留，不擅自换算"),
        sa.Column("source_pct_year", sa.Numeric(8, 4), nullable=True, comment="源返回的近一年分位，范围0至100；仅供观察对照，不作为历史固定时点分位；可空"),
        sa.Column("source_pct_all", sa.Numeric(8, 4), nullable=True, comment="源返回的全历史分位，范围0至100；仅供观察对照，不作为历史固定时点分位；可空"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, comment="本条首次入库或字段实际修订的本地采集时间，带时区；未变化不重写"),
        comment="全市场恐贪五维环境子因子源日频序列；源分位仅供展示，不作为历史策略分位",
    )
    op.create_index("ix_market_regime_factor_daily_trade_date", "market_regime_factor_daily", ["trade_date"])
    op.execute("INSERT INTO jobs (job_id, schedule_enabled, scheduled_time) VALUES (6, true, '01:15')")
    op.execute("COMMENT ON COLUMN jobs.job_id IS '采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划，6为全市场恐贪与五维环境因子，7为ETF档案与份额流'")
    op.execute("COMMENT ON COLUMN runs.job_id IS '所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划，6为全市场恐贪与五维环境因子，7为ETF档案与份额流'")
    factor_table = sa.table("research_factors", sa.column("factor_id"), sa.column("factor_name"), sa.column("category"), sa.column("output_type"), sa.column("meaning"), sa.column("chart_visible"))
    op.bulk_insert(factor_table, [{"factor_id": factor_id, "factor_name": name, "category": category, "output_type": output_type, "meaning": meaning, "chart_visible": True} for factor_id, name, category, output_type, meaning in NEW_FACTORS])


def downgrade():
    """撤销任务6及其原始环境观测。"""
    factor_ids = [item[0] for item in NEW_FACTORS]
    op.execute(sa.text("DELETE FROM research_strategy_factors WHERE factor_id IN :factor_ids").bindparams(sa.bindparam("factor_ids", factor_ids, expanding=True)))
    op.execute(sa.text("DELETE FROM strategy_comparison_factors WHERE factor_id IN :factor_ids").bindparams(sa.bindparam("factor_ids", factor_ids, expanding=True)))
    op.execute(sa.text("DELETE FROM research_factors WHERE factor_id IN :factor_ids").bindparams(sa.bindparam("factor_ids", factor_ids, expanding=True)))
    op.execute("DELETE FROM jobs WHERE job_id = 6")
    op.execute("COMMENT ON COLUMN jobs.job_id IS '采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划'")
    op.execute("COMMENT ON COLUMN runs.job_id IS '所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划'")
    op.drop_index("ix_market_regime_factor_daily_trade_date", table_name="market_regime_factor_daily")
    op.drop_table("market_regime_factor_daily")
    op.drop_table("market_fear_greed_daily")
