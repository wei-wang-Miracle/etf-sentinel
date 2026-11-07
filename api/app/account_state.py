"""统一读取完整持仓集合，防止同日后续同步消失的标的沿用旧仓位。"""

from datetime import date

from sqlalchemy import DateTime, and_, cast, func, literal, or_, select, true

from app.models import AccountHoldingSnapshot, AccountSyncRun


def latest_holdings(db, account_id=1):
    """在单条查询的同一数据库快照中读取集合与数量，避免并发同步拼接版本。

    完整源为空数组时返回空集合，不回退到历史正持仓。空仓没有源日期则保持空，
    不把采集日期冒充源日期。旧记录没有集合证据时兼容读取最大源日期。
    """
    latest_run = (
        select(AccountSyncRun.holdings_snapshot)
        .where(
            AccountSyncRun.account_id == account_id,
            AccountSyncRun.holdings_snapshot.is_not(None),
        )
        .order_by(AccountSyncRun.sync_run_id.desc())
        .limit(1)
        .subquery()
    )
    snapshot = latest_run.c.holdings_snapshot
    legacy_date = (
        select(func.max(AccountHoldingSnapshot.data_date))
        .where(AccountHoldingSnapshot.account_id == account_id)
        .correlate(None)
        .scalar_subquery()
    )
    # 常量行保证完整空集合及尚未同步时也返回集合头；LEFT JOIN不把空集合吞掉。
    anchor = select(literal(1).label("anchor")).subquery()
    statement = (
        select(snapshot, AccountHoldingSnapshot)
        .select_from(anchor)
        .outerjoin(latest_run, true())
        .outerjoin(
            AccountHoldingSnapshot,
            and_(
                AccountHoldingSnapshot.account_id == account_id,
                or_(
                    and_(
                        snapshot.is_not(None),
                        AccountHoldingSnapshot.collected_at
                        == cast(
                            snapshot["collected_at"].as_string(),
                            DateTime(timezone=True),
                        ),
                    ),
                    and_(
                        snapshot.is_(None),
                        AccountHoldingSnapshot.data_date == legacy_date,
                    ),
                ),
            ),
        )
        .order_by(AccountHoldingSnapshot.instrument_code)
    )
    result = db.execute(statement).all()
    metadata = result[0][0]
    rows = [row for _, row in result if row is not None]
    if metadata is not None:
        source_date = (
            date.fromisoformat(metadata["source_date"])
            if metadata["source_date"]
            else None
        )
        return source_date, [
            row
            for row in rows
            if row.instrument_code in metadata["instrument_codes"]
            and row.data_date == source_date
        ]
    return (rows[0].data_date if rows else None), rows
