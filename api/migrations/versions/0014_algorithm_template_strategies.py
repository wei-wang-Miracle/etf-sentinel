"""清理旧配置策略记录并改用不可变算法模板流程。"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

OLD_TABLE_COMMENTS = {
    "strategy_observations": "ETF策略观察版本；采用规则不代表已下单或实际成交，修改规则需新建版本",
    "saved_strategies": "用户命名的单ETF策略身份；保存不自动启用，不代表真实交易",
    "strategy_comparisons": "单ETF自定义策略统一比较记录；包含失败对象及研究证据类型，不覆盖既有回测或启用状态",
    "saved_strategy_versions": "自定义策略不可变版本；规则、预算、费用和原回测固定，编辑需保存新版本",
    "strategy_research_batches": "ETF策略研究批次；冻结持仓范围、开发验证区间、每只五万元假设与全部成功失败结果",
}

COLUMN_TYPES = {
    ("strategy_observations", "strategy_version_id"): sa.Integer(),
    ("strategy_observations", "research_batch_id"): sa.Integer(),
    ("strategy_observations", "rule_snapshot"): sa.JSON(),
    ("saved_strategies", "strategy_id"): sa.Integer(),
    ("strategy_comparisons", "input_snapshot"): sa.JSON(),
    ("strategy_comparisons", "result_snapshot"): sa.JSON(),
    ("saved_strategy_versions", "strategy_version_id"): sa.Integer(),
    ("saved_strategy_versions", "strategy_name"): sa.String(100),
    ("saved_strategy_versions", "configuration"): sa.JSON(),
    ("strategy_research_batches", "input_snapshot"): sa.JSON(),
    ("strategy_research_batches", "result_snapshot"): sa.JSON(),
}


def set_table_comment(table, comment, existing):
    """通过Alembic原生注释操作更新业务表说明。"""
    op.create_table_comment(table, comment, existing_comment=existing)


def upgrade():
    """删除旧策略与关联回测，保留行情、估值及账户基础资料。"""
    connection = op.get_bind()
    run_ids = list(
        connection.execute(
            sa.text("SELECT backtest_run_id FROM saved_strategy_versions")
        ).scalars()
    )
    op.execute(sa.text("DELETE FROM strategy_execution_links"))
    op.execute(sa.text("DELETE FROM strategy_signals"))
    op.execute(sa.text("DELETE FROM strategy_observations"))
    op.execute(sa.text("DELETE FROM strategy_research_batches"))
    op.execute(sa.text("DELETE FROM saved_strategy_versions"))
    op.execute(sa.text("DELETE FROM strategy_comparisons"))
    op.execute(sa.text("DELETE FROM saved_strategies"))
    op.execute(sa.text("DELETE FROM strategy_drafts"))
    if run_ids:
        connection.execute(
            sa.text(
                "DELETE FROM backtest_runs "
                "WHERE backtest_run_id IN :run_ids OR strategy_key = 'custom_conditions'"
            ).bindparams(sa.bindparam("run_ids", expanding=True)),
            {"run_ids": run_ids},
        )
    else:
        op.execute(
            sa.text("DELETE FROM backtest_runs WHERE strategy_key = 'custom_conditions'")
        )
    op.drop_table("strategy_drafts")

    comments = (
        ("strategy_observations", None, "ETF算法模板观察版本；采用不代表已下单或实际成交，更新模板需新建版本"),
        ("strategy_observations", "strategy_version_id", "采用的算法模板保存版本编号；NULL表示已退役的旧持仓候选观察"),
        ("strategy_observations", "research_batch_id", "模板采用记录所属研究批次编号"),
        ("strategy_observations", "rule_snapshot", "不可变模板JSON：模板标识和版本、算法及顶底版本、ETF冻结参数、模型状态起点、研究本金与成本；不含真实账户本金"),
        ("saved_strategies", None, "用户命名的单ETF算法模板身份；保存不自动启用，不代表真实交易"),
        ("saved_strategies", "strategy_id", "算法模板策略稳定编号，同一命名策略的不可变版本共用"),
        ("strategy_comparisons", None, "单ETF算法模板统一比较记录；包含模板版本、失败对象及研究证据类型，不覆盖既有回测或启用状态"),
        ("strategy_comparisons", "input_snapshot", "不可变JSON：settings统一区间本金费用、candidates模板及版本、market行情权益日历、external各日期外部指标与采集证据、引擎及算法版本"),
        ("strategy_comparisons", "result_snapshot", "不可变JSON：tracks各模板与持有参照的status成功失败、reason原因、backtest_id、account日权益成交分红绩效、完整平仓轮次及未平仓诊断；complete表示全部成功"),
        ("saved_strategy_versions", None, "算法模板不可变版本；模板版本、预算、费用和原回测固定，更新需保存新版本"),
        ("saved_strategy_versions", "strategy_version_id", "算法模板策略具体版本唯一编号，与稳定strategy_id不同"),
        ("saved_strategy_versions", "strategy_name", "此模板版本的用户可读中文名称，非收益承诺"),
        ("saved_strategy_versions", "configuration", "不可变JSON：template服务端冻结模板标识版本、ETF参数及算法版本，settings记录回测日期本金成本；不接受用户配置内部指标阈值"),
        ("strategy_research_batches", None, "ETF算法模板采用记录批次；冻结模板版本、回测来源及采用时间，不表示真实成交"),
        ("strategy_research_batches", "input_snapshot", "冻结采用输入JSON：模板保存版本编号、回测设置与引擎版本；不含真实账户本金"),
        ("strategy_research_batches", "result_snapshot", "冻结采用结果JSON：关联比较编号、回测编号及后续观察状态"),
    )
    for table, column, comment in comments:
        if column is None:
            set_table_comment(table, comment, OLD_TABLE_COMMENTS[table])
        else:
            op.alter_column(table, column, existing_type=COLUMN_TYPES[(table, column)], comment=comment)


def downgrade():
    """恢复旧草稿表结构；已清理的策略与回测数据不恢复。"""
    op.create_table(
        "strategy_drafts",
        sa.Column("instrument_code", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft_snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["instrument_code"], ["instruments.instrument_code"]),
        sa.PrimaryKeyConstraint("instrument_code"),
        comment="单ETF最近编辑草稿；可覆盖保存，独立于不可变策略版本和观察状态",
    )
    op.alter_column(
        "strategy_observations", "rule_snapshot", existing_type=sa.JSON(),
        comment="不可变规则JSON：候选key、策略版本、参数、资金分配百分数、每只五万元及成本；不含真实账户本金",
    )
    op.alter_column(
        "strategy_observations", "strategy_version_id", existing_type=sa.Integer(),
        comment="自定义策略版本编号；NULL表示旧持仓候选观察，保留原批次语义",
    )
    op.alter_column(
        "strategy_observations", "research_batch_id", existing_type=sa.Integer(),
        comment="规则来源研究批次编号",
    )
    op.create_table_comment("strategy_observations", OLD_TABLE_COMMENTS["strategy_observations"], existing_comment="ETF算法模板观察版本；采用不代表已下单或实际成交，更新模板需新建版本")
    op.create_table_comment("saved_strategies", OLD_TABLE_COMMENTS["saved_strategies"], existing_comment="用户命名的单ETF算法模板身份；保存不自动启用，不代表真实交易")
    op.alter_column(
        "saved_strategies", "strategy_id", existing_type=sa.Integer(),
        comment="自定义策略稳定编号，同一策略的各不可变版本共用",
    )
    op.create_table_comment("strategy_comparisons", OLD_TABLE_COMMENTS["strategy_comparisons"], existing_comment="单ETF算法模板统一比较记录；包含模板版本、失败对象及研究证据类型，不覆盖既有回测或启用状态")
    op.alter_column(
        "strategy_comparisons", "input_snapshot", existing_type=sa.JSON(),
        comment="不可变JSON：settings统一区间本金费用、candidates规则与版本、market行情权益日历、external各日期外部指标与采集证据、引擎与条件版本",
    )
    op.alter_column(
        "strategy_comparisons", "result_snapshot", existing_type=sa.JSON(),
        comment="不可变JSON：tracks各策略与持有参照的status成功失败、reason原因、backtest_id、account日权益成交分红绩效、diagnostics及evidence_type；complete表示全部成功",
    )
    op.create_table_comment("saved_strategy_versions", OLD_TABLE_COMMENTS["saved_strategy_versions"], existing_comment="算法模板不可变版本；模板版本、预算、费用和原回测固定，更新需保存新版本")
    op.create_table_comment("strategy_research_batches", OLD_TABLE_COMMENTS["strategy_research_batches"], existing_comment="ETF算法模板采用记录批次；冻结模板版本、回测来源及采用时间，不表示真实成交")
    op.alter_column(
        "saved_strategy_versions", "strategy_version_id", existing_type=sa.Integer(),
        comment="自定义策略具体版本唯一编号，与稳定strategy_id不同",
    )
    op.alter_column(
        "saved_strategy_versions", "strategy_name", existing_type=sa.String(100),
        comment="此版本的用户可读中文策略名称，非收益承诺",
    )
    op.alter_column(
        "saved_strategy_versions", "configuration", existing_type=sa.JSON(),
        comment="不可变JSON：rule买卖条件组及资金分配、settings回测日期本金成本；条件含指标参数比较符阈值，单位由条件注册版本定义",
    )
    op.alter_column(
        "strategy_research_batches", "input_snapshot", existing_type=sa.JSON(),
        comment="冻结输入JSON：持仓代码及源日期、候选参数版本、每只50000元、成本、开发验证区间；非真实本金",
    )
    op.alter_column(
        "strategy_research_batches", "result_snapshot", existing_type=sa.JSON(),
        comment="冻结输出JSON：每只ETF及组合的各区间候选净值指标、实验编号、失败原因；缺失不补零",
    )
    op.create_table_comment(
        "strategy_research_batches",
        OLD_TABLE_COMMENTS["strategy_research_batches"],
        existing_comment="ETF算法模板采用记录批次；冻结模板版本、回测来源及采用时间，不表示真实成交",
    )
