"""删除旧策略研究数据，以因子观察和当前策略分配重建策略域。"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

# 固定本次迁移的目录数据，后续因子迭代不改变历史迁移。
FACTORS = (
    (
        "turning_bottom",
        "阶段底部确认",
        "结构确认",
        "event",
        "因果状态机在该交易日确认阶段底部，不代表买入信号。",
    ),
    (
        "turning_top",
        "阶段顶部确认",
        "结构确认",
        "event",
        "因果状态机在该交易日确认阶段顶部，不代表卖出指令。",
    ),
    (
        "ma5_cross_ma20_up",
        "短均线上穿中期均线",
        "趋势转折",
        "event",
        "MA5 从 MA20 下方上穿至上方的交易日。",
    ),
    (
        "box_breakout_up",
        "箱体向上突破",
        "突破事件",
        "event",
        "当日含息收盘价高于此前20个交易日最高收盘价；连创新高可以连续标记。",
    ),
    (
        "volume_breakout_up",
        "放量向上突破",
        "突破确认",
        "event",
        "向上突破同日的成交量至少为此前20日均量的1.1倍。",
    ),
    (
        "atr_oversold",
        "ATR归一化超跌",
        "超跌状态",
        "state",
        "含息收盘价低于MA20达到1.5倍Wilder ATR14。",
    ),
    (
        "oversold_recovery",
        "超跌后止跌修复",
        "反转确认",
        "event",
        "近期超跌后收盘突破昨高，并满足量能、收盘位置和MA20下方条件。",
    ),
    (
        "wilder_rsi_oversold",
        "Wilder RSI 超卖",
        "超跌状态",
        "state",
        "Wilder RSI14 不高于35；只标记进入状态的首日。",
    ),
    (
        "ma60_rising",
        "MA60 向上",
        "趋势状态",
        "state",
        "MA60 高于五个交易日前；只标记进入状态的首日。",
    ),
    (
        "strong_close",
        "日内强势收盘",
        "价格确认",
        "event",
        "当日有有效振幅，且收盘位于当日高低价区间的60%或以上。",
    ),
    (
        "atr_box_breakout",
        "ATR 余量突破",
        "突破事件",
        "event",
        "超过此前20日最高收盘的幅度严格大于0.2倍Wilder ATR14。",
    ),
)
RELATIONS = {
    "range_breakout": (("box_breakout_up", "trigger"), ("turning_top", "risk")),
    "bottom_confirmation": (("turning_bottom", "trigger"), ("turning_top", "risk")),
    "hybrid_reversal": (("turning_bottom", "trigger"), ("turning_top", "risk")),
    "range_breakout_research": (
        ("atr_box_breakout", "trigger"),
        ("ma60_rising", "confirmation"),
        ("strong_close", "confirmation"),
        ("turning_top", "risk"),
    ),
    "left_reversal_research": (
        ("atr_oversold", "trigger"),
        ("wilder_rsi_oversold", "trigger"),
        ("oversold_recovery", "trigger"),
    ),
}


def upgrade():
    # 先标记由旧比较独占的回测轨道；未被旧比较引用的通用持有回测保留。
    op.execute("""
        CREATE TEMPORARY TABLE retired_strategy_run_ids ON COMMIT DROP AS
        SELECT DISTINCT (track ->> 'backtest_id')::integer AS backtest_run_id
        FROM strategy_comparisons,
             LATERAL json_array_elements(result_snapshot -> 'tracks') AS track
        WHERE track ->> 'backtest_id' IS NOT NULL
    """)
    for table in (
        "strategy_execution_links",
        "strategy_signals",
        "strategy_observations",
        "strategy_research_batches",
        "saved_strategy_versions",
        "saved_strategies",
        "strategy_comparisons",
    ):
        op.drop_table(table)
    op.execute("""
        DELETE FROM backtest_runs WHERE strategy_key = 'algorithm_template'
        OR backtest_run_id IN (SELECT backtest_run_id FROM retired_strategy_run_ids)
    """)
    op.create_table(
        "research_factors",
        sa.Column(
            "factor_id",
            sa.String(length=64),
            nullable=False,
            comment="稳定因子身份，关联代码中的因子计算实现",
        ),
        sa.Column(
            "factor_name",
            sa.String(length=100),
            nullable=False,
            comment="因子中文名称，用于图例、悬停和策略说明",
        ),
        sa.Column(
            "category",
            sa.String(length=40),
            nullable=False,
            comment="因子业务分类，例如结构确认、趋势转折、突破事件、超跌状态或反转确认",
        ),
        sa.Column(
            "output_type",
            sa.String(length=16),
            nullable=False,
            comment="因子输出类型：event表示确认事件，state表示进入状态时的标记",
        ),
        sa.Column(
            "meaning",
            sa.String(),
            nullable=False,
            comment="面向用户的输出含义及非买卖指令说明，不包含可执行表达式",
        ),
        sa.Column(
            "chart_visible",
            sa.Boolean(),
            nullable=False,
            comment="是否允许在行情日K图提供显示标记",
        ),
        sa.PrimaryKeyConstraint("factor_id"),
        comment="代码实现的可观察市场事件和状态目录；不保存可执行算法或因子版本",
    )
    op.create_table(
        "research_strategy_factors",
        sa.Column(
            "strategy_id",
            sa.String(length=64),
            nullable=False,
            comment="代码目录中的当前策略身份；算法实现不入库",
        ),
        sa.Column(
            "factor_id",
            sa.String(length=64),
            nullable=False,
            comment="策略使用的因子稳定身份",
        ),
        sa.Column(
            "role",
            sa.String(length=24),
            nullable=False,
            comment="因子在策略中的作用：trigger、confirmation、filter、exit或risk",
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            comment="策略说明中因子关系的展示顺序，从0开始",
        ),
        sa.ForeignKeyConstraint(
            ["factor_id"],
            ["research_factors.factor_id"],
        ),
        sa.PrimaryKeyConstraint("strategy_id", "factor_id"),
        comment="当前策略与观察因子的组成关系；计算顺序和规则由代码负责",
    )
    op.create_index(
        "ix_research_strategy_factors_factor_id",
        "research_strategy_factors",
        ["factor_id"],
        unique=False,
    )
    op.create_table(
        "strategy_comparisons",
        sa.Column(
            "comparison_id",
            sa.Integer(),
            nullable=False,
            comment="本次统一比较的唯一编号",
        ),
        sa.Column(
            "instrument_code",
            sa.String(length=6),
            nullable=False,
            comment="比较的唯一可交易ETF证券代码",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="比较完成并保存的带时区本地时间",
        ),
        sa.Column(
            "input_sha256",
            sa.String(length=64),
            nullable=False,
            comment="本次比较全部策略身份、共同假设与市场输入规范JSON的SHA256摘要",
        ),
        sa.Column(
            "input_snapshot",
            sa.JSON(),
            nullable=False,
            comment="不可变JSON：settings统一区间本金费用、candidates当前策略身份、market行情权益日历、external外部指标及引擎/数据摘要",
        ),
        sa.Column(
            "result_snapshot",
            sa.JSON(),
            nullable=False,
            comment="不可变JSON：tracks策略与持有参照的状态、原因、回测编号、日权益成交分红绩效及平仓诊断",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_code"],
            ["instruments.instrument_code"],
        ),
        sa.PrimaryKeyConstraint("comparison_id"),
        comment="单ETF当前策略统一比较记录；保存本次研究证据，不构成可选择的策略版本",
    )
    op.create_table(
        "instrument_strategy_assignments",
        sa.Column(
            "assignment_id",
            sa.Integer(),
            nullable=False,
            comment="当前策略分配唯一编号；更换策略时保持分配身份",
        ),
        sa.Column(
            "instrument_code",
            sa.String(length=6),
            nullable=False,
            comment="可交易ETF六位代码；每只ETF至多一条当前分配",
        ),
        sa.Column(
            "strategy_id",
            sa.String(length=64),
            nullable=False,
            comment="当前采用的服务端策略身份；仅研究策略不可分配",
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            comment="是否为该ETF生成后续盘前计划；false表示暂停",
        ),
        sa.Column(
            "comparison_id",
            sa.Integer(),
            nullable=False,
            comment="用户据以采用该策略的成功比较记录",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="当前分配首次采用或替换的本地时间，带时区",
        ),
        sa.Column(
            "settings_snapshot",
            sa.JSON(),
            nullable=False,
            comment="采用时账户本金、交易成本和模型状态起点；不是可选历史策略版本",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"],
            ["strategy_comparisons.comparison_id"],
        ),
        sa.ForeignKeyConstraint(
            ["instrument_code"],
            ["instruments.instrument_code"],
        ),
        sa.PrimaryKeyConstraint("assignment_id"),
        comment="每只ETF唯一当前策略分配；未采用时无记录，暂停不清除历史信号",
    )
    op.create_index(
        "uq_instrument_strategy_assignment",
        "instrument_strategy_assignments",
        ["instrument_code"],
        unique=True,
    )
    op.create_table(
        "strategy_comparison_factors",
        sa.Column(
            "comparison_id", sa.Integer(), nullable=False, comment="所属策略比较记录"
        ),
        sa.Column(
            "strategy_id",
            sa.String(length=64),
            nullable=False,
            comment="本轨道运行的代码目录策略身份",
        ),
        sa.Column(
            "factor_id",
            sa.String(length=64),
            nullable=False,
            comment="本轨道实际使用的因子身份",
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"],
            ["strategy_comparisons.comparison_id"],
        ),
        sa.ForeignKeyConstraint(
            ["factor_id"],
            ["research_factors.factor_id"],
        ),
        sa.PrimaryKeyConstraint("comparison_id", "strategy_id", "factor_id"),
        comment="单次比较轨道与实际使用因子的关系；仅研究引用记录，不保存因子代码版本",
    )
    op.create_table(
        "strategy_signals",
        sa.Column("signal_id", sa.Integer(), nullable=False, comment="日计划唯一编号"),
        sa.Column(
            "assignment_id",
            sa.Integer(),
            nullable=False,
            comment="产生计划时所属的ETF当前策略分配编号",
        ),
        sa.Column(
            "instrument_code",
            sa.String(length=6),
            nullable=False,
            comment="计划对应可交易ETF六位代码",
        ),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="首次生成时间，带时区；同一分配同一执行日重复请求不修改",
        ),
        sa.Column(
            "data_cutoff",
            sa.Date(),
            nullable=False,
            comment="决策所用完整行情最后交易日，不晚于生成时已采集数据",
        ),
        sa.Column(
            "execution_date",
            sa.Date(),
            nullable=False,
            comment="最早执行的尚未开盘交易日；不表示实际成交日",
        ),
        sa.Column(
            "plan_snapshot",
            sa.JSON(),
            nullable=False,
            comment="冻结计划JSON：方向、研究目标比例份额、实际及可用份额、数据源日期、原因、因子、输入摘要和待资金核对提示",
        ),
        sa.Column(
            "evidence_snapshot",
            sa.JSON(),
            nullable=False,
            comment="决策证据JSON：策略身份、规则与采用时刻、当时的行情权益、采集时刻及账户证据；不使用后来修订覆盖",
        ),
        sa.Column(
            "skip_note",
            sa.String(),
            nullable=True,
            comment="用户明确不执行的原因；空表示未主动跳过，不等于未成交证明",
        ),
        sa.Column(
            "skipped_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="人工跳过确认时间，带时区；未跳过为空",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["instrument_strategy_assignments.assignment_id"],
        ),
        sa.ForeignKeyConstraint(
            ["instrument_code"],
            ["instruments.instrument_code"],
        ),
        sa.PrimaryKeyConstraint("signal_id"),
        comment="ETF逐日策略计划与生成时证据；提示、人工确认和真实成交分开，不回填历史信号",
    )
    op.create_index(
        "uq_strategy_signal_assignment_day",
        "strategy_signals",
        ["assignment_id", "execution_date"],
        unique=True,
    )
    op.create_table(
        "strategy_execution_links",
        sa.Column(
            "execution_link_id",
            sa.Integer(),
            nullable=False,
            comment="执行关联唯一编号",
        ),
        sa.Column(
            "signal_id",
            sa.Integer(),
            nullable=False,
            comment="人工确认对应的日计划编号",
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            nullable=False,
            comment="本地账户编号，不是资金账号",
        ),
        sa.Column(
            "curr_date",
            sa.Date(),
            nullable=False,
            comment="源委托关联日期，与account_id及entrust_no共同定位累计委托",
        ),
        sa.Column(
            "entrust_no",
            sa.String(length=32),
            nullable=False,
            comment="源累计委托号；不代表逐笔成交编号",
        ),
        sa.Column(
            "confirmed_trade_date",
            sa.Date(),
            nullable=False,
            comment="用户依据对账资料确认的实际成交日期，必须等于计划执行日",
        ),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="人工关联确认时间，带时区；不当作成交时间",
        ),
        sa.Column(
            "confirmed_amount",
            sa.Numeric(precision=20, scale=4),
            nullable=False,
            comment="确认时源累计成交份额快照，份；源后续变化用于展示修订差异",
        ),
        sa.Column(
            "confirmation_note",
            sa.String(),
            nullable=False,
            comment="人工确认依据或偏离说明，不可空白；不包含自动下单含义",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "curr_date", "entrust_no"],
            [
                "account_entrusts.account_id",
                "account_entrusts.curr_date",
                "account_entrusts.entrust_no",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.account_id"],
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["strategy_signals.signal_id"],
        ),
        sa.PrimaryKeyConstraint("execution_link_id"),
        comment="真实累计委托与计划的人工确认关联；一条委托最多归属一个计划，源数量修订后重新核对",
    )
    op.create_index(
        "uq_strategy_execution_entrust",
        "strategy_execution_links",
        ["account_id", "curr_date", "entrust_no"],
        unique=True,
    )

    factor_table = sa.table(
        "research_factors",
        *(
            sa.column(key)
            for key in (
                "factor_id",
                "factor_name",
                "category",
                "output_type",
                "meaning",
                "chart_visible",
            )
        ),
    )
    op.bulk_insert(
        factor_table,
        [
            {
                "factor_id": k,
                "factor_name": name,
                "category": category,
                "output_type": kind,
                "meaning": meaning,
                "chart_visible": True,
            }
            for k, name, category, kind, meaning in FACTORS
        ],
    )
    relation_table = sa.table(
        "research_strategy_factors",
        *(
            sa.column(key)
            for key in (
                "strategy_id",
                "factor_id",
                "role",
                "display_order",
            )
        ),
    )
    op.bulk_insert(
        relation_table,
        [
            {
                "strategy_id": strategy_id,
                "factor_id": factor_id,
                "role": role,
                "display_order": order,
            }
            for strategy_id, factors in RELATIONS.items()
            for order, (factor_id, role) in enumerate(factors)
        ],
    )


def downgrade():
    raise RuntimeError(
        "迁移0018永久删除旧策略数据，不支持降级；需要恢复时使用迁移前备份"
    )
