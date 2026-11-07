"""账户数据源 HTTP 客户端与同步编排。"""

import json
import os
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.account import (
    DEFAULT_SYNC_START,
    fetch_entrust_window,
    merge_entrust_rows,
    normalize_entrust,
    normalize_holding,
    split_windows,
    sync_start,
)
from app.chatbi_config import ACCOUNT_ACCESS_CODE, SOURCE_URL
from app.collection import now
from app.db import Session
from app.models import (
    Account,
    AccountEntrust,
    AccountHoldingSnapshot,
    AccountSyncRun,
    Instrument,
)

ACCOUNT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "account.json"
_SYNC_LOCK = threading.Lock()


class AccountSyncBusy(RuntimeError):
    """已有账户同步在运行。"""


@dataclass(frozen=True)
class AccountConfig:
    """本地账户数据源配置；资金号只从本地配置文件读取。"""

    url: str
    access_code: str
    token: str
    fund_account: str
    start_date: date
    account_id: int = 1


def load_config() -> AccountConfig:
    """读取共享 token 和本地资金号，固定接口参数不从环境变量覆盖。

    Returns:
        默认本地账户的只读同步配置。

    Raises:
        ValueError: token 缺失或本地账户配置缺失、格式错误。
    """
    token = os.getenv("CHATBI_TOKEN")
    if not token:
        raise ValueError("请配置后端 CHATBI_TOKEN")
    try:
        data = json.loads(ACCOUNT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("账户配置无法读取，请检查 api/config/account.json") from None
    fund_account = data.get("fund_account") if isinstance(data, dict) else None
    if not isinstance(fund_account, str) or not fund_account.strip():
        raise ValueError("账户配置 fund_account 须为非空字符串")
    return AccountConfig(
        url=SOURCE_URL,
        access_code=ACCOUNT_ACCESS_CODE,
        token=token,
        fund_account=fund_account.strip(),
        start_date=DEFAULT_SYNC_START,
    )


def build_client() -> httpx.Client:
    """账户接口要求 IPv4/HTTP1.1/TLS1.2，显式限制避免握手失败。"""
    context = ssl.create_default_context()
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    return httpx.Client(
        verify=context,
        http2=False,
        trust_env=False,
        timeout=30,
        follow_redirects=False,
    )


def fetch_rows(
    api_path: str,
    payload: dict,
    *,
    client: httpx.Client | None = None,
    config: AccountConfig | None = None,
) -> list[dict]:
    """只读调用账户接口，有限重试且不向调用方暴露鉴权信息。"""
    cfg = config or load_config()
    own_client = client is None
    client = client or build_client()
    try:
        for attempt in range(3):
            try:
                response = client.post(
                    cfg.url,
                    params={"api_path": api_path, "access_code": cfg.access_code},
                    headers={"Authorization": f"Bearer {cfg.token}"},
                    json=payload,
                )
                if response.status_code in (401, 403):
                    raise ValueError("账户数据源鉴权失败，请检查后端凭据")
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 2:
                        raise ValueError("账户数据源暂时不可用，请稍后重试")
                    time.sleep(attempt + 1)
                    continue
                if response.status_code != 200:
                    raise ValueError(f"账户数据源 HTTP {response.status_code}")
                body = response.json()
                if (
                    not isinstance(body, dict)
                    or body.get("success") is not True
                    or not isinstance(body.get("data"), list)
                ):
                    raise ValueError("账户数据源返回格式错误")
                return body["data"]
            except httpx.TransportError:
                if attempt == 2:
                    raise ValueError("账户数据源网络请求失败，已重试三次") from None
                time.sleep(attempt + 1)
    finally:
        if own_client:
            client.close()
    raise ValueError("账户数据源请求失败")


def fetch_holdings(
    config: AccountConfig, *, client: httpx.Client | None = None
) -> list[dict]:
    """读取当前持仓快照，调用方负责按配置范围过滤。"""
    return fetch_rows(
        "mine/stockreal",
        {"fundAccount": config.fund_account},
        client=client,
        config=config,
    )


def fetch_entrust(
    config: AccountConfig,
    start: date,
    end: date,
    *,
    client: httpx.Client | None = None,
) -> list[dict]:
    """读取闭区间委托记录；单次可能被源截断，由窗口拆分处理。"""
    return fetch_rows(
        "mine/entrust",
        {
            "fundAccount": config.fund_account,
            "startDate": start.strftime("%Y%m%d"),
            "endDate": end.strftime("%Y%m%d"),
        },
        client=client,
        config=config,
    )


def _mark_failed(run_id: int, message: str) -> None:
    """用独立事务记录失败，避免原会话回滚后丢失批次状态。"""
    with Session() as db:
        run = db.get(AccountSyncRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.ended_at = now()
        run.error_message = message[:2000]
        db.commit()


def sync_account(
    *,
    config: AccountConfig | None = None,
    fetch_holdings_fn: Callable[[AccountConfig], list[dict]] | None = None,
    fetch_entrust_fn: Callable[[AccountConfig, date, date], list[dict]] | None = None,
    today: date | None = None,
) -> dict:
    """同步配置内持仓和委托；返回批次摘要，重复运行按主键幂等更新。"""
    if not _SYNC_LOCK.acquire(blocking=False):
        raise AccountSyncBusy("账户同步正在运行")
    client = None
    run_id = None
    try:
        cfg = config or load_config()
        today = today or now().date()
        client = (
            build_client()
            if fetch_holdings_fn is None or fetch_entrust_fn is None
            else None
        )
        holdings_fn = fetch_holdings_fn or (
            lambda item_config: fetch_holdings(item_config, client=client)
        )
        entrust_fn = fetch_entrust_fn or (
            lambda item_config, start, end: fetch_entrust(
                item_config, start, end, client=client
            )
        )
        with Session() as db:
            account = db.get(Account, cfg.account_id)
            if account is None:
                account = Account(
                    account_id=cfg.account_id,
                    account_name="默认账户",
                    base_currency="CNY",
                    created_at=now(),
                )
                db.add(account)
                db.flush()
            configured = set(db.scalars(select(Instrument.code)).all())
            if not configured:
                raise ValueError("尚未配置研究标的，不能同步账户数据")
            last_date = db.scalar(
                select(func.max(AccountEntrust.curr_date)).where(
                    AccountEntrust.account_id == cfg.account_id
                )
            )
            start = sync_start(last_date, today, cfg.start_date)
            end = today
            run = AccountSyncRun(
                account_id=cfg.account_id,
                status="running",
                range_start=start,
                range_end=end,
                started_at=now(),
            )
            db.add(run)
            db.commit()
            run_id = run.sync_run_id
            try:
                raw_holdings = holdings_fn(cfg)
                raw_entrust = []
                for window_start, window_end in split_windows(start, end):
                    raw_entrust.extend(
                        fetch_entrust_window(
                            lambda left, right: entrust_fn(cfg, left, right),
                            window_start,
                            window_end,
                        )
                    )
                raw_entrust = merge_entrust_rows(raw_entrust)

                holdings = []
                entrusts = []
                errors = []
                skipped = 0
                for row in raw_holdings:
                    try:
                        item = normalize_holding(row, configured)
                    except ValueError as exc:
                        errors.append(str(exc))
                        continue
                    if item is None:
                        skipped += 1
                    else:
                        holdings.append(item)
                holdings_valid = not errors
                if len({item["data_date"] for item in holdings}) > 1:
                    holdings_valid = False
                    errors.append("持仓源日期不一致，不能形成完整当前快照")
                for row in raw_entrust:
                    try:
                        item = normalize_entrust(row, configured)
                    except ValueError as exc:
                        errors.append(str(exc))
                        continue
                    if item is None:
                        skipped += 1
                    else:
                        entrusts.append(item)
                entrusts = merge_entrust_rows(entrusts)
                stamp = now()
                holding_values = [
                    {**item, "account_id": cfg.account_id, "collected_at": stamp}
                    for item in holdings if holdings_valid
                ]
                entrust_values = [
                    {**item, "account_id": cfg.account_id, "collected_at": stamp}
                    for item in entrusts
                ]
                if holdings_valid:
                    run.holdings_snapshot = {"instrument_codes": sorted({item["instrument_code"] for item in holdings}), "source_date": str(holdings[0]["data_date"]) if holdings else None, "collected_at": stamp.isoformat()}
                if holding_values:
                    statement = insert(AccountHoldingSnapshot).values(holding_values)
                    statement = statement.on_conflict_do_update(
                        index_elements=[
                            "account_id",
                            "data_date",
                            "instrument_code",
                        ],
                        set_={
                            field: getattr(statement.excluded, field)
                            for field in (
                                "current_amount",
                                "enable_amount",
                                "frozen_amount",
                                "uncome_buy_amount",
                                "uncome_sell_amount",
                                "cost_price",
                                "sum_buy_amount",
                                "sum_buy_balance",
                                "sum_sell_amount",
                                "sum_sell_balance",
                                "source_etl_time",
                                "collected_at",
                            )
                        },
                    )
                    db.execute(statement)
                if entrust_values:
                    statement = insert(AccountEntrust).values(entrust_values)
                    statement = statement.on_conflict_do_update(
                        index_elements=["account_id", "curr_date", "entrust_no"],
                        set_={
                            field: getattr(statement.excluded, field)
                            for field in (
                                "curr_time",
                                "init_date",
                                "order_id",
                                "instrument_code",
                                "entrust_side",
                                "entrust_amount",
                                "entrust_price",
                                "entrust_type",
                                "business_amount",
                                "business_price",
                                "business_balance",
                                "clear_balance",
                                "withdraw_amount",
                                "entrust_status",
                                "fare_kind",
                                "fee_amount",
                                "data_date",
                                "source_etl_time",
                                "collected_at",
                            )
                        },
                    )
                    db.execute(statement)
                run.status = "partial" if errors else "success"
                run.ended_at = now()
                run.fetched_count = len(raw_holdings) + len(raw_entrust)
                run.stored_count = len(holding_values) + len(entrust_values)
                run.skipped_count = skipped
                run.error_count = len(errors)
                run.error_message = "; ".join(errors[:5])[:2000] or None
                db.commit()
            except Exception as exc:
                db.rollback()
                if run_id is not None:
                    _mark_failed(run_id, str(exc))
                raise
        return {
            "sync_run_id": run_id,
            "status": run.status,
            "range_start": run.range_start.isoformat()
            if run.range_start
            else None,
            "range_end": run.range_end.isoformat() if run.range_end else None,
            "fetched_count": run.fetched_count,
            "stored_count": run.stored_count,
            "skipped_count": run.skipped_count,
            "error_count": run.error_count,
            "error_message": run.error_message,
        }
    finally:
        if client is not None:
            client.close()
        _SYNC_LOCK.release()
