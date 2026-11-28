"""验证在线因子图接口的预热校验窗口、已核验停牌放行与错误前缀区分。"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.backtest_data import trading_days
from app.models import (
    BacktestSource,
    Candle,
    IndexCandle,
    IndexValuationDaily,
    Instrument,
    InstrumentIndexLink,
    InstrumentSentimentLink,
    InstrumentVerifiedSuspension,
    MarketFearGreedDaily,
    MarketRegimeFactorDaily,
)


def _candle_row(day_text, *, close="1.000", adjusted_close="1.000"):
    value = Decimal(close)
    return SimpleNamespace(
        date=date.fromisoformat(day_text),
        open=value,
        high=value + Decimal("0.010"),
        low=value - Decimal("0.010"),
        close=value,
        adjusted_close=Decimal(adjusted_close),
        volume=Decimal(1000),
    )


def _install_fake_session(
    monkeypatch,
    *,
    candles,
    actions,
    suspensions=(),
):
    cutoff = candles[-1].date

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def connection(self, **kwargs):
            return None

        def get(self, model, key):
            if model is Instrument:
                return SimpleNamespace(code=key, name="中证1000ETF")
            if model is BacktestSource:
                return SimpleNamespace(
                    instrument_code=key,
                    checked_through_date=cutoff,
                    corporate_actions=actions,
                )
            return None

        def scalar(self, stmt):
            return cutoff

        def scalars(self, stmt):
            entity = stmt.column_descriptions[0]["entity"]
            if entity is Candle:
                return list(candles)
            if entity is InstrumentVerifiedSuspension:
                return [
                    SimpleNamespace(
                        trade_date=date.fromisoformat(day),
                        sources=["eastmoney", "sina", "tencent"],
                    )
                    for day in suspensions
                ]
            if entity in (
                InstrumentIndexLink,
                IndexValuationDaily,
                IndexCandle,
                InstrumentSentimentLink,
                MarketFearGreedDaily,
                MarketRegimeFactorDaily,
            ):
                return []
            return []

    monkeypatch.setattr(main, "Session", FakeSession)


def test_candle_factors_skips_early_gap_outside_validation_window_and_allows_verified_suspension(
    monkeypatch,
):
    """展示起点前超过266个交易日的早期缺口不阻断看图，窗口内仅放行已核验停牌日。"""
    days, _ = trading_days("2022-01-04", "2023-12-29")
    early_gap = days[10]
    recent_suspension = days[-30]
    candles = [
        _candle_row(day)
        for day in days
        if day not in (early_gap, recent_suspension)
    ]

    _install_fake_session(
        monkeypatch,
        candles=candles,
        actions={"dividends": [], "splits": []},
        suspensions=(),
    )
    client = TestClient(main.app)
    # 窗口内有未核验缺日时应被拦截，且错误文案引导至行情而非权益资料
    blocked = client.get(f"/candles/512100/factors?start={days[-20]}&end={days[-1]}")
    assert blocked.status_code == 422
    assert blocked.json()["detail"].startswith("行情数据未通过校验：行情缺少交易日")
    assert "权益资料" not in blocked.json()["detail"]

    # 窗口内停牌日经跨源核验后放行；更早的 early_gap 在 266 日校验窗口外也不误拦
    _install_fake_session(
        monkeypatch,
        candles=candles,
        actions={"dividends": [], "splits": []},
        suspensions=(recent_suspension,),
    )
    ok = client.get(f"/candles/512100/factors?start={days[-20]}&end={days[-1]}")
    assert ok.status_code == 200, ok.text
    assert ok.json()["data_cutoff"] == days[-1]


def test_candle_factors_labels_adjustment_mismatch_with_equity_prefix(monkeypatch):
    """复权因子与分红不符时保留权益资料文案，便于前端提示更新权益资料。"""
    days, _ = trading_days("2025-11-03", "2025-11-14")
    candles = [_candle_row(day) for day in days]
    candles[-1] = _candle_row(days[-1], close="1.000", adjusted_close="1.200")
    _install_fake_session(
        monkeypatch,
        candles=candles,
        actions={"dividends": [], "splits": []},
    )
    client = TestClient(main.app)
    response = client.get(f"/candles/512100/factors?start={days[0]}&end={days[-1]}")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("权益资料或复权未通过校验：")
    assert "权益资料" in response.json()["detail"]
