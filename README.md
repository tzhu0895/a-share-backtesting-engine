# A-Share Backtesting Engine

A share-and-cash backtesting component extracted from an AI-assisted quantitative research workflow. Includes a synthetic example and tests; it does not contain a proprietary strategy or real account data.

## Features

- Close-to-next-session order scheduling, explicitly supplied opening tradability, blocked-order retry and target replacement.
- Separate cash, positions, costs, optional external flows and flow-adjusted return.
- Board-specific share quantity rules, dividend/bonus event accounting, optional slippage and fee callback.
- Inputs describe observed/assumed tradability; opening fills and exchange-rule compliance are not independently certified by this software. Data-vintage checks and historical fee schedules remain the caller’s responsibility.

## Run

Python 3.10+; standard library only.

```bash
python -m unittest -v test_physical_engine
python example.py
```

The example uses entirely synthetic prices and is not a performance claim. The engine does not place orders.
