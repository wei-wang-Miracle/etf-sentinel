"""记录完整账户持仓集合，修复同日消失持仓被沿用的问题。"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    """保留历史持仓行，增加完整同步集合证据及任务5注释。"""
    op.add_column(
        "account_sync_runs",
        sa.Column(
            "holdings_snapshot",
            sa.JSON(none_as_null=True),
            nullable=True,
            comment="完整持仓集合JSON：instrument_codes代码数组、source_date源日期或空、collected_at带时区采集时间；空数组表示真实空集合；NULL为旧版本或本次未取得完整快照，不将其当作空仓",
        ),
    )
    op.execute(
        "COMMENT ON COLUMN runs.job_id IS '所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情，5为策略日计划'"
    )


def downgrade():
    """仅移除集合证据字段，不删除真实持仓和成交记录。"""
    op.drop_column("account_sync_runs", "holdings_snapshot")
    op.execute(
        "COMMENT ON COLUMN runs.job_id IS '所属采集任务编号，关联jobs.job_id；1为ETF，2为行业恐贪，3为国家队持仓比例，4为指数估值与指数日行情'"
    )
