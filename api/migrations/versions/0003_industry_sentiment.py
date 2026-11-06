"""新增行业恐贪历史数据及独立采集任务；ETF既有数据保留。"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    """创建带详尽注释的恐贪表并预置独立任务。"""
    op.create_table_comment(
        "jobs",
        "采集任务配置；执行时区Asia/Shanghai",
        existing_comment="日行情采集任务配置；执行时区Asia/Shanghai",
    )
    op.alter_column(
        "jobs", "job_id", comment="采集任务唯一编号；1为ETF日行情，2为行业恐贪"
    )
    op.create_table(
        "sentiment_categories",
        sa.Column(
            "category_key",
            sa.String(length=64),
            primary_key=True,
            nullable=False,
            comment="源类别唯一标识，如gf军工、qs券商；主外键统一使用category_key",
        ),
        sa.Column(
            "category_name",
            sa.String(),
            primary_key=False,
            nullable=False,
            comment="数据源类别显示名称，不根据key自行推断",
        ),
        sa.Column(
            "index_name",
            sa.String(),
            primary_key=False,
            nullable=True,
            comment="历史序列返回的关联指数名称；尚未返回时为空",
        ),
        sa.Column(
            "collection_enabled",
            sa.Boolean(),
            primary_key=False,
            nullable=False,
            comment="是否采集该类别，停用不删除历史；新发现类别默认启用",
        ),
        sa.Column(
            "snapshot_date",
            sa.Date(),
            primary_key=False,
            nullable=True,
            comment="源目录最新快照日期；保持源日期，不推断时区；可空",
        ),
        sa.Column(
            "snapshot_score",
            sa.Numeric(precision=8, scale=4),
            primary_key=False,
            nullable=True,
            comment="源最新快照恐贪分数0至100；0有效；缺失为空",
        ),
        sa.Column(
            "snapshot_label",
            sa.String(),
            primary_key=False,
            nullable=True,
            comment="源最新快照情绪标签；仅日期与分数匹配本地日数据时展示；可空",
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            comment="本系统最近成功读取类别目录时间，带时区时间戳",
        ),
        comment="韭圈行业恐贪类别目录及源快照；包括行业、固收与美股，不与ETF自动关联",
    )
    op.create_table(
        "sentiment_daily",
        sa.Column(
            "category_key",
            sa.String(length=64),
            sa.ForeignKey("sentiment_categories.category_key"),
            primary_key=True,
            nullable=False,
            comment="源类别唯一标识，关联sentiment_categories.category_key",
        ),
        sa.Column(
            "trade_date",
            sa.Date(),
            primary_key=True,
            nullable=False,
            comment="数据源序列日期，非采集日期；不统一截为北京时间昨日",
        ),
        sa.Column(
            "fear_greed_score",
            sa.Numeric(precision=8, scale=4),
            primary_key=False,
            nullable=False,
            comment="恐贪分数，闭区间0至100，0为有效值；计算公式由源提供",
        ),
        sa.Column(
            "close_price",
            sa.Numeric(precision=24, scale=8),
            primary_key=False,
            nullable=True,
            comment="关联指数收盘点位，非ETF价格；源缺失时为空",
        ),
        sa.Column(
            "collected_at",
            sa.DateTime(timezone=True),
            primary_key=False,
            nullable=False,
            comment="本系统本条日数据最近采集时间，带时区时间戳",
        ),
        comment="行业恐贪历史日序列，含关联指数收盘；原始源日期保存，零分有效，不自行计算情绪阈值",
    )
    op.add_column(
        "runs",
        sa.Column(
            "job_id",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪",
        ),
    )
    op.alter_column("runs", "job_id", server_default=None)
    op.create_foreign_key("runs_job_id_fkey", "runs", "jobs", ["job_id"], ["job_id"])
    op.execute(
        "INSERT INTO jobs (job_id, schedule_enabled, scheduled_time) VALUES (2, true, '01:10')"
    )


def downgrade():
    """撤销行业恐贪任务与日数据，保留ETF任务与行情。"""
    op.create_table_comment(
        "jobs",
        "日行情采集任务配置；执行时区Asia/Shanghai",
        existing_comment="采集任务配置；执行时区Asia/Shanghai",
    )
    op.alter_column(
        "jobs", "job_id", comment="采集任务唯一编号；当前ETF日行情任务固定为1"
    )
    op.execute("DELETE FROM runs WHERE job_id = 2")
    op.execute("DELETE FROM jobs WHERE job_id = 2")
    op.drop_constraint("runs_job_id_fkey", "runs", type_="foreignkey")
    op.drop_column("runs", "job_id")
    op.drop_table("sentiment_daily")
    op.drop_table("sentiment_categories")
