"""新增十八只国家队ETF估算比例与独立任务，不改变已有行情表。"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    """创建目录和日比例表，注释与应用模型一致，预置任务3。"""
    op.create_table(
        "national_team_instruments",
        sa.Column(
            "instrument_code",
            sa.String(6),
            primary_key=True,
            nullable=False,
            comment="源ETF证券代码，六位字符串，保留前导零",
        ),
        sa.Column(
            "instrument_name",
            sa.String(),
            nullable=False,
            comment="源ETF名称，不使用行情近似价格",
        ),
        sa.Column(
            "index_name",
            sa.String(),
            nullable=False,
            comment="源ETF跟踪指数名称，非指数代码",
        ),
        sa.Column(
            "estimation_start_date",
            sa.Date(),
            nullable=False,
            comment="固定请求与估算起点2026-01-01；筛选日期和跨年不重置，不同起点比例不可拼接",
        ),
        sa.Column(
            "reference_holding_pct",
            sa.Numeric(12, 8),
            nullable=True,
            comment="源hold_pct年报基准持仓比例，百分数0至100；上游披露未核实；可空",
        ),
        sa.Column(
            "source_url",
            sa.String(),
            nullable=False,
            comment="固定第三方源接口地址，不包含凭据",
        ),
        sa.Column(
            "source_available",
            sa.Boolean(),
            nullable=False,
            comment="最近成功读取的源目录是否包含该ETF；缺失不删除历史",
        ),
        sa.Column(
            "last_success_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="该ETF最近完整核验并成功增量入库时间，带时区；不代表源行情日期",
        ),
        comment="国家队ETF源目录及固定估算基准；比例为第三方推算，不代表实际持仓",
    )
    op.create_table(
        "national_team_daily",
        sa.Column(
            "instrument_code",
            sa.String(6),
            sa.ForeignKey("national_team_instruments.instrument_code"),
            primary_key=True,
            nullable=False,
            comment="源ETF证券代码，关联national_team_instruments.instrument_code",
        ),
        sa.Column(
            "trade_date",
            sa.Date(),
            primary_key=True,
            nullable=False,
            comment="源points.date交易日期，保留源日历日期，不使用请求截止日",
        ),
        sa.Column(
            "estimated_holding_pct",
            sa.Numeric(12, 8),
            nullable=True,
            comment="源nat_pct估算持仓比例，百分数0至100；有效份额下零有效；份额为零或源比例缺失时为空",
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="本条首次入库或源比例实际修订的采集时间，带时区；未变化不重写",
        ),
        comment="国家队ETF源日估算比例；同代码同源日期唯一；不作为真实持仓或交易信号",
    )
    op.alter_column(
        "jobs",
        "job_id",
        comment="采集任务唯一编号；1为ETF日行情，2为行业恐贪，3为国家队持仓比例",
    )
    op.alter_column(
        "runs",
        "job_id",
        comment="所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例",
    )
    op.execute(
        "INSERT INTO jobs (job_id, schedule_enabled, scheduled_time) VALUES (3, true, '01:20')"
    )


def downgrade():
    """仅撤销国家队任务和比例表，保留其他业务。"""
    op.execute("DELETE FROM runs WHERE job_id = 3")
    op.execute("DELETE FROM jobs WHERE job_id = 3")
    op.drop_table("national_team_daily")
    op.drop_table("national_team_instruments")
    op.alter_column(
        "jobs", "job_id", comment="采集任务唯一编号；1为ETF日行情，2为行业恐贪"
    )
    op.alter_column(
        "runs",
        "job_id",
        comment="所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪",
    )
