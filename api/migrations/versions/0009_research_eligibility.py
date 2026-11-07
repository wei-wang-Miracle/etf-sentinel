"""权益核验资格扩展到配置内ETF，保留原事件及回测快照。"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    """同步动态资格的数据库中文注释。"""
    op.create_table_comment(
        "backtest_sources",
        "配置内ETF回测现金分红与折算来源；按权益、日历和行情动态核验资格，不作为行情价格",
    )
    op.alter_column(
        "backtest_sources",
        "instrument_code",
        comment="证券代码，关联instruments.instrument_code；仅限配置内ETF",
    )


def downgrade():
    """恢复原注释，不删除来源证据。"""
    op.create_table_comment(
        "backtest_sources",
        "回测现金分红与折算来源；仅支持已核实的两只境内股票ETF，不作为行情价格",
    )
    op.alter_column(
        "backtest_sources",
        "instrument_code",
        comment="证券代码，关联instruments.instrument_code；当前510500或512100",
    )
