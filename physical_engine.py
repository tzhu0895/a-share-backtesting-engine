"""Isolated share/cash engine. No synthetic return adjustments or broker access.

Inputs explicitly supply open-time tradability and a fee callback. The engine
cannot certify those upstream inputs; missing flags fail closed. Daily raw high,
low or closing volume are never consulted to justify an opening fill.
"""
from dataclasses import dataclass
from math import floor, isfinite

from repair_primitives import legal_buy_shares, legal_sell_shares, own_capital_return


@dataclass(frozen=True)
class Instruction:
    signal_date: object
    execution_date: object
    shares: dict


def _price(value):
    return value is not None and isfinite(float(value)) and float(value) > 0


def replay(dates, bars, instructions, fee_fn, initial_cash=100000.,
           actions=(), external_funding=True, slippage_bps=0.,tax_book=None,signal_factory=None,
           refund_settled_principal=False):
    """Replay next-legal-open orders with independent entitlement/settlement states.

    bars[(date,symbol)] = raw open/close, buy_allowed/sell_allowed at that open.
    instructions contain T-close frozen INTEGER quantities. A new instruction
    supersedes the entire older pending target; unfilled orders otherwise retry.
    actions require record_date/ex_date/pay_date and optional bonus_listing_date.
    Dividend receivables accrue on ex date and become spendable AFTER pay-date
    trading; bonus stock is valued from ex date but sellable only on listing day.
    Fee callback must include relevant tax/commission; no interest is assumed for
    self-funded deposits. Funding is never treated as profit.
    """
    dates=list(dates)
    if dates != sorted(set(dates)) or not dates:
        raise ValueError('dates must be nonempty, ordered, unique')
    if not _price(initial_cash) or not isfinite(float(slippage_bps)) or slippage_bps<0:
        raise ValueError('invalid capital or slippage')
    actions=list(actions)
    calendar=set(dates); schedules={}; by_record={}; by_ex={}; by_pay={}; by_listing={}
    bars_by_date={}
    for (d,s),bar in bars.items():bars_by_date.setdefault(d,{})[s]=bar
    for order in instructions:
        if order.signal_date not in calendar or order.execution_date not in calendar:
            raise ValueError('instruction outside explicit calendar')
        if order.execution_date <= order.signal_date:
            raise ValueError('execution must follow signal date')
        if order.execution_date in schedules:
            raise ValueError('ambiguous same-open instruction')
        if any(not isfinite(float(q)) or int(q)!=q or q<0 for q in order.shares.values()):
            raise ValueError('invalid target quantity')
        schedules[order.execution_date]=order
    for index, event in enumerate(actions):
        e=dict(event);e['id']=index
        if e.get('unsupported_if_held'):
            if e.get('record_date') is not None:
                by_record.setdefault(e['record_date'],[]).append(e)
            by_ex.setdefault(e['ex_date'],[]).append(e)
            continue
        if not (e['record_date'] < e['ex_date']):
            raise ValueError('record date must precede ex date')
        if e['record_date'] not in calendar:
            raise ValueError('record-date ownership not observable in this replay')
        if e.get('cash',0)<0 or e.get('bonus',0)<0 or e.get('rights_ratio',0):
            raise ValueError('invalid or unsupported rights action')
        if e.get('cash',0)>0 and (e.get('pay_date') is None or e['pay_date']<e['ex_date']):
            raise ValueError('missing/invalid cash payment date')
        if e.get('bonus',0)>0 and (e.get('bonus_listing_date') is None or e['bonus_listing_date']<e['ex_date']):
            raise ValueError('missing/invalid bonus listing date')
        for lookup,key in [(by_record,'record_date'),(by_ex,'ex_date'),
                           (by_pay,'pay_date'),(by_listing,'bonus_listing_date')]:
            if e.get(key) is not None:
                # Non-trading settlement date -> first following session, never earlier.
                day=next((d for d in dates if d>=e[key]),None)
                if day is not None:lookup.setdefault(day,[]).append(e)
    cash=float(initial_cash);previous=float(initial_cash);cum_deposits=0.;cum_withdrawals=0.
    holdings={};locked={};marks={};entitlements={};receivables={};awarded={};ever_held=set()
    pending=None; daily=[];fills=[];flows=[];blocked=[];positions=[];action_log=[]
    for day in dates:
        # Previous-session cash is settled. Today's sale proceeds and cash
        # dividends are not withdrawn today. Gross buys consume the settled
        # allowance first: conservative cash-account policy, no broker fast-cash.
        settled_allowance=max(0.,cash)
        if day in schedules:
            instruction=schedules[day]
            pending=Instruction(instruction.signal_date,instruction.execution_date,instruction.shares.copy())
            # A delayed order arriving AFTER an intervening split still denotes
            # the pre-split economic quantity frozen on its signal date. Ex-day
            # itself is handled below exactly once, not here.
            for e in actions:
                if (not e.get('unsupported_if_held') and e.get('bonus',0)>0
                        and instruction.signal_date<e['ex_date']<day
                        and e['symbol'] in pending.shares):
                    sym=e['symbol']
                    pending.shares[sym]=floor(pending.shares[sym]*(1+e['bonus'])+1e-9)
        for e in by_ex.get(day,[]):
            sym=e['symbol'];quantity=entitlements.get(e['id'],0)
            if e.get('unsupported_if_held'):
                if e.get('record_date') is None:
                    if sym in ever_held:
                        raise ValueError(f'Unresolved action with unobservable record-date ownership: {sym} {day}')
                elif quantity:
                    raise ValueError(f'Unresolved action with actual entitlement: {sym} {day} qty={quantity}')
                if holdings.get(sym,0) or locked.get(sym,0) or (pending and pending.shares.get(sym,0)):
                    raise ValueError(f'Unresolved action affects actual/pending holding: {sym} {day}')
                action_log.append(dict(date=day,event_id=e['id'],symbol=sym,record_shares=0,
                    receivable=0.,locked_bonus=0,unsupported_action_zero_ownership_asserted=True))
                continue
            credit=quantity*e.get('cash',0);receivables[e['id']]=credit
            bonus=floor(quantity*e.get('bonus',0)+1e-9)
            awarded[e['id']]=bonus;locked[sym]=locked.get(sym,0)+bonus
            if tax_book is not None:tax_book.ex_date(e,bonus)
            if sym in marks:
                # Differential dividends: retail cash entitlement can differ
                # from the weighted cash used in the exchange ex-reference.
                marks[sym]=(marks[sym]-e.get('reference_cash',e.get('cash',0)))/(1+e.get('reference_bonus',e.get('bonus',0)))
            if pending and sym in pending.shares:
                # Preserve the economic target across a split/bonus, rather than
                # spuriously selling the new bonus shares to the old share count.
                pending.shares[sym]=floor(pending.shares[sym]*(1+e.get('bonus',0))+1e-9)
            action_log.append(dict(date=day,event_id=e['id'],symbol=sym,
                                   record_shares=quantity,receivable=credit,locked_bonus=bonus))
        for e in by_listing.get(day,[]):
            sym=e['symbol'];qty=awarded.pop(e['id'],0)
            locked[sym]=locked.get(sym,0)-qty
            holdings[sym]=holdings.get(sym,0)+qty
            assert locked[sym]>=0
        sellable=holdings.copy()
        def mark(symbol, field):
            bar=bars.get((day,symbol),{})
            price=bar.get(field)
            if _price(price):return float(price)
            if symbol in marks:return marks[symbol]
            raise ValueError(f'no causal mark for held stock {day} {symbol}')
        opening=cash+sum(receivables.values())+sum(
            (holdings.get(s,0)+locked.get(s,0))*mark(s,'open')
            for s in set(holdings)|set(locked) if holdings.get(s,0)+locked.get(s,0)>0)
        fees=turnover=deposit=dividend_tax=0.
        if pending:
            assert pending.signal_date<day
            # Trade sells first; no same-day bought quantity can become sellable.
            for side in ('SELL','BUY'):
                for sym in sorted(set(holdings)|set(pending.shares)):
                    owned=holdings.get(sym,0);target=pending.shares.get(sym,0)
                    difference=target-owned-locked.get(sym,0)
                    quantity=-difference if side=='SELL' else difference
                    if quantity<=0:continue
                    if side=='BUY':quantity=legal_buy_shares(sym,quantity)
                    else:
                        quantity=min(quantity,sellable.get(sym,0))
                        quantity=legal_sell_shares(sym,quantity,owned)
                    if quantity<=0:continue
                    bar=bars.get((day,sym),{})
                    cap=bar.get('max_buy_qty' if side=='BUY' else 'max_sell_qty')
                    if cap is not None and quantity>cap:
                        limited=max(0,int(cap))
                        quantity=legal_buy_shares(sym,limited) if side=='BUY' else legal_sell_shares(sym,limited,owned)
                        if quantity<=0:
                            blocked.append(dict(date=day,signal_date=pending.signal_date,symbol=sym,
                                side=side,shares=int(limited),reason='PRIOR_VOLUME_CAPACITY_LIMIT'));continue
                    raw=bar.get('open');reason=None
                    if not _price(raw):reason='NO_OPEN_SUSPENSION_OR_MISSING_BAR'
                    elif bar.get('buy_allowed' if side=='BUY' else 'sell_allowed') is not True:
                        reason='OPEN_PERMISSION_NOT_VERIFIED_OR_BLOCKED'
                    if reason:
                        blocked.append(dict(date=day,signal_date=pending.signal_date,symbol=sym,
                                             side=side,shares=quantity,reason=reason));continue
                    cash_before=cash;available_before=sellable.get(sym,0);order_deposit=0.
                    price=float(raw)*(1+slippage_bps/10000*(1 if side=='BUY' else -1))
                    fee=float(fee_fn(side,sym,quantity,price,day))
                    if not isfinite(fee) or fee<0:raise ValueError('invalid fee callback')
                    transaction_fee=fee
                    tax=tax_book.preview_sell(sym,quantity,day) if tax_book is not None and side=='SELL' else 0.
                    fee+=tax
                    cost=quantity*price+fee
                    if side=='BUY' and cost>cash+1e-8:
                        if not external_funding:
                            blocked.append(dict(date=day,signal_date=pending.signal_date,symbol=sym,
                                side=side,shares=quantity,reason='INSUFFICIENT_CASH'));continue
                        amount=max(0.,cost-cash);cash+=amount;deposit+=amount;cum_deposits+=amount
                        order_deposit=amount
                        flows.append(dict(date=day,signal_date=pending.signal_date,symbol=sym,
                                          amount=amount,stage='OPEN_BEFORE_BUY',interest=0.))
                    if side=='BUY':
                        holdings[sym]=owned+quantity;cash-=cost
                        settled_allowance=max(0.,settled_allowance-cost)
                        ever_held.add(sym)
                        if tax_book is not None:tax_book.buy(sym,quantity,day)
                    else:
                        holdings[sym]=owned-quantity;sellable[sym]-=quantity
                        cash+=quantity*price-fee
                        if tax_book is not None:
                            assert abs(tax_book.sell(sym,quantity,day)-tax)<1e-7
                    if cash < -1e-7 or holdings[sym]<0:
                        raise AssertionError('negative cash or shares')
                    fees+=fee;dividend_tax+=tax;turnover+=quantity*float(raw)
                    fills.append(dict(date=day,signal_date=pending.signal_date,symbol=sym,
                        side=side,shares=quantity,raw_open=float(raw),fill_price=price,fee=fee,
                        shares_before=owned,shares_after=holdings[sym],sellable_before=available_before,
                        cash_before=cash_before,cash_after=cash,external_deposit=order_deposit,
                        transaction_fee=transaction_fee,dividend_tax=tax,
                        slippage_cost=quantity*abs(price-float(raw))))
        # After the opening orders, return only settled idle OWNER PRINCIPAL.
        # Both deposits and this withdrawal occur at the opening valuation;
        # neither closing prices nor future target quantities decide the refund.
        withdrawal=0.
        refundable=min(max(0.,cash),settled_allowance,max(0.,cum_deposits-cum_withdrawals))
        if refund_settled_principal and refundable>1e-8:
            withdrawal=refundable;cash-=withdrawal;cum_withdrawals+=withdrawal
            flows.append(dict(date=day,signal_date=day,symbol='OWNER_PRINCIPAL',
                              amount=-withdrawal,stage='AFTER_OPEN_ORDERS_SETTLED_REFUND',interest=0.))
        assert cum_withdrawals<=cum_deposits+1e-7
        # Close settlement deliberately cannot finance this day's opening buys.
        for e in by_pay.get(day,[]):
            credit=receivables.pop(e['id'],0.);cash+=credit
        for sym,bar in bars_by_date.get(day,{}).items():
            if _price(bar.get('close')):marks[sym]=float(bar['close'])
        stock=0.
        for sym in set(holdings)|set(locked):
            qty=holdings.get(sym,0)+locked.get(sym,0)
            if qty:
                value=qty*mark(sym,'close');stock+=value
                positions.append(dict(date=day,symbol=sym,shares=holdings.get(sym,0),
                    locked_shares=locked.get(sym,0),raw_close=mark(sym,'close'),value=value))
        equity=cash+sum(receivables.values())+stock
        twr=own_capital_return(previous,opening,deposit-withdrawal,equity)
        assert abs(equity-cash-sum(receivables.values())-stock)<1e-7
        daily.append(dict(date=day,equity=equity,cash=cash,stock_value=stock,
            dividend_receivable=sum(receivables.values()),opening_pre_flow_equity=opening,
            external_deposit=deposit,cumulative_deposits=cum_deposits,
            external_withdrawal=withdrawal,cumulative_withdrawals=cum_withdrawals,
            outstanding_owner_principal=cum_deposits-cum_withdrawals,
            settled_refund_allowance=settled_allowance,
            economic_profit=equity-float(initial_cash)-cum_deposits+cum_withdrawals,
            twr_daily_return=twr,fees=fees,dividend_tax=dividend_tax,turnover=turnover/(opening+deposit-withdrawal)))
        for e in by_record.get(day,[]):
            entitlements[e['id']]=holdings.get(e['symbol'],0)+locked.get(e['symbol'],0)
            if tax_book is not None:tax_book.record(e,entitlements[e['id']],day)
        if signal_factory is not None:
            # Only this already-closed account state is passed. No future bar or
            # tomorrow's equity funds today's frozen quantity calculation.
            generated=signal_factory(day,dict(daily[-1]))
            if generated is not None:
                if generated.signal_date!=day or generated.execution_date<=day:
                    raise ValueError('online target must be frozen now and execute later')
                if generated.execution_date not in calendar or generated.execution_date in schedules:
                    raise ValueError('online target outside calendar or conflicting instruction')
                if any(not isfinite(float(q)) or int(q)!=q or q<0 for q in generated.shares.values()):
                    raise ValueError('invalid online target quantity')
                schedules[generated.execution_date]=Instruction(day,generated.execution_date,generated.shares.copy())
        previous=equity
    return dict(daily=daily,orders=fills,flows=flows,blocked=blocked,
                positions=positions,actions=action_log,tax_ledger=tax_book.log if tax_book is not None else [])
