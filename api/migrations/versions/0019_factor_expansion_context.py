"""扩展研究因子并登记 ETF 与行业恐贪的核验关联。"""

from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

NEW_FACTORS = (
    ("close_above_prior_high", "收盘收复昨高", "反转确认", "event", "含息收盘价严格高于前一交易日最高价。"),
    ("recovery_volume_band", "温和量能带", "反转确认", "state", "当日成交量为此前20日均量的0.8至2.5倍，过滤极端缩量和放量。"),
    ("below_ma20", "仍在MA20下方", "均线位置", "state", "含息收盘价低于当日MA20。"),
    ("close_position_positive", "收盘位于振幅上半区", "价格确认", "event", "当日有有效振幅，且收盘位于高低价区间55%或以上。"),
    ("lower_shadow_support", "长下影承接", "反转确认", "event", "当日下影线至少占振幅40%，且收盘位于振幅上半区。"),
    ("atr_overbought", "ATR归一化超买", "兑现状态", "state", "含息收盘价高于MA20达到2.0倍Wilder ATR14。"),
    ("wilder_rsi_overbought_turn_down", "Wilder RSI 超买转弱", "兑现确认", "event", "Wilder RSI14此前不低于70，本日首次较前日回落。"),
    ("close_cross_ma10_down", "收盘下破MA10", "趋势走弱", "event", "含息收盘价从MA10上方或相等位置下穿至下方。"),
    ("ma5_cross_ma10_down", "MA5下穿MA10", "趋势走弱", "event", "MA5从MA10上方或相等位置下穿至下方。"),
    ("ma5_cross_ma20_down", "MA5下穿MA20", "趋势走弱", "event", "MA5从MA20上方或相等位置下穿至下方。"),
    ("high_volume_stall", "放量高位受阻", "兑现确认", "event", "日内高点超过MA20一倍ATR、成交量至少为20日均量1.5倍，且收盘转弱。"),
    ("upper_shadow_rejection", "长上影受阻", "兑现确认", "event", "当日上影线至少占振幅40%，且收盘位于振幅下半区。"),
    ("atr_volatility_high", "ATR相对波动高位", "波动率状态", "state", "ATR14/收盘价位于截至当日最近252日的80%分位或以上。"),
    ("volatility_contracting", "短波动率收敛", "波动率状态", "state", "20日收益波动率不高于60日收益波动率的80%。"),
    ("volatility_expanding", "短波动率扩张", "波动率状态", "state", "20日收益波动率不低于60日收益波动率的120%。"),
    ("ma20_ma60_bullish", "MA20–MA60强势多头排列", "趋势状态", "state", "MA20比MA60至少高出1.0倍Wilder ATR14。"),
    ("trend_pullback_near_ma20", "上升趋势回踩MA20", "趋势回踩", "state", "MA60向上，且含息收盘价距MA20不超过0.5倍Wilder ATR14。"),
    ("valuation_low_percentile", "关联指数低估值保护", "外部估值", "state", "关联指数此前最近可得PE或PB本地回看分位不高于30%。"),
    ("valuation_high_percentile", "关联指数高估风险", "外部估值", "state", "关联指数此前最近可得PE或PB本地回看分位不低于80%。"),
    ("sentiment_extreme_fear", "行业极度恐惧", "外部情绪", "state", "已映射行业此前最近可得恐贪分数不高于20。"),
    ("sentiment_fear_rebound", "行业恐惧回升", "外部情绪", "event", "已映射行业恐贪分数此前处于极度恐惧后首次回升。"),
    ("sentiment_extreme_greed", "行业极度贪婪", "外部情绪", "state", "已映射行业此前最近可得恐贪分数不低于80。"),
)

OLD_FACTOR = (
    "oversold_recovery",
    "超跌后止跌修复",
    "反转确认",
    "event",
    "近期超跌后收盘突破昨高，并满足量能、收盘位置和MA20下方条件。",
)


def upgrade():
    """删除组合型旧因子，新增原子因子和显式恐贪映射关系。"""
    op.create_table(
        "instrument_sentiment_links",
        sa.Column(
            "instrument_code",
            sa.String(6),
            sa.ForeignKey("instruments.instrument_code"),
            primary_key=True,
            comment="ETF证券代码，关联instruments.instrument_code；与category_key组成主键",
        ),
        sa.Column(
            "category_key",
            sa.String(64),
            sa.ForeignKey("sentiment_categories.category_key"),
            primary_key=True,
            comment="行业恐贪类别标识，关联sentiment_categories.category_key；与instrument_code组成主键",
        ),
        sa.Column(
            "mapping_evidence",
            sa.Text(),
            nullable=False,
            comment="ETF与恐贪类别的核验依据，不根据名称或相关性自动推断",
        ),
        sa.Column(
            "verified_date",
            sa.Date(),
            nullable=False,
            comment="本系统确认该ETF与恐贪类别关联的北京时间日期，非情绪数据日期",
        ),
        comment="ETF与行业恐贪类别的显式核验关联；未建立关联的ETF不得使用行业恐贪因子",
    )
    op.create_index(
        "ix_instrument_sentiment_links_category_key",
        "instrument_sentiment_links",
        ["category_key"],
    )

    op.execute(
        sa.text(
            "DELETE FROM strategy_comparison_factors WHERE factor_id = 'oversold_recovery'"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM research_strategy_factors WHERE factor_id = 'oversold_recovery'"
        )
    )
    op.execute(sa.text("DELETE FROM research_factors WHERE factor_id = 'oversold_recovery'"))

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
                "chart_visible": True,
            }
            for factor_id, factor_name, category, output_type, meaning in NEW_FACTORS
        ],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO instrument_sentiment_links
                (instrument_code, category_key, mapping_evidence, verified_date)
            SELECT '518880', 'hj', :evidence, :verified_date
            WHERE EXISTS (SELECT 1 FROM instruments WHERE instrument_code = '518880')
              AND EXISTS (SELECT 1 FROM sentiment_categories WHERE category_key = 'hj')
            """
        ).bindparams(
            evidence="黄金ETF与恐贪源关联指数SGE黄金9999及标的名称核验一致",
            verified_date=date(2026, 11, 27),
        )
    )


def downgrade():
    """撤销扩展目录和显式恐贪映射。"""
    op.execute(
        sa.text(
            "DELETE FROM research_strategy_factors WHERE factor_id IN :factor_ids"
        ).bindparams(sa.bindparam("factor_ids", [item[0] for item in NEW_FACTORS], expanding=True))
    )
    op.execute(
        sa.text(
            "DELETE FROM strategy_comparison_factors WHERE factor_id IN :factor_ids"
        ).bindparams(sa.bindparam("factor_ids", [item[0] for item in NEW_FACTORS], expanding=True))
    )
    op.execute(
        sa.text("DELETE FROM research_factors WHERE factor_id IN :factor_ids").bindparams(
            sa.bindparam("factor_ids", [item[0] for item in NEW_FACTORS], expanding=True)
        )
    )
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
                "factor_id": OLD_FACTOR[0],
                "factor_name": OLD_FACTOR[1],
                "category": OLD_FACTOR[2],
                "output_type": OLD_FACTOR[3],
                "meaning": OLD_FACTOR[4],
                "chart_visible": True,
            }
        ],
    )
    op.drop_index("ix_instrument_sentiment_links_category_key", table_name="instrument_sentiment_links")
    op.drop_table("instrument_sentiment_links")
