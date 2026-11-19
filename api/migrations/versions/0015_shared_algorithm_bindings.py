"""记录共享算法与ETF绑定，保留已有研究及盘前信号。"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

TABLE_OLD = "用户命名的单ETF算法模板身份；保存不自动启用，不代表真实交易"
TABLE_NEW = "共享算法与可交易ETF的绑定；保存不自动启用，不代表真实交易"
STRATEGY_OLD = "自定义策略稳定编号，同一策略的各不可变版本共用"
STRATEGY_NEW = "算法与ETF绑定的稳定编号，后续不可变回测记录共用"
NAME_OLD = "此模板版本的用户可读中文名称，非收益承诺"
NAME_NEW = "保存时的算法中文名称；历史记录保留原名称，非收益承诺"
SNAPSHOT_OLD = "不可变JSON：template服务端冻结模板标识版本、ETF参数及算法版本，settings记录回测日期本金成本；不接受用户配置内部指标阈值"
SNAPSHOT_NEW = "不可变JSON：template为冻结算法标识、版本和规则，settings为回测日期、本金、成本及ETF；历史逐ETF规则保留原快照"


def upgrade():
    op.add_column("saved_strategies", sa.Column(
        "algorithm_template_id", sa.String(64), nullable=True,
        comment="服务端算法模板稳定标识，不含版本；NULL仅表示历史逐ETF规则",
    ))
    op.create_index("uq_saved_strategy_etf_algorithm", "saved_strategies", ["instrument_code", "algorithm_template_id"], unique=True)
    op.create_table_comment("saved_strategies", TABLE_NEW, existing_comment=TABLE_OLD)
    op.alter_column("saved_strategies", "strategy_id", existing_type=sa.Integer(), comment=STRATEGY_NEW)
    op.alter_column("saved_strategy_versions", "strategy_name", existing_type=sa.String(100), comment=NAME_NEW)
    op.alter_column("saved_strategy_versions", "configuration", existing_type=sa.JSON(), comment=SNAPSHOT_NEW)


def downgrade():
    op.alter_column("saved_strategy_versions", "configuration", existing_type=sa.JSON(), comment=SNAPSHOT_OLD)
    op.alter_column("saved_strategy_versions", "strategy_name", existing_type=sa.String(100), comment=NAME_OLD)
    op.alter_column("saved_strategies", "strategy_id", existing_type=sa.Integer(), comment=STRATEGY_OLD)
    op.create_table_comment("saved_strategies", TABLE_OLD, existing_comment=TABLE_NEW)
    op.drop_index("uq_saved_strategy_etf_algorithm", table_name="saved_strategies")
    op.drop_column("saved_strategies", "algorithm_template_id")
