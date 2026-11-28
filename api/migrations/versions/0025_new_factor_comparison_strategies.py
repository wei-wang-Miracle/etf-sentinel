"""登记三套可比较观察的新因子策略与研究因子的展示关系。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

STRATEGY_FACTORS = [
    ("trend_pullback", "above_ma250", "filter", 0),
    ("trend_pullback", "adx_trending", "filter", 1),
    ("trend_pullback", "trend_pullback_near_ma20", "trigger", 2),
    ("trend_pullback", "turning_top", "exit", 3),
    ("trend_pullback", "adx_choppy", "exit", 4),
    ("trend_pullback", "atr_overbought", "exit", 5),
    ("volatility_contraction_breakout", "volatility_contracting", "filter", 0),
    ("volatility_contraction_breakout", "atr_box_breakout", "trigger", 1),
    ("volatility_contraction_breakout", "strong_close", "confirmation", 2),
    ("volatility_contraction_breakout", "turning_top", "exit", 3),
    ("volatility_contraction_breakout", "high_volume_stall", "exit", 4),
    ("volatility_contraction_breakout", "close_cross_ma10_down", "exit", 5),
    ("value_sentiment_reversal", "erp_high_percentile", "filter", 0),
    ("value_sentiment_reversal", "dividend_yield_high", "filter", 1),
    ("value_sentiment_reversal", "valuation_low_percentile", "filter", 2),
    ("value_sentiment_reversal", "market_fear_extreme", "filter", 3),
    ("value_sentiment_reversal", "oversold_recovery", "trigger", 4),
    ("value_sentiment_reversal", "turning_top", "exit", 5),
    ("value_sentiment_reversal", "valuation_high_percentile", "exit", 6),
    ("value_sentiment_reversal", "market_greed_extreme", "exit", 7),
    ("value_sentiment_reversal", "wilder_rsi_overbought_turn_down", "exit", 8),
]


def upgrade():
    """幂等写入三套新因子对比策略与因子展示关系。"""
    relation_table = sa.table(
        "research_strategy_factors",
        sa.column("strategy_id", sa.String()),
        sa.column("factor_id", sa.String()),
        sa.column("role", sa.String()),
        sa.column("display_order", sa.Integer()),
    )
    rows = [
        {
            "strategy_id": strategy_id,
            "factor_id": factor_id,
            "role": role,
            "display_order": order,
        }
        for strategy_id, factor_id, role, order in STRATEGY_FACTORS
    ]
    stmt = insert(relation_table).values(rows).on_conflict_do_nothing(
        index_elements=["strategy_id", "factor_id"]
    )
    op.execute(stmt)


def downgrade():
    """移除三套新因子对比策略的因子展示关系（并清理可能引用它们的未采用比较记录）。"""
    ids = "('trend_pullback', 'volatility_contraction_breakout', 'value_sentiment_reversal')"
    op.execute(
        sa.text(
            f"DELETE FROM strategy_comparison_factors WHERE strategy_id IN {ids}"
        )
    )
    op.execute(
        sa.text(
            f"DELETE FROM research_strategy_factors WHERE strategy_id IN {ids}"
        )
    )
