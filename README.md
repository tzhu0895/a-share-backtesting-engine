# A-Share Backtesting Engine

A small, event-driven share and cash ledger for researching equity execution under explicit trading constraints. It accepts target-share instructions and market data supplied by the caller; it does not generate investment signals, contain a trading strategy, or connect to a broker.

## Why this project?

Portfolio returns based only on target weights can overlook cash balances, blocked orders and share-size constraints. This project makes those assumptions visible in an inspectable daily ledger. It is a research component, not a certified exchange simulator.

## Features

- Freeze a target on a signal day and execute no earlier than a subsequent session.
- Apply caller-supplied buy/sell permissions at the open; retry pending instructions and replace them when a newer target arrives.
- Track shares, locked shares, cash, fees, optional capital flows and flow-adjusted daily return.
- Normalize purchases and sales using the included board-specific quantity conventions.
- Process dated cash dividends and bonus shares; apply an optional caller-supplied dividend tax book and fee callback.
- Apply a fixed adverse basis-point adjustment to the open when requested.

## Installation and quick start

Requires Python 3.10 or newer and the standard library. Clone this repository, then:

```bash
python -m unittest -v test_physical_engine
python example.py
```

The example creates three fictional sessions and a fixed order. A representative output is:

```text
1 cash 10000.0 equity 10000.0
2 cash 8995.0 equity 9995.0
3 cash 8995.0 equity 10045.0
```

These numbers are synthetic illustrations, not financial performance.

## Interface

```python
from physical_engine import Instruction, replay

dates = [1, 2, 3]
bars = {(day, "SH600001"): {
    "open": price, "close": price,
    "buy_allowed": True, "sell_allowed": True,
} for day, price in zip(dates, [10.0, 10.0, 10.5])}
orders = [Instruction(signal_date=1, execution_date=2, shares={"SH600001": 100})]

def fees(side, symbol, shares, price, day):
    return 5.0

result = replay(dates, bars, orders, fees, initial_cash=10_000, external_funding=False)
print(result["daily"][-1]["equity"])
```

`dates` must be unique and sorted. Each instruction contains a complete target-share mapping. `bars` maps `(date, symbol)` to prices and open-time permissions. Missing trade permissions fail closed. The fee callback must return the transaction cost for the given side and fill.

The returned dictionary contains `daily`, `orders`, `flows`, `blocked`, `positions`, `actions` and `tax_ledger`. `daily` includes cash, stock value, receivables, equity, fees, capital flows and flow-adjusted returns. `orders` records simulated fills; `blocked` explains unfilled attempts. A target is an intention, not a guaranteed fill.

## Execution model and limits

- The caller supplies the session calendar, actual data availability and open-time trade permissions. Daily high/low or closing volume are not proof of an opening fill.
- The engine models main-board and STAR share-size conventions, but listing eligibility, current exchange rules and instrument-specific exceptions require separate validation.
- `slippage_bps` is an assumption, not a measured market-impact model. No minute-level liquidity, order book, queue position, brokerage integration or capacity estimate is supplied.
- Default external funding is enabled; pass `external_funding=False` for a cash-limited example. External deposits are recorded separately from economic profit.
- Dividend events and tax behavior depend on supplied event records and callbacks. Historical tax schedules and data point-in-time correctness are not certified.

## Project files

- `physical_engine.py` — replay and ledger.
- `repair_primitives.py` — quantity and cash-flow helpers.
- `example.py` — standalone synthetic example.
- `test_physical_engine.py` — execution, accounting and error-handling tests.

This repository was assembled with AI-assisted development and human-directed review. No real portfolio records or proprietary strategy are included.
