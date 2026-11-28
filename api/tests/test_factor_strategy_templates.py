"""验证三套新因子比较策略的规则快照、回测确定性、预热校验与采用拦截。"""

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import main, strategy_plans, strategy_workbench
from app.backtest import run_backtest
from app.backtest_data import trading_days
from app.factor_strategy_templates import (
    FACTOR_TEMPLATES,
    factor_template_snapshot,
    prepare_factor_template,
    validate_factor_template_parameters,
)
from app.models import (
    AccountSyncRun,
    BacktestRun,
    BacktestSource,
    Candle,
    IndexValuationDaily,
    Instrument,
    InstrumentIndexLink,
    InstrumentStrategyAssignment,
    InstrumentVerifiedSuspension,
    MarketFearGreedDaily,
    ResearchFactor,
    ResearchStrategyFactor,
    ResearchStrategyScope,
    StrategyComparison,
)
from app.research_factors import STRATEGIES
from app.shared_etf_snapshot import normalize_split_history


def _synthetic_rows(start_text, end_text):
    days, _ = trading_days(start_text, end_text)
    rows = []
    for idx, day in enumerate(days):
        wave = Decimal(idx % 30 - 15) * Decimal("0.015")
        close = (Decimal("2.000") + Decimal(idx) * Decimal("0.002") + wave).quantize(
            Decimal("0.001")
        )
        rows.append(
            {
                "trade_date": day,
                "open": str(close),
                "high": str(close + Decimal("0.030")),
                "low": str(close - Decimal("0.030")),
                "close": str(close),
                "adjusted_close": str(close),
                "volume": str(100000 + (idx % 10) * 5000),
            }
        )
    return days, rows


def test_factor_template_snapshot_validates_strictly_and_runs_deterministically():
    days, rows = _synthetic_rows("2024-01-02", "2025-06-30")
    external = {
        "valuation_rows": [
            {
                "trade_date": day,
                "metric_key": "premium_diff",
                "metric_value": "4.5",
                "value_status": "valid",
            }
            for day in days
        ],
        "market_rows": [
            {"trade_date": day, "fear_greed_score": "15" if idx % 40 == 0 else "50"}
            for idx, day in enumerate(days)
        ],
    }

    for strategy_id, spec in FACTOR_TEMPLATES.items():
        snap = factor_template_snapshot(strategy_id, "510300")
        assert snap["adoptable"] is False
        assert snap["min_warmup_bars"] == spec["min_warmup_bars"]
        params = {
            "template": snap,
            "decision_start": days[260],
            "external": external,
            "slippage_bps": 5,
        }
        validate_factor_template_parameters(params)
        first = prepare_factor_template(rows, [], params)
        second = prepare_factor_template(rows, [], params)
        assert [p["decision"] for p in first] == [p["decision"] for p in second]
        assert first[spec["min_warmup_bars"] - 2]["decision"] is None
        assert first[260]["decision"] is not None

        tampered = deepcopy(params)
        tampered["template"]["risk_baseline"]["weak_exit_days"] = 999
        with pytest.raises(ValueError, match="不一致"):
            validate_factor_template_parameters(tampered)

        result = run_backtest(
            rows,
            [],
            {
                "instrument_code": "510300",
                "start_date": days[261],
                "end_date": days[-1],
                "initial_cash": Decimal(50000),
                "commission_rate": Decimal("0.0001"),
                "minimum_commission": Decimal(0),
                "slippage_bps": Decimal(5),
                "strategy_key": "factor_strategy",
                "parameters": params,
            },
        )
        assert Decimal(result["strategy"]["metrics"]["final_equity"]) > 0


def test_factor_template_rejects_insufficient_warmup():
    days, rows = _synthetic_rows("2025-01-02", "2025-08-29")
    snap = factor_template_snapshot("trend_pullback", "510300")
    params = {
        "template": snap,
        "decision_start": days[100],
        "external": {},
        "slippage_bps": 5,
    }
    with pytest.raises(ValueError, match="预热数据不足"):
        run_backtest(
            rows,
            [],
            {
                "instrument_code": "510300",
                "start_date": days[101],
                "end_date": days[-1],
                "initial_cash": Decimal(50000),
                "commission_rate": Decimal("0.0001"),
                "minimum_commission": Decimal(0),
                "slippage_bps": Decimal(5),
                "strategy_key": "factor_strategy",
                "parameters": params,
            },
        )


def test_workbench_compare_verify_and_adopt_guard_for_new_factor_strategies(monkeypatch):
    days, rows = _synthetic_rows("2024-01-02", "2025-06-30")
    now_dt = datetime(2026, 11, 28, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    candles = [
        SimpleNamespace(
            code="510300",
            date=date.fromisoformat(row["trade_date"]),
            open=Decimal(row["open"]),
            high=Decimal(row["high"]),
            low=Decimal(row["low"]),
            close=Decimal(row["close"]),
            adjusted_close=Decimal(row["adjusted_close"]),
            volume=Decimal(row["volume"]),
            source_updated_at="test",
            collected_at=now_dt,
        )
        for row in rows
    ]
    source = SimpleNamespace(
        instrument_code="510300",
        source_url="https://example.com/510300",
        source_sha256="a" * 64,
        source_html="html",
        checked_through_date=date.fromisoformat(days[-1]),
        collected_at=now_dt,
        corporate_actions={"dividends": [], "splits": []},
    )
    comparisons = {}
    next_id = {"run": 1, "comp": 1}

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def connection(self, **kwargs):
            return None

        def execute(self, stmt, *args):
            sql = str(stmt)
            if "candles" in sql:
                return [("510300", item.date) for item in candles]
            return None

        def get(self, model, key):
            if model is Instrument:
                return (
                    SimpleNamespace(
                        code=key, name="沪深300ETF", research_category="大盘宽基"
                    )
                    if key == "510300"
                    else None
                )
            if model is BacktestSource:
                return source if key == "510300" else None
            if model is StrategyComparison:
                return comparisons.get(key)
            return None

        def scalars(self, stmt):
            entity = stmt.column_descriptions[0]["entity"]
            if entity is Instrument:
                return [
                    SimpleNamespace(
                        code="510300", name="沪深300ETF", research_category="大盘宽基"
                    )
                ]
            if entity is BacktestSource:
                return [source]
            if entity is Candle:
                return candles
            if entity is InstrumentIndexLink:
                return ["000300.SH"]
            if entity is IndexValuationDaily:
                return [
                    SimpleNamespace(
                        trade_date=date.fromisoformat(day),
                        metric_key="premium_diff",
                        metric_value=Decimal("4.5"),
                        value_status="valid",
                    )
                    for day in days
                ]
            if entity is MarketFearGreedDaily:
                return [
                    SimpleNamespace(
                        trade_date=date.fromisoformat(day),
                        fear_greed_score=Decimal(15),
                    )
                    for day in days
                ]
            if entity is InstrumentVerifiedSuspension:
                return []
            if entity is ResearchFactor:
                return [
                    SimpleNamespace(
                        factor_id=fid,
                        factor_name=meta["name"],
                        category=meta["category"],
                        meaning=meta["meaning"],
                    )
                    for fid, meta in __import__(
                        "app.research_factors", fromlist=["FACTORS"]
                    ).FACTORS.items()
                ]
            if entity is ResearchStrategyFactor:
                return [
                    SimpleNamespace(
                        strategy_id=sid,
                        factor_id=fid,
                        role=role,
                        display_order=idx,
                    )
                    for sid, meta in STRATEGIES.items()
                    if not meta.get("research_only")
                    for idx, (fid, role) in enumerate(meta["factors"])
                ]
            if entity is InstrumentStrategyAssignment:
                return []
            return []

        def add(self, obj):
            if isinstance(obj, BacktestRun):
                obj.backtest_run_id = next_id["run"]
                next_id["run"] += 1
            elif isinstance(obj, StrategyComparison):
                obj.comparison_id = next_id["comp"]
                next_id["comp"] += 1
                comparisons[obj.comparison_id] = obj

        def flush(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(strategy_workbench, "Session", FakeSession)
    monkeypatch.setattr(
        strategy_workbench,
        "backtest_instruments",
        lambda algorithm_warmup=60: [
            {
                "instrument_code": "510300",
                "instrument_name": "沪深300ETF",
                "first_date": days[0],
                "last_date": days[-1],
                "default_start": days[60],
                "default_end": days[-1],
                "source_checked_through": days[-1],
            }
        ],
    )
    client = TestClient(main.app)

    cat = client.get("/strategies/catalog").json()
    by_id = {item["id"]: item for item in cat["strategies"]}
    assert by_id["range_breakout"]["adoptable"] is True
    assert by_id["trend_pullback"]["adoptable"] is False
    assert by_id["volatility_contraction_breakout"]["adoptable"] is False
    assert by_id["value_sentiment_reversal"]["adoptable"] is False

    # 预热不足时仅缺少预热的轨道失败，其余成功（单轨隔离失败）
    partial = client.post(
        "/strategies/comparisons",
        json={
            "instrument_code": "510300",
            "start_date": days[70],
            "end_date": days[-1],
            "strategies": ["trend_pullback", "volatility_contraction_breakout"],
        },
    )
    assert partial.status_code == 200, partial.text
    p_data = partial.json()
    assert not p_data["complete"]
    assert p_data["tracks"][0]["status"] == "failed"
    assert "250" in p_data["tracks"][0]["reason"]
    assert p_data["tracks"][1]["status"] == "success"

    # 满足 250 日预热后 3 套新因子策略均可完整比较与复算，且严格禁止采用
    full = client.post(
        "/strategies/comparisons",
        json={
            "instrument_code": "510300",
            "start_date": days[260],
            "end_date": days[-1],
            "strategies": [
                "trend_pullback",
                "volatility_contraction_breakout",
                "value_sentiment_reversal",
            ],
        },
    )
    assert full.status_code == 200, full.text
    f_data = full.json()
    assert f_data["complete"] is True
    assert (
        client.post(f"/strategies/comparisons/{f_data['id']}/verify").json()[
            "identical"
        ]
        is True
    )
    for sid in (
        "trend_pullback",
        "volatility_contraction_breakout",
        "value_sentiment_reversal",
    ):
        resp = client.post(
            "/strategies/adopt",
            json={"comparison_id": f_data["id"], "strategy_id": sid},
        )
        assert resp.status_code == 422
        assert "比较观察" in resp.json()["detail"]

    # 离线 research_only 策略依然在接口层被拒绝
    assert (
        client.post(
            "/strategies/comparisons",
            json={
                "instrument_code": "510300",
                "start_date": days[260],
                "end_date": days[-1],
                "strategies": ["left_reversal_research"],
            },
        ).status_code
        == 422
    )


def test_factor_template_cross_split_warmup_and_category_scope_adoption(monkeypatch):
    """验证跨份额折算全历史预热及分类绑定下的黄金采用与创业板观察拦截。"""
    days, full_rows = _synthetic_rows("2024-01-02", "2025-09-30")
    split_day = days[300]
    actions = {"dividends": [], "splits": [{"effective_date": split_day, "ratio": "1:2"}]}
    raw_rows = []
    for row in full_rows:
        item = dict(row)
        if row["trade_date"] > split_day:
            for key in ("open", "high", "low", "close"):
                item[key] = str((Decimal(row[key]) / 2).quantize(Decimal("0.0001")))
            item["adjusted_close"] = row["close"]
            item["volume"] = str(Decimal(row["volume"]) * 2)
        raw_rows.append(item)

    warmup_rows, warmup_actions, _ = normalize_split_history(raw_rows, actions)
    post_rows = [row for row in raw_rows if row["trade_date"] > split_day]
    assert len(post_rows) < 250

    now_dt = datetime(2026, 11, 28, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    cutoff_date = date.fromisoformat(post_rows[-1]["trade_date"])
    execution_date = date(2025, 10, 9)
    scopes = [
        SimpleNamespace(
            strategy_id="range_breakout",
            category_name="通用",
            scope_type="universal",
            research_version="shared-baseline-v1.0",
            evidence_tier="baseline",
            adoptable=True,
            evidence_summary={"note": "通用基准"},
        ),
        SimpleNamespace(
            strategy_id="trend_pullback",
            category_name="黄金",
            scope_type="category",
            research_version="factor-strategy-research-v1.5.0",
            evidence_tier="single_unit_candidate",
            adoptable=True,
            evidence_summary={"note": "黄金开放采用"},
        ),
        SimpleNamespace(
            strategy_id="gem_bottom_contraction",
            category_name="创业板",
            scope_type="category",
            research_version="factor-strategy-research-v1.5.0",
            evidence_tier="holdout_watch",
            adoptable=False,
            evidence_summary={"note": "创业板观察"},
        ),
    ]
    candles_by_code = {
        code: [
            SimpleNamespace(
                code=code,
                date=date.fromisoformat(row["trade_date"]),
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                adjusted_close=Decimal(row["adjusted_close"]),
                volume=Decimal(row["volume"]),
                source_updated_at="test",
                collected_at=now_dt,
            )
            for row in raw_rows
        ]
        for code in ("518880", "159915")
    }
    sources_by_code = {
        code: SimpleNamespace(
            instrument_code=code,
            source_url=f"https://example.com/{code}",
            source_sha256="a" * 64,
            source_html="html",
            checked_through_date=cutoff_date,
            collected_at=now_dt,
            corporate_actions=actions,
        )
        for code in ("518880", "159915")
    }
    instruments_by_code = {
        "518880": SimpleNamespace(code="518880", name="黄金ETF", research_category="黄金"),
        "159915": SimpleNamespace(code="159915", name="创业板ETF", research_category="创业板"),
    }
    comparisons = {}
    assignments = {}
    next_id = {"run": 1, "comp": 1, "assign": 1}

    class ScopeFakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def connection(self, **kwargs):
            return None

        def execute(self, stmt, *args):
            sql = str(stmt)
            if "account_sync_runs" in sql or "account_holding" in sql:
                return SimpleNamespace(all=lambda: [(None, None)])
            if "candles" in sql:
                return [
                    (code, item.date)
                    for code, items in candles_by_code.items()
                    for item in items
                ]
            return SimpleNamespace(all=list)

        def get(self, model, key):
            if model is Instrument:
                return instruments_by_code.get(key)
            if model is BacktestSource:
                return sources_by_code.get(key)
            if model is StrategyComparison:
                return comparisons.get(key)
            return None

        def scalar(self, stmt):
            entity = stmt.column_descriptions[0]["entity"]
            if entity is InstrumentStrategyAssignment:
                return assignments.get("518880")
            if entity is Candle:
                return cutoff_date
            if entity is AccountSyncRun:
                return None
            return None

        def scalars(self, stmt):
            entity = stmt.column_descriptions[0]["entity"]
            if entity is Instrument:
                return list(instruments_by_code.values())
            if entity is BacktestSource:
                return list(sources_by_code.values())
            if entity is ResearchStrategyScope:
                return scopes
            if entity is Candle:
                code = "518880"
                for param in stmt.compile().params.values():
                    if param in candles_by_code:
                        code = param
                        break
                return candles_by_code[code]
            if entity is InstrumentVerifiedSuspension:
                return []
            if entity is ResearchFactor:
                return [
                    SimpleNamespace(
                        factor_id=fid,
                        factor_name=meta["name"],
                        category=meta["category"],
                        meaning=meta["meaning"],
                    )
                    for fid, meta in __import__(
                        "app.research_factors", fromlist=["FACTORS"]
                    ).FACTORS.items()
                ]
            if entity is ResearchStrategyFactor:
                return [
                    SimpleNamespace(
                        strategy_id=sid,
                        factor_id=fid,
                        role=role,
                        display_order=idx,
                    )
                    for sid, meta in STRATEGIES.items()
                    if not meta.get("research_only")
                    for idx, (fid, role) in enumerate(meta["factors"])
                ]
            if entity is InstrumentStrategyAssignment:
                return list(assignments.values())
            return []

        def add(self, obj):
            if isinstance(obj, BacktestRun):
                obj.backtest_run_id = next_id["run"]
                next_id["run"] += 1
            elif isinstance(obj, StrategyComparison):
                obj.comparison_id = next_id["comp"]
                next_id["comp"] += 1
                comparisons[obj.comparison_id] = obj
            elif isinstance(obj, InstrumentStrategyAssignment):
                obj.assignment_id = next_id["assign"]
                next_id["assign"] += 1
                assignments[obj.instrument_code] = obj

        def flush(self):
            return None

        def commit(self):
            return None

    monkeypatch.setattr(strategy_workbench, "Session", ScopeFakeSession)
    monkeypatch.setattr(
        strategy_workbench,
        "backtest_instruments",
        lambda algorithm_warmup=60: [
            {
                "instrument_code": code,
                "instrument_name": inst.name,
                "first_date": days[0],
                "last_date": days[-1],
                "default_start": post_rows[10]["trade_date"],
                "default_end": days[-1],
                "source_checked_through": days[-1],
            }
            for code, inst in instruments_by_code.items()
        ],
    )
    client = TestClient(main.app)

    cat = {item["id"]: item for item in client.get("/strategies/catalog").json()["strategies"]}
    assert cat["trend_pullback"]["supported_instruments"] == ["518880"]
    assert cat["trend_pullback"]["adoptable_instruments"] == ["518880"]
    assert cat["trend_pullback"]["earliest_start_by_instrument"]["518880"] == post_rows[1]["trade_date"]
    assert cat["gem_bottom_contraction"]["supported_instruments"] == ["159915"]
    assert cat["gem_bottom_contraction"]["adoptable_instruments"] == []

    # 跨分类对比被拦截（不能用黄金策略回测创业板）
    assert (
        client.post(
            "/strategies/comparisons",
            json={
                "instrument_code": "159915",
                "start_date": post_rows[5]["trade_date"],
                "end_date": post_rows[-1]["trade_date"],
                "strategies": ["trend_pullback"],
            },
        ).status_code
        == 422
    )

    # 折算后仅数日仍能借助全历史跨拆预热完整运行 250 日策略并复算一致
    comp = client.post(
        "/strategies/comparisons",
        json={
            "instrument_code": "518880",
            "start_date": post_rows[5]["trade_date"],
            "end_date": post_rows[-1]["trade_date"],
            "strategies": ["trend_pullback"],
        },
    )
    assert comp.status_code == 200, comp.text
    comp_data = comp.json()
    assert comp_data["complete"] is True
    assert client.post(f"/strategies/comparisons/{comp_data['id']}/verify").json()["identical"] is True

    # 黄金采用 trend_pullback 成功，并支持任务5盘前生成
    adopted = client.post(
        "/strategies/adopt",
        json={"comparison_id": comp_data["id"], "strategy_id": "trend_pullback"},
    )
    assert adopted.status_code == 200, adopted.text
    with ScopeFakeSession() as db:
        plan, evidence = strategy_plans.make_assignment_plan(
            db, assignments["518880"], now_dt, cutoff_date, execution_date
        )
        assert plan["action"] in {"buy", "hold", "sell", "wait"}
        assert evidence["strategy_id"] == "trend_pullback"
        assert plan["conditions"]["buy"] and plan["conditions"]["sell"]

    # 创业板对比 gem_bottom_contraction 成功，但禁止采用
    gem_comp = client.post(
        "/strategies/comparisons",
        json={
            "instrument_code": "159915",
            "start_date": post_rows[5]["trade_date"],
            "end_date": post_rows[-1]["trade_date"],
            "strategies": ["gem_bottom_contraction"],
        },
    )
    assert gem_comp.status_code == 200 and gem_comp.json()["complete"] is True
    gem_adopt = client.post(
        "/strategies/adopt",
        json={"comparison_id": gem_comp.json()["id"], "strategy_id": "gem_bottom_contraction"},
    )
    assert gem_adopt.status_code == 422
    assert "尚未达到研究采用门槛" in gem_adopt.json()["detail"]

    # 纯单元校验证明 warmup_rows 长度与末尾日期错位会被拒绝
    with pytest.raises(ValueError, match="不一致"):
        prepare_factor_template(
            post_rows,
            [],
            {
                "template": factor_template_snapshot("trend_pullback", "518880"),
                "decision_start": post_rows[-1]["trade_date"],
                "external": {"warmup_rows": warmup_rows[:-1], "warmup_dividends": warmup_actions["dividends"]},
                "slippage_bps": 5,
            },
        )
