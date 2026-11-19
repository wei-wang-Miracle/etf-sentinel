"""策略研究账户的独立储备资金与风险统计。"""

from copy import deepcopy
from decimal import Decimal

from app.backtest import metrics, money

RESEARCH_CASH = Decimal(50000)
RESEARCH_VERSION = "1.1"


def with_reserve(account, reserve):
    """加入不参与交易的零息储备；按总资金重算净值与回撤，不改变成交。"""
    result = deepcopy(account)
    initial = RESEARCH_CASH
    peak = initial
    for row in result["daily"]:
        equity = Decimal(row["equity"]) + reserve
        peak = max(peak, equity)
        row.update(
            cash=str(money(Decimal(row["cash"]) + reserve)),
            equity=str(money(equity)),
            nav=float(equity / initial),
            drawdown=float(equity / peak - 1),
            position_weight=float(Decimal(row["market_value"]) / equity),
        )
    result["metrics"] = metrics(result["daily"], result["trades"], initial)
    return result


def diagnostics(account, initial=RESEARCH_CASH):
    """补充水下交易日、在场比例和完整退出轮次，末尾未平仓单列。

    轮次净盈亏包含买卖佣金及持有期间权益分红，滑点已体现在成交价格中。
    仅适用于现有空满仓引擎的一买一卖账户，不推断真实委托先后。
    """
    peak, underwater, longest = initial, 0, 0
    for row in account["daily"]:
        equity = Decimal(row["equity"])
        if equity < peak:
            underwater += 1
            longest = max(longest, underwater)
        else:
            peak, underwater = equity, 0
    rounds, opening = [], None
    for trade in account["trades"]:
        if trade["side"] == "buy":
            opening = trade
        elif opening:
            dividends = sum(
                (
                    Decimal(event["amount"])
                    for event in account["dividends"]
                    if event["kind"] == "receivable"
                    and opening["trade_date"]
                    <= event["trade_date"]
                    <= trade["trade_date"]
                ),
                Decimal(0),
            )
            pnl = (
                Decimal(trade["notional"])
                - Decimal(trade["commission"])
                - Decimal(opening["notional"])
                - Decimal(opening["commission"])
                + dividends
            )
            rounds.append(
                {
                    "entry_date": opening["trade_date"],
                    "exit_date": trade["trade_date"],
                    "pnl": str(money(pnl)),
                }
            )
            opening = None
    return {
        "longest_underwater_days": longest,
        "time_in_market": sum(r["quantity"] > 0 for r in account["daily"])
        / len(account["daily"]),
        "completed_rounds": len(rounds),
        "open_rounds": int(opening is not None),
        "rounds": rounds,
        "sample_warning": "完整退出不足5轮，不能据此判断稳定性"
        if len(rounds) < 5
        else None,
    }
