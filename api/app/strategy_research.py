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


def diagnostics(account, initial=RESEARCH_CASH, *, dividend_record_dates=None):
    """补充水下交易日、在场比例和完整退出轮次，末尾未平仓单列。

    轮次净盈亏包含买卖佣金及持有期间权益分红，滑点已体现在成交价格中。
    指定除息日到登记日的映射时，按登记日收盘持仓归属已入账权益；否则保留旧口径。
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

    def held_for_dividend(ex_date, entry_date, exit_date):
        if dividend_record_dates is None:
            return entry_date <= ex_date <= exit_date
        # 卖出在开盘，登记日收盘时已不持有。同理，登记日开盘买入可取得权益。
        return entry_date <= dividend_record_dates[ex_date] < exit_date

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
                    and held_for_dividend(
                        event["trade_date"], opening["trade_date"], trade["trade_date"]
                    )
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
