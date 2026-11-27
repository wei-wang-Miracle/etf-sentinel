"""登记估值扩展和长期技术观察因子。"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

NEW_FACTORS = (
    ("erp_high_percentile", "股债高性价比保护", "外部估值", "state", "关联指数此前最近可得股债风险溢价本地回看分位不低于70%。", True),
    ("erp_low_percentile", "股债性价比偏低", "外部估值", "state", "关联指数此前最近可得股债风险溢价本地回看分位不高于20%。", True),
    ("dividend_yield_high", "高股息率保护", "外部估值", "state", "关联指数此前最近可得股息率本地回看分位不低于70%。", True),
    ("above_ma250", "年线多头区间", "趋势状态", "state", "含息收盘价严格高于当日MA250；不足250根交易日不标记。", True),
    ("ma120_rising", "半年线向上", "趋势状态", "state", "当日MA120严格高于五个交易日前；不足125根交易日不标记。", False),
    ("adx_trending", "趋势形成状态", "趋势状态", "state", "Wilder ADX14不低于25，且+DI14高于-DI14。", False),
    ("adx_choppy", "无趋势震荡状态", "趋势状态", "state", "Wilder ADX14低于18，表示价格方向性不足。", False),
    ("deep_drawdown_60d", "60日深度回撤状态", "超跌状态", "state", "含息收盘相对60日内最高收盘回撤10%至35%。", True),
    ("consecutive_down_exhaustion", "连跌耗竭观察", "超跌状态", "state", "含息收盘连续下跌不少于4个交易日。", True),
    ("gap_up_strong", "强势跳空高开", "突破确认", "event", "当日低点较昨高跳空至少0.3倍ATR14，且收盘位于有效振幅上半区。", True),
    ("relative_strength_20d_positive", "相对沪深300跑赢", "相对强弱", "state", "若本地沪深300指数同日序列完整，ETF过去20日含息收益至少跑赢1.5个百分点。", False),
)


def upgrade():
    """插入阶段一新增因子目录项。"""
    factor_table = sa.table(
        "research_factors",
        sa.column("factor_id"),
        sa.column("factor_name"),
        sa.column("category"),
        sa.column("output_type"),
        sa.column("meaning"),
        sa.column("chart_visible"),
    )
    op.bulk_insert(
        factor_table,
        [
            {
                "factor_id": factor_id,
                "factor_name": factor_name,
                "category": category,
                "output_type": output_type,
                "meaning": meaning,
                "chart_visible": chart_visible,
            }
            for factor_id, factor_name, category, output_type, meaning, chart_visible in NEW_FACTORS
        ],
    )


def downgrade():
    """删除阶段一因子及其可能产生的关联记录。"""
    factor_ids = [item[0] for item in NEW_FACTORS]
    op.execute(
        sa.text("DELETE FROM research_strategy_factors WHERE factor_id IN :factor_ids").bindparams(
            sa.bindparam("factor_ids", factor_ids, expanding=True)
        )
    )
    op.execute(
        sa.text("DELETE FROM strategy_comparison_factors WHERE factor_id IN :factor_ids").bindparams(
            sa.bindparam("factor_ids", factor_ids, expanding=True)
        )
    )
    op.execute(
        sa.text("DELETE FROM research_factors WHERE factor_id IN :factor_ids").bindparams(
            sa.bindparam("factor_ids", factor_ids, expanding=True)
        )
    )
