"""配置内 ETF FundDB 档案和日度份额流采集。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select

from app.collection import now
from app.db import Session
from app.etf_catalog import fetch_catalog, fetch_fund_detail, parse_fund_detail
from app.models import EtfCatalogProfile, EtfFlowDaily, Instrument, Run


def _sync_profile(db, row: dict[str, Any], detail: dict[str, Any], collected_at) -> tuple[int, int]:
    code = row["instrument_code"]
    values = {
        key: row.get(key)
        for key in (
            "fund_full_name",
            "category_primary",
            "category_tag",
            "tracking_index_code",
            "tracking_index_name",
            "setup_date",
            "management_fee_pct",
            "custody_fee_pct",
            "linked_otc_code",
            "source_url",
        )
    }
    values["index_corr"] = detail.get("index_corr")
    existing = db.get(EtfCatalogProfile, code)
    if existing is None:
        db.add(EtfCatalogProfile(instrument_code=code, **values, collected_at=collected_at))
        return 1, 0
    if any(getattr(existing, key) != value for key, value in values.items()):
        for key, value in values.items():
            setattr(existing, key, value)
        existing.collected_at = collected_at
        return 0, 1
    return 0, 0


def _sync_flow(db, code: str, flow: dict[str, Any] | None, collected_at) -> tuple[int, int]:
    if flow is None:
        return 0, 0
    values = {
        key: flow.get(key)
        for key in (
            "unit_shares_100m",
            "aum_100m",
            "net_share_flow_7d_100m",
            "net_share_flow_30d_100m",
            "discount_premium_pct",
            "purchase_status",
            "redeem_status",
        )
    }
    identity = (code, flow["trade_date"])
    existing = db.get(EtfFlowDaily, identity)
    if existing is None:
        db.add(EtfFlowDaily(instrument_code=code, trade_date=flow["trade_date"], **values, collected_at=collected_at))
        return 1, 0
    if any(getattr(existing, key) != value for key, value in values.items()):
        for key, value in values.items():
            setattr(existing, key, value)
        existing.collected_at = collected_at
        return 0, 1
    return 0, 0


def collect_etf_flows(
    run_id: int,
    *,
    fetch_catalog: Callable[[], list[dict[str, Any]]] = fetch_catalog,
    fetch_detail: Callable[[str], object] = fetch_fund_detail,
) -> None:
    """仅更新已启用标的；源目录局部缺失绝不删除本地历史。"""
    with Session() as db:
        run = db.get(Run, run_id)
        if run is None:
            raise ValueError("运行记录不存在")
        enabled = set(db.scalars(select(Instrument.code).where(Instrument.enabled.is_(True))))
        if not enabled:
            run.status, run.ended_at = "skipped", now()
            run.logs = [{"status": "skipped", "message": "没有启用中的ETF标的"}]
            db.commit()
            return
        try:
            catalog = {item["instrument_code"]: item for item in fetch_catalog()}
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            run.status, run.ended_at = "failed", now()
            run.logs = [{"status": "failed", "message": "ETF档案目录获取或校验失败，保留已有数据"}]
            db.commit()
            return

        successes = failures = profile_inserted = profile_revised = flow_inserted = flow_revised = 0
        logs: list[dict[str, Any]] = []
        captured_at = now()
        for code in sorted(enabled):
            item = catalog.get(code)
            entry: dict[str, Any] = {"code": code}
            if item is None:
                failures += 1
                entry.update(status="skipped", message="FundDB目录暂未收录该ETF，保留已有数据")
                logs.append(entry)
                continue
            try:
                raw_detail = fetch_detail(code)
                detail = (
                    raw_detail
                    if isinstance(raw_detail, dict) and "index_corr" in raw_detail
                    else parse_fund_detail(raw_detail, item.get("tracking_index_code"))
                )
                profile_added, profile_changed = _sync_profile(
                    db, item, detail, captured_at
                )
                flow_added, flow_changed = _sync_flow(
                    db, code, item.get("flow"), captured_at
                )
                profile_inserted += profile_added
                profile_revised += profile_changed
                flow_inserted += flow_added
                flow_revised += flow_changed
                db.commit()
                successes += 1
                entry.update(
                    status="success",
                    count=profile_added + profile_changed + flow_added + flow_changed,
                    message="已更新ETF档案与份额流" if item.get("flow") else "已更新ETF档案，源暂未提供份额截面",
                )
            except (httpx.HTTPError, ValueError, TypeError, KeyError, ArithmeticError):
                db.rollback()
                failures += 1
                entry.update(status="failed", count=0, message="ETF详情获取或校验失败，保留已有数据")
            logs.append(entry)

        run = db.get(Run, run_id)
        run.logs = [
            {
                "status": "success" if successes else "failed",
                "count": profile_inserted + profile_revised + flow_inserted + flow_revised,
                "profiles_inserted": profile_inserted,
                "profiles_revised": profile_revised,
                "flows_inserted": flow_inserted,
                "flows_revised": flow_revised,
                "message": f"成功{successes}只，未完成{failures}只；仅处理已启用ETF",
            },
            *logs,
        ]
        run.status = "success" if failures == 0 else ("partial" if successes else "failed")
        run.ended_at = now()
        db.commit()
