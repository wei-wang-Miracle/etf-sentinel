"""新增回测权益来源与不可变实验记录，保留既有数据。"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    """创建有中文注释的权益来源和回测记录表。"""
    op.create_table(
        "backtest_sources",
        sa.Column(
            "instrument_code",
            sa.String(length=6),
            sa.ForeignKey("instruments.instrument_code"),
            primary_key=True,
            nullable=False,
            comment="证券代码，关联instruments.instrument_code；当前510500或512100",
        ),
        sa.Column(
            "source_url",
            sa.String(),
            primary_key=False,
            nullable=False,
            comment="东方财富基金分红送配页面URL，不包含凭据",
        ),
        sa.Column(
            "checked_through_date",
            sa.Date(),
            primary_key=False,
            nullable=False,
            comment="本次读取权益页面的北京时间日期；表示读取时点，不保证来源绝对完整",
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            comment="本系统读取并校验权益页面时间，带时区",
        ),
        sa.Column(
            "source_sha256",
            sa.String(64),
            primary_key=False,
            nullable=False,
            comment="源页面字节的SHA256摘要，用于核对原始证据",
        ),
        sa.Column(
            "source_html",
            sa.String(),
            primary_key=False,
            nullable=False,
            comment="已获取权益源页面原始HTML，仅作证据，不在前端渲染",
        ),
        sa.Column(
            "corporate_actions",
            sa.JSON(),
            primary_key=False,
            nullable=False,
            comment="权益JSON：dividends数组含record_date登记日、ex_date除息日、pay_date到账日、cash_per_share每份人民币元字符串；splits数组含effective_date折算日及ratio源比例",
        ),
        comment="回测现金分红与折算来源；仅支持已核实的两只境内股票ETF，不作为行情价格",
    )
    op.create_table(
        "backtest_runs",
        sa.Column(
            "backtest_run_id",
            sa.Integer(),
            primary_key=True,
            nullable=False,
            comment="回测实验唯一自增编号，与采集运行编号无关",
        ),
        sa.Column(
            "instrument_code",
            sa.String(length=6),
            sa.ForeignKey("instruments.instrument_code"),
            primary_key=False,
            nullable=False,
            comment="回测证券代码，关联instruments.instrument_code",
        ),
        sa.Column(
            "strategy_key",
            sa.String(),
            primary_key=False,
            nullable=False,
            comment="策略注册标识，ma_trend为均线趋势；规则版本位于输入快照",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            comment="回测完成并写入本地时间，带时区",
        ),
        sa.Column(
            "input_sha256",
            sa.String(64),
            primary_key=False,
            nullable=False,
            comment="含参数、预热行情、权益、来源和版本的规范JSON SHA256摘要",
        ),
        sa.Column(
            "input_snapshot",
            sa.JSON(),
            primary_key=False,
            nullable=False,
            comment="不可变输入JSON：settings参数、rows原始行情与采集时间、actions权益、来源快照、交易日历及策略/引擎/数据版本；金额使用十进制字符串",
        ),
        sa.Column(
            "result_snapshot",
            sa.JSON(),
            primary_key=False,
            nullable=False,
            comment="结果JSON：strategy与benchmark含daily逐日现金/份额/分红应收/净值/回撤/决策、trades成交及费用原因、dividends权益账本、metrics绩效；金额十进制字符串，收益率小数",
        ),
        comment="已成功完成的策略回测实验；仅研究模拟，非交易记录；输入与结果不可变",
    )


def downgrade():
    """按依赖顺序撤销本次表；显式降级将删除本地回测实验。"""
    op.drop_table("backtest_runs")
    op.drop_table("backtest_sources")
