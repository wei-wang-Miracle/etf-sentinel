"""分级免费历史行情采集、跨源对比与复权反推的单元测试。"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.free_market_sources import (
    MIN_CALENDAR_DATE,
    audited_suspensions,
    backfill_instrument_history,
    collect_and_verify_history,
    compute_historical_adjusted_close,
    fetch_eastmoney_history,
    fetch_sina_history,
    fetch_tencent_history,
    free_backfill_end_date,
    persist_verified_suspensions,
)


def _sample_series(dates, base_close=Decimal("1.000"), *, include_amount=True):
    return [
        {
            "trade_date": day,
            "open": base_close + Decimal(idx) * Decimal("0.010"),
            "high": base_close + Decimal(idx) * Decimal("0.010") + Decimal("0.020"),
            "low": base_close + Decimal(idx) * Decimal("0.010") - Decimal("0.010"),
            "close": base_close + Decimal(idx) * Decimal("0.010") + Decimal("0.005"),
            "volume": Decimal(1000000),
            "amount": Decimal(1005000) if include_amount else None,
            "change_pct": Decimal("0.5"),
        }
        for idx, day in enumerate(dates)
    ]


def test_eastmoney_sina_tencent_parsers_normalize_units():
    """验证三个源各自的价格、手/份换算与截止日过滤。"""
    def em_handler(request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "klines": [
                        "2024-08-12,3.400,3.410,3.420,3.390,1000,341000.0,0.88,0.29,0.010,1.2",
                        "2024-08-13,3.410,3.420,3.430,3.400,2000,684000.0,0.88,0.29,0.010,1.2",
                    ]
                }
            },
        )

    def sina_handler(request):
        return httpx.Response(
            200,
            json=[
                {"day": "2024-08-12", "open": "3.400", "high": "3.420", "low": "3.390", "close": "3.410", "volume": "100000"},
                {"day": "2024-08-13", "open": "3.410", "high": "3.430", "low": "3.400", "close": "3.420", "volume": "200000"},
            ],
        )

    def tx_handler(request):
        return httpx.Response(
            200,
            json={
                "data": {
                    "sh510300": {
                        "day": [
                            ["2024-08-12", "3.400", "3.410", "3.420", "3.390", "1000.000"],
                        ]
                    }
                }
            },
        )

    em_rows = fetch_eastmoney_history(
        "510300",
        end_date=date(2024, 8, 12),
        client=httpx.Client(transport=httpx.MockTransport(em_handler)),
    )
    sn_rows = fetch_sina_history(
        "510300",
        end_date=date(2024, 8, 12),
        client=httpx.Client(transport=httpx.MockTransport(sina_handler)),
    )
    tx_rows = fetch_tencent_history(
        "510300",
        end_date=date(2024, 8, 12),
        start_year=2024,
        client=httpx.Client(transport=httpx.MockTransport(tx_handler)),
    )

    assert len(em_rows) == 1 and em_rows[0]["volume"] == Decimal(100000)
    assert em_rows[0]["amount"] == Decimal("341000.0")
    assert sn_rows[0]["volume"] == Decimal(100000) and sn_rows[0]["amount"] is None
    assert tx_rows[0]["volume"] == Decimal(100000) and tx_rows[0]["amount"] is None


def test_tiered_fallback_and_peer_cross_check_succeed_when_primary_down():
    """优先源东财不可用时，自动降级至备用源新浪并用兜底源腾讯交叉验证通过。"""
    dates = ["2020-01-02", "2020-01-03", "2024-08-12"]
    sn_rows = _sample_series(dates, include_amount=False)
    tx_rows = _sample_series(dates, include_amount=False)
    local_anchor = [{**sn_rows[-1], "amount": None}]

    def fail_em(code, *, end_date=None):
        raise ValueError("东财临时限流")

    result = collect_and_verify_history(
        "510300",
        existing_rows=local_anchor,
        fetchers={
            "eastmoney": fail_em,
            "sina": lambda code, *, end_date=None: sn_rows,
            "tencent": lambda code, *, end_date=None: tx_rows,
        },
    )

    assert result["selected_source"] == "sina"
    assert result["source_status"]["eastmoney"]["available"] is False
    assert result["overlap_check"]["passed"] is True
    assert result["cross_check"]["passed"] is True


def test_audited_suspensions_require_every_available_source_to_miss_the_same_day():
    shared_missing = audited_suspensions(
        {
            "eastmoney": _sample_series(["2026-01-05", "2026-01-07"]),
            "sina": _sample_series(["2026-01-05", "2026-01-07"], include_amount=False),
            "tencent": _sample_series(["2026-01-05", "2026-01-07"], include_amount=False),
        }
    )
    assert shared_missing["available_source_count"] == 3
    assert shared_missing["verified_suspensions"] == [
        {
            "trade_date": "2026-01-06",
            "sources": ["eastmoney", "sina", "tencent"],
        }
    ]

    peer_has_trade = audited_suspensions(
        {
            "eastmoney": _sample_series(["2026-01-05", "2026-01-07"]),
            "sina": _sample_series(
                ["2026-01-05", "2026-01-06", "2026-01-07"], include_amount=False
            ),
            "tencent": _sample_series(["2026-01-05", "2026-01-07"], include_amount=False),
        }
    )
    assert peer_has_trade["verified_suspensions"] == []


def test_three_source_consensus_resolves_single_peer_historical_quirk():
    """某单源早期存在单点畸变时，另外两源一致即可消解分歧而不误杀主源。"""
    dates = ["2008-01-02", "2024-08-12"]
    em_rows = _sample_series(dates, base_close=Decimal("10.000"))
    sn_rows = _sample_series(dates, base_close=Decimal("10.000"), include_amount=False)
    tx_rows = _sample_series(dates, base_close=Decimal("10.000"), include_amount=False)
    # 模拟腾讯早期错误前复权价格
    tx_rows[0]["close"] = Decimal("3.500")
    tx_rows[0]["low"] = Decimal("3.400")

    result = collect_and_verify_history(
        "510180",
        existing_rows=[em_rows[-1]],
        fetchers={
            "eastmoney": lambda code, *, end_date=None: em_rows,
            "sina": lambda code, *, end_date=None: sn_rows,
            "tencent": lambda code, *, end_date=None: tx_rows,
        },
    )

    assert result["selected_source"] == "eastmoney"
    assert result["cross_check"]["passed"] is True
    assert result["cross_check"]["peers"]["tencent"]["resolved_by_consensus_count"] == 1


def test_unresolvable_conflict_between_two_available_sources_is_rejected():
    """仅两源可用且出现大幅价格分歧时，必须拒绝入库。"""
    dates = ["2020-01-02", "2024-08-12"]
    em_rows = _sample_series(dates, base_close=Decimal("3.000"))
    tx_rows = _sample_series(dates, base_close=Decimal("3.000"), include_amount=False)
    tx_rows[0]["close"] = Decimal("1.500")
    tx_rows[0]["low"] = Decimal("1.400")

    with pytest.raises(ValueError, match="一致性对比验证"):
        collect_and_verify_history(
            "510300",
            existing_rows=[em_rows[-1]],
            fetchers={
                "eastmoney": lambda code, *, end_date=None: em_rows,
                "sina": lambda code, *, end_date=None: (_ for _ in ()).throw(ValueError("不可用")),
                "tencent": lambda code, *, end_date=None: tx_rows,
            },
        )


def test_compute_historical_adjusted_close_bridges_anchor_smoothly():
    """反推历史复权收盘价需在分红除息与份额折算处保持严格比率连续。"""
    rows = [
        {"trade_date": "2024-01-17", "close": "4.000"},
        {"trade_date": "2024-01-18", "close": "3.900"},
        {"trade_date": "2024-08-12", "close": "3.500"},
    ]
    actions = {
        "dividends": [{"ex_date": "2024-01-18", "cash_per_share": "0.100"}],
        "splits": [],
    }
    anchor_factor = Decimal("1.20000000")
    adjusted = compute_historical_adjusted_close(
        rows, actions, anchor_date="2024-08-12", anchor_factor=anchor_factor
    )

    assert adjusted[-1] == Decimal("4.20000000")
    # 2024-01-18 除息后倍率 = 1.2，前一日除息前倍率应为 1.2 / (4.0 / 3.9) = 1.17
    assert adjusted[0] == Decimal("4.68000000")


def test_compute_historical_adjusted_close_matches_observed_post_split_dividend_basis():
    """同日拆分与分红时，若本地已核验跃迁与拆后派息一致，反推应采用同一口径。"""
    rows = [
        {"trade_date": "2024-11-29", "close": "6.159"},
        {"trade_date": "2024-12-02", "close": "2.374"},
    ]
    actions = {
        "dividends": [{"ex_date": "2024-12-02", "cash_per_share": "0.1292"}],
        "splits": [{"effective_date": "2024-11-29", "ratio": "1:2.5000"}],
    }
    observed_ratio = (Decimal("6.9987") / Decimal("2.374")) / (
        Decimal("6.8820") / Decimal("6.159")
    )
    adjusted = compute_historical_adjusted_close(
        rows,
        actions,
        anchor_date="2024-11-29",
        anchor_factor=Decimal("6.8820") / Decimal("6.159"),
        observed_transitions={("2024-11-29", "2024-12-02"): observed_ratio},
    )
    assert adjusted[1].quantize(Decimal("0.0001")) == Decimal("6.9987")

    # 传入末端已入库锚点时，新增尾部日期直接衔接最近真实复权因子，不因早年累计四舍五入产生接缝跳变
    rows_with_tail = [*rows, {"trade_date": "2024-12-03", "close": "2.371"}]
    adjusted_with_tail = compute_historical_adjusted_close(
        rows_with_tail,
        actions,
        anchor_date="2024-11-29",
        anchor_factor=Decimal("6.8820") / Decimal("6.159"),
        known_factors={
            "2024-11-29": Decimal("6.8820") / Decimal("6.159"),
            "2024-12-02": Decimal("6.9987") / Decimal("2.374"),
        },
    )
    assert adjusted_with_tail[2] == (
        Decimal("2.371") * (Decimal("6.9987") / Decimal("2.374"))
    ).quantize(Decimal("0.00000001"))


def test_free_backfill_end_date_respects_market_close():
    """盘中时段不得把未收盘当日K线纳入日线回补，15:30后可截至当日。"""
    tz = ZoneInfo("Asia/Shanghai")
    assert free_backfill_end_date(datetime(2026, 11, 27, 14, 59, tzinfo=tz)) == date(
        2026, 11, 26
    )
    assert free_backfill_end_date(datetime(2026, 11, 27, 15, 30, tzinfo=tz)) == date(
        2026, 11, 27
    )


def test_collect_runs_free_backfill_only_for_requested_new_codes(monkeypatch):
    """常规采集不触发免费回补，仅当传入新增标的代码时追加上市至今日回补。"""
    import app.collection as collection_mod

    fake_run = SimpleNamespace(logs=[], status="running", ended_at=None)
    fake_instruments = [
        SimpleNamespace(code="510300", enabled=True, start_date=date(2026, 11, 26), name="沪深300"),
        SimpleNamespace(code="510500", enabled=True, start_date=date(2026, 11, 26), name="中证500"),
    ]

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, model, key):
            return fake_run if model is collection_mod.Run else None

        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: fake_instruments)

        def add(self, obj):
            return None

        def execute(self, stmt):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(collection_mod, "Session", FakeSession)
    monkeypatch.setattr(
        collection_mod,
        "now",
        lambda: datetime(2026, 11, 27, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    backfill_calls = []

    def fake_backfill(db, code, *, end_date, collected_at, require_equity=False):
        backfill_calls.append((code, end_date, require_equity))
        return {
            "selected_source": "eastmoney",
            "listing_start": "2012-05-28",
            "end": str(end_date),
            "backfill_candidates": 100,
        }

    collection_mod.collect(
        1,
        fetch=lambda c, s, e: [],
        fetch_equity=lambda c: {
            "actions": {"dividends": [], "splits": []},
            "source_url": "https://example.com",
            "source_html": "html",
            "source_sha256": "0" * 64,
            "collected_at": datetime(2026, 11, 27, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        },
        backfill_codes=("510300",),
        backfill_fn=fake_backfill,
    )

    assert backfill_calls == [("510300", date(2026, 11, 27), True)]
    assert fake_run.status == "success"
    assert any(
        entry.get("kind") == "free_backfill"
        and entry["code"] == "510300"
        and entry["count"] == 100
        for entry in fake_run.logs
    )


def test_backfill_clamps_pre_calendar_history_to_2006_11_27():
    """早于 2006-11-27 的历史行应被截断为 MAX(2006-11-27, 上市日期)，避免严格日历越界。"""
    dates = ["2005-02-23", "2006-11-24", "2006-11-27", "2024-08-12"]
    em_rows = _sample_series(dates)
    sn_rows = _sample_series(dates, include_amount=False)[1:]

    fake_db = SimpleNamespace(
        scalars=lambda stmt: [],
        get=lambda model, key: SimpleNamespace(
            corporate_actions={"dividends": [], "splits": []}
        ),
    )

    result = backfill_instrument_history(
        fake_db,
        "510050",
        end_date=date(2024, 8, 12),
        collected_at=datetime(2026, 11, 27, 16, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        fetchers={
            "eastmoney": lambda code, *, end_date=None: em_rows,
            "sina": lambda code, *, end_date=None: sn_rows,
            "tencent": lambda code, *, end_date=None: (_ for _ in ()).throw(ValueError("不可用")),
        },
        apply=False,
    )

    assert MIN_CALENDAR_DATE == date(2006, 11, 27)
    assert result["listing_start"] == "2006-11-27"
    assert result["backfill_candidates"] == 2


def test_collect_silently_switches_to_free_source_when_chatbi_fails(monkeypatch):
    """ChatBI 采集失败时自动静默切换免费行情源并推进窗口；两者都失败才报错。"""
    import app.collection as collection_mod

    fake_run = SimpleNamespace(logs=[], status="running", ended_at=None)
    fake_instruments = [
        SimpleNamespace(code="510300", enabled=True, start_date=date(2026, 11, 25), name="沪深300"),
    ]
    added = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, model, key):
            return fake_run if model is collection_mod.Run else None

        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: fake_instruments)

        def add(self, obj):
            added.append(obj)

        def delete(self, obj):
            return None

        def execute(self, stmt):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(collection_mod, "Session", FakeSession)
    monkeypatch.setattr(
        collection_mod,
        "now",
        lambda: datetime(2026, 11, 27, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    def fail_chatbi(code, start, end):
        raise ValueError("数据源鉴权失败，请检查后端凭据")

    fallback_calls = []

    def fake_fallback(db, code, *, end_date, collected_at, tencent_start_year=2004):
        fallback_calls.append((code, end_date, tencent_start_year))
        return {
            "selected_source": "eastmoney",
            "backfill_candidates": 1,
        }

    collection_mod.collect(
        1,
        fetch=fail_chatbi,
        fetch_equity=lambda c: {
            "actions": {"dividends": [], "splits": []},
            "source_url": "https://example.com",
            "source_html": "html",
            "source_sha256": "0" * 64,
            "collected_at": datetime(2026, 11, 27, 1, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        },
        fallback_fn=fake_fallback,
    )

    assert fallback_calls == [("510300", date(2026, 11, 26), 2025)]
    assert fake_run.status == "success"
    assert len(added) == 1 and added[0].end == date(2026, 11, 26)
    assert any("静默" not in log["message"] and "切换免费源 eastmoney" in log["message"] for log in fake_run.logs if log.get("kind") == "market")


def test_backfill_persists_verified_suspensions_even_without_missing_candles():
    """无缺失日K可补时，apply=True 仍应将已核验停牌日幂等持久化入库。"""
    dates = ["2026-01-05", "2026-01-07"]
    em_rows = _sample_series(dates)
    sn_rows = _sample_series(dates, include_amount=False)
    tx_rows = _sample_series(dates, include_amount=False)

    executed = []
    commits = []

    class FakeDb:
        def scalars(self, stmt):
            return [
                SimpleNamespace(
                    date=date.fromisoformat(row["trade_date"]),
                    open=row["open"],
                    high=row["high"],
                    low=row["low"],
                    close=row["close"],
                    adjusted_close=row["close"],
                    volume=row["volume"],
                    amount=row["amount"],
                )
                for row in em_rows
            ]

        def get(self, model, key):
            return SimpleNamespace(corporate_actions={"dividends": [], "splits": []})

        def execute(self, stmt):
            executed.append(stmt)

        def commit(self):
            commits.append(True)

    fake_db = FakeDb()
    result = backfill_instrument_history(
        fake_db,
        "512100",
        end_date=date(2026, 1, 7),
        collected_at=datetime(2026, 11, 28, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        fetchers={
            "eastmoney": lambda code, *, end_date=None: em_rows,
            "sina": lambda code, *, end_date=None: sn_rows,
            "tencent": lambda code, *, end_date=None: tx_rows,
        },
        apply=True,
    )

    assert result["backfill_candidates"] == 0
    assert len(executed) == 1
    assert len(commits) == 1
    # 单源或不足两源的审计记录不得入库
    assert (
        persist_verified_suspensions(
            fake_db,
            "512100",
            {
                "available_source_count": 1,
                "calendar_version": "test",
                "verified_suspensions": [{"trade_date": "2026-01-06", "sources": ["eastmoney"]}],
            },
            datetime(2026, 11, 28, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        == 0
    )
