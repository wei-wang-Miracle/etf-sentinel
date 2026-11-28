"""恢复研究因子“超跌后止跌修复”到可观察因子目录。"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import insert

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

RESTORED_FACTOR = {
    "factor_id": "oversold_recovery",
    "factor_name": "超跌后止跌修复",
    "category": "反转确认",
    "output_type": "event",
    "meaning": "近期超跌后收盘突破昨高，并满足量能、收盘位置和MA20下方条件。",
    "chart_visible": True,
}


def upgrade():
    """幂等恢复 oversold_recovery，并保留既有原子因子。"""
    factor_table = sa.table(
        "research_factors",
        sa.column("factor_id"),
        sa.column("factor_name"),
        sa.column("category"),
        sa.column("output_type"),
        sa.column("meaning"),
        sa.column("chart_visible"),
    )
    stmt = insert(factor_table).values(RESTORED_FACTOR).on_conflict_do_nothing(
        index_elements=["factor_id"]
    )
    op.execute(stmt)


def downgrade():
    """撤销恢复的 oversold_recovery 目录条目及关系。"""
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
    op.execute(
        sa.text("DELETE FROM research_factors WHERE factor_id = 'oversold_recovery'")
    )
