"""下线旧持仓候选研究：清理旧观察链数据，保留共用表与新流程数据。"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    """仅删除 strategy_version_id 为 NULL 的旧观察及其信号/执行关联/无主批次。

    共用表结构保留；新流程观察（strategy_version_id 非空）及其批次、信号不受影响。
    回测 runs 被 saved_strategy_versions 与比较快照引用，不在本次清理范围。
    """
    old_obs = "SELECT observation_id FROM strategy_observations WHERE strategy_version_id IS NULL"
    op.execute(
        sa.text(
            "DELETE FROM strategy_execution_links WHERE signal_id IN "
            f"(SELECT signal_id FROM strategy_signals WHERE observation_id IN ({old_obs}))"
        )
    )
    op.execute(
        sa.text(
            f"DELETE FROM strategy_signals WHERE observation_id IN ({old_obs})"
        )
    )
    op.execute(sa.text("DELETE FROM strategy_observations WHERE strategy_version_id IS NULL"))
    op.execute(
        sa.text(
            "DELETE FROM strategy_research_batches WHERE research_batch_id NOT IN "
            "(SELECT research_batch_id FROM strategy_observations)"
        )
    )


def downgrade():
    """数据删除不可逆，结构未变更，无需回滚。"""
