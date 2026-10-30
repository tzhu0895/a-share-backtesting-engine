import unittest
from physical_engine import Instruction, replay


def data(days=6,price=10.,symbol='SH600001'):
    return {(d,symbol):dict(open=price,close=price,buy_allowed=True,sell_allowed=True)
            for d in range(1,days+1)}


def free(*args):return 0.


class PhysicalTests(unittest.TestCase):
    def test_buy_is_t_plus_one(self):
        with self.assertRaises(ValueError):
            replay([1,2],data(2),[Instruction(1,1,{'SH600001':100})],free)

    def test_missing_open_flags_fail_closed(self):
        bars=data(2);bars[(2,'SH600001')].pop('buy_allowed')
        r=replay([1,2],bars,[Instruction(1,2,{'SH600001':100})],free)
        self.assertFalse(r['orders']);self.assertEqual(len(r['blocked']),1)

    def test_blocked_order_retries(self):
        bars=data(3);bars[(2,'SH600001')]['buy_allowed']=False
        r=replay([1,2,3],bars,[Instruction(1,2,{'SH600001':100})],free)
        self.assertEqual(r['orders'][0]['date'],3)

    def test_missing_bar_retries_without_fake_fill(self):
        bars=data(3);del bars[(2,'SH600001')]
        r=replay([1,2,3],bars,[Instruction(1,2,{'SH600001':100})],free)
        self.assertEqual([x['date'] for x in r['orders']],[3])

    def test_new_instruction_supersedes_blocked_order(self):
        bars=data(3);bars[(2,'SH600001')]['buy_allowed']=False
        r=replay([1,2,3],bars,[Instruction(1,2,{'SH600001':100}),Instruction(2,3,{})],free)
        self.assertFalse(r['orders'])

    def test_deposit_not_profit(self):
        r=replay([1,2],data(2),[Instruction(1,2,{'SH600001':15000})],free)
        self.assertAlmostEqual(r['daily'][-1]['external_deposit'],50000)
        self.assertAlmostEqual(r['daily'][-1]['economic_profit'],0)
        self.assertAlmostEqual(r['daily'][-1]['twr_daily_return'],0)

    def test_cash_funding_disabled(self):
        r=replay([1,2],data(2),[Instruction(1,2,{'SH600001':15000})],free,external_funding=False)
        self.assertFalse(r['orders']);self.assertFalse(r['flows'])

    def test_sell_next_day(self):
        r=replay([1,2,3],data(3),[Instruction(1,2,{'SH600001':100}),Instruction(2,3,{})],free)
        self.assertEqual([x['side'] for x in r['orders']],['BUY','SELL'])
        self.assertTrue(all(x['date']>x['signal_date'] for x in r['orders']))

    def test_cannot_sell_nonexistent_holding(self):
        r=replay([1,2],data(2),[Instruction(1,2,{})],free)
        self.assertFalse(r['orders'])

    def test_star_minimum(self):
        r=replay([1,2],data(2,symbol='SH688001'),[Instruction(1,2,{'SH688001':199})],free)
        self.assertFalse(r['orders'])

    def test_noninteger_target_rejected(self):
        with self.assertRaises(ValueError):
            replay([1,2],data(2),[Instruction(1,2,{'SH600001':100.2})],free)

    def test_slippage_and_fee_are_real_costs(self):
        r=replay([1,2],data(2),[Instruction(1,2,{'SH600001':100})],lambda *a:5.,slippage_bps=10)
        self.assertAlmostEqual(r['daily'][-1]['economic_profit'],-6.)

    def test_no_fake_cash_yield_or_alpha(self):
        r=replay([1,2,3],data(3),[],free)
        self.assertTrue(all(x['equity']==100000. for x in r['daily']))

    def test_dividend_receivable_separate_from_cash(self):
        bars=data();bars.update({(d,'SH600001'):dict(open=9.,close=9.,buy_allowed=True,sell_allowed=True) for d in (4,5,6)})
        action=dict(symbol='SH600001',record_date=3,ex_date=4,cash=1.,bonus=0.,pay_date=5)
        r=replay(list(range(1,7)),bars,[Instruction(1,2,{'SH600001':100})],free,actions=[action])
        self.assertEqual(r['daily'][3]['dividend_receivable'],100.)
        self.assertEqual(r['daily'][3]['cash'],99000.)
        self.assertEqual(r['daily'][4]['dividend_receivable'],0.)
        self.assertEqual(r['daily'][4]['cash'],99100.)
        self.assertTrue(all(abs(x['equity']-100000)<1e-7 for x in r['daily']))

    def test_unlisted_bonus_cannot_be_sold(self):
        bars=data();bars.update({(d,'SH600001'):dict(open=5.,close=5.,buy_allowed=True,sell_allowed=True) for d in (4,5,6)})
        action=dict(symbol='SH600001',record_date=3,ex_date=4,cash=0.,bonus=1.,pay_date=None,bonus_listing_date=5)
        r=replay(list(range(1,7)),bars,[Instruction(1,2,{'SH600001':100}),Instruction(3,4,{})],free,actions=[action])
        sales=[x for x in r['orders'] if x['side']=='SELL']
        self.assertEqual([(x['date'],x['shares']) for x in sales],[(4,100),(5,100)])
        self.assertTrue(all(abs(x['equity']-100000)<1e-7 for x in r['daily']))

    def test_unverified_payment_date_rejected(self):
        action=dict(symbol='SH600001',record_date=1,ex_date=2,cash=1.)
        with self.assertRaises(ValueError):
            replay([1,2],data(2),[],free,actions=[action])

    def test_bonus_does_not_cause_spurious_target_sale(self):
        bars=data();bars.update({(d,'SH600001'):dict(open=5.,close=5.,buy_allowed=True,sell_allowed=True) for d in (4,5,6)})
        action=dict(symbol='SH600001',record_date=3,ex_date=4,cash=0.,bonus=1.,pay_date=None,bonus_listing_date=5)
        instruction=Instruction(1,2,{'SH600001':100})
        r=replay(list(range(1,7)),bars,[instruction],free,actions=[action])
        self.assertEqual(len(r['orders']),1)
        self.assertEqual(r['positions'][-1]['shares'],200)
        self.assertEqual(instruction.shares['SH600001'],100)

    def test_future_price_suffix_does_not_change_prefix(self):
        bars=data(5);schedule=[Instruction(1,2,{'SH600001':100})]
        a=replay([1,2,3,4,5],bars,schedule,free)
        bars[(5,'SH600001')]['close']=1000.
        b=replay([1,2,3,4,5],bars,schedule,free)
        self.assertEqual(a['daily'][:4],b['daily'][:4])
        self.assertEqual(a['orders'],b['orders'])

    def test_unsupported_action_requires_zero_entitlement(self):
        action=dict(symbol='SH600001',record_date=3,ex_date=4,unsupported_if_held=True)
        r=replay(list(range(1,7)),data(),[],free,actions=[action])
        self.assertTrue(r['actions'][0]['unsupported_action_zero_ownership_asserted'])
        with self.assertRaises(ValueError):
            replay(list(range(1,7)),data(),[Instruction(1,2,{'SH600001':100})],free,actions=[action])

    def test_unknown_record_date_cannot_assume_zero_after_prior_holding(self):
        action=dict(symbol='SH600001',record_date=None,ex_date=4,unsupported_if_held=True)
        with self.assertRaises(ValueError):
            replay(list(range(1,7)),data(),[Instruction(1,2,{'SH600001':100}),Instruction(2,3,{})],free,actions=[action])

    def test_known_zero_record_ownership_after_old_holding_is_checked(self):
        action=dict(symbol='SH600001',record_date=4,ex_date=5,unsupported_if_held=True)
        r=replay(list(range(1,7)),data(),[Instruction(1,2,{'SH600001':100}),Instruction(2,3,{})],free,actions=[action])
        self.assertTrue(r['actions'][0]['unsupported_action_zero_ownership_asserted'])

    def test_unsupported_action_cannot_affect_new_pending_position(self):
        action=dict(symbol='SH600001',record_date=3,ex_date=4,unsupported_if_held=True)
        with self.assertRaises(ValueError):
            replay(list(range(1,7)),data(),[Instruction(3,4,{'SH600001':100})],free,actions=[action])

    def test_differential_dividend_cash_and_reference_are_distinct(self):
        bars=data();bars[(4,'SH600001')].update(open=None,close=None,buy_allowed=False,sell_allowed=False)
        for d in (5,6):bars[(d,'SH600001')].update(open=9.5,close=9.5)
        action=dict(symbol='SH600001',record_date=3,ex_date=4,cash=.6,reference_cash=.5,bonus=0.,pay_date=5)
        r=replay(list(range(1,7)),bars,[Instruction(1,2,{'SH600001':100})],free,actions=[action])
        self.assertAlmostEqual(r['daily'][3]['equity'],100010)
        self.assertAlmostEqual(r['daily'][3]['dividend_receivable'],60)

    def test_capacity_partials_retry_without_overfill(self):
        bars=data(4)
        for bar in bars.values():bar['max_buy_qty']=200
        r=replay([1,2,3,4],bars,[Instruction(1,2,{'SH600001':500})],free)
        self.assertEqual([o['shares'] for o in r['orders']],[200,200,100])
        self.assertEqual(r['positions'][-1]['shares'],500)


if __name__=='__main__':unittest.main(verbosity=2)
