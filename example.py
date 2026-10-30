from physical_engine import Instruction, replay

days = [1, 2, 3]
bars = {(d, "SH600001"): {"open": p, "close": p, "buy_allowed": True, "sell_allowed": True} for d, p in zip(days, [10., 10., 10.5])}
orders = [Instruction(1, 2, {"SH600001": 100})]
result = replay(days, bars, orders, lambda side, symbol, shares, price, day: 5., initial_cash=10000., external_funding=False)
for row in result["daily"]:
    print(row["date"], "cash", round(row["cash"], 2), "equity", round(row["equity"], 2))
