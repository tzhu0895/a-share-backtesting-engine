"""Execution and cash-flow primitives extracted from the research ledger."""

from math import isfinite

def _finite_nonnegative(value, name):
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f'{name} must be finite and nonnegative')
    return value

def legal_buy_shares(symbol, requested):
    """Only lot-size normalization; listing/date eligibility is checked elsewhere.

    Mainboard: increments of 100. STAR: at least 200, then increments of one.
    A sell may involve odd-lot liquidation and is NOT handled by this function.
    """
    quantity = int(_finite_nonnegative(requested, 'requested'))
    if symbol.startswith('SH688'):
        return quantity if quantity >= 200 else 0
    return quantity // 100 * 100

def own_capital_return(previous_equity, opening_equity_before_flow,
                       opening_external_flow, closing_equity):
    """Flow-adjusted return with exactly one flow at the opening boundary.

    The caller must ensure opening_equity_before_flow includes the old holdings'
    overnight PnL and closing_equity includes the flow and all actual costs.
    Supports withdrawals only if post-flow opening equity remains positive.
    """
    values = [float(x) for x in (previous_equity, opening_equity_before_flow,
                                opening_external_flow, closing_equity)]
    if not all(isfinite(x) for x in values):
        raise ValueError('nonfinite equity or flow')
    prev, before, flow, closing = values
    if min(prev, before, before + flow, closing) <= 0:
        raise ValueError('nonpositive equity')
    return (before / prev) * (closing / (before + flow)) - 1

def legal_sell_shares(symbol,requested,owned):
    """Largest legal sell order no larger than requested / available inventory.

    Mainboard odd remainder may be sold once alone or alongside whole hundreds.
    STAR orders require 200 shares unless liquidating an entire sub-200 balance.
    Sources: SSE 2023-02-09 quantity/front-control notice; STAR trading rules.
    """
    available=int(_finite_nonnegative(owned,'owned'))
    q=min(int(_finite_nonnegative(requested,'requested')),available)
    if symbol.startswith('SH688'):
        return q if q>=200 or q==available else 0
    odd=available%100
    hundreds=q//100*100
    return hundreds+odd if odd and q-hundreds>=odd else hundreds
