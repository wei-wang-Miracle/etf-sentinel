"""顶底研究复用统一回测引擎和退出轮次诊断，不维护另一套分红账本。"""

import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'api'))
from app.backtest import simulate  # noqa: E402
from app.strategies import Decision  # noqa: E402
from app.strategy_research import diagnostics  # noqa: E402

root, start, end = sys.argv[1:4]
history = json.loads((Path(root) / 'qualified-history.json').read_text())
all_signals = json.load(sys.stdin)
funds = []
for code, signals in all_signals.items():
    item = history[code]
    rows = [row for row in item['auditRows'] if row['trade_date'] <= end]
    by_date = {signal['date']: signal for signal in signals}
    target, decisions = 0, []
    for row in rows:
        signal = by_date.get(row['trade_date'])
        if signal:
            target = int(signal['kind'] == 'bottom')
        decisions.append({'decision': Decision(target, signal['reason'] if signal else '保持目标仓位'), 'indicators': {}})
    begin = max(1, next(i for i, row in enumerate(rows) if row['trade_date'] >= start))
    settings = {'initial_cash': 50000, 'commission_rate': .0001, 'minimum_commission': 0,
                'slippage_bps': 5, 'end_date': end}
    account = simulate(rows, item['actions']['dividends'], settings, decisions, begin)
    checked = diagnostics(account)
    buys = {trade['trade_date']: trade for trade in account['trades'] if trade['side'] == 'buy'}
    sells = {trade['trade_date']: trade for trade in account['trades'] if trade['side'] == 'sell'}
    indices = {row['trade_date']: i for i, row in enumerate(rows)}
    pairs = []
    for pair in checked['rounds']:
        buy, sell = buys[pair['entry_date']], sells[pair['exit_date']]
        cost = Decimal(buy['notional']) + Decimal(buy['commission'])
        pairs.append({'entryDate': pair['entry_date'], 'exitDate': pair['exit_date'],
                      'profit': float(pair['pnl']), 'return': float(Decimal(pair['pnl']) / cost),
                      'holdingDays': indices[pair['exit_date']] - indices[pair['entry_date']],
                      'entrySignalDate': buy['signal_date'], 'exitSignalDate': sell['signal_date']})
    last = account['daily'][-1]
    opening = next(reversed(buys.values()), None) if last['quantity'] else None
    open_profit = 0
    open_days = 0
    if opening:
        income = sum(Decimal(event['amount']) for event in account['dividends'] if event['kind'] == 'receivable' and event['trade_date'] >= opening['trade_date'])
        open_profit = float(Decimal(last['market_value']) + income - Decimal(opening['notional']) - Decimal(opening['commission']))
        open_days = indices[last['trade_date']] - indices[opening['trade_date']]
    funds.append({'code': code, 'name': item['name'], 'indices': item['indices'], 'signals': signals,
                  'initialCash': 50000, 'finalEquity': float(last['equity']),
                  'totalReturn': account['metrics']['total_return'], 'maxDrawdown': account['metrics']['max_drawdown'],
                  'trades': [{**t, 'price': float(t['price']), 'tradeDate': t['trade_date'], 'signalDate': t['signal_date']} for t in account['trades']],
                  'pairs': pairs, 'daily': [{'date': r['trade_date'], 'equity': float(r['equity']), 'cash': float(r['cash']), 'quantity': r['quantity'], 'drawdown': r['drawdown']} for r in account['daily']],
                  'dividends': account['dividends'], 'openQuantity': last['quantity'], 'openProfit': open_profit,
                  'openHoldingDays': open_days, 'completedTrades': len(pairs), 'winningTrades': sum(p['profit'] > 0 for p in pairs)})
json.dump(funds, sys.stdout, ensure_ascii=False)
