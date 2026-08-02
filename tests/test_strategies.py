"""Strategy signal logic, tested offline with a fake send socket.

Each strategy gets driven by a hand-fed price series and we assert on the orders
it produces. Several tests are regressions for specific bugs, labelled inline.
"""

from src.bots import MomentumBot, ArbitrageBot, MarketMakerBot, VWAPBot
from src.models.enums import Side
from tests.conftest import make_ack, make_fill


def attach(bot, fake_socket):
    bot.client.send_socket = fake_socket
    return bot


# --------------------------------------------------------------------------- #
# Momentum
# --------------------------------------------------------------------------- #

def test_momentum_fires_on_crossover(fake_socket):
    bot = attach(MomentumBot(client_id=1, symbols="X", short_window=3, long_window=5), fake_socket)
    for p in [100, 100, 100, 100, 100, 101, 102, 103, 104, 105]:
        bot.on_tick("X", p)
    sides = [o["side"] for o in fake_socket.orders()]
    assert "B" in sides


def test_momentum_flat_series_sends_nothing(fake_socket):
    # Regression: equal moving averages used to register as a SELL signal, so a
    # perfectly flat market opened a short out of nowhere.
    bot = attach(MomentumBot(client_id=1, symbols="X", short_window=3, long_window=5), fake_socket)
    for _ in range(10):
        bot.on_tick("X", 100)
    assert fake_socket.orders() == []


def test_momentum_flips_on_signal_reversal(fake_socket):
    # Note: this test asserts on order flow, not position, because positions only
    # move on fills and this offline socket delivers none. The downtrend should
    # produce a sell, the following uptrend a buy.
    bot = attach(MomentumBot(client_id=1, symbols="X", short_window=3, long_window=5, order_qty=10), fake_socket)
    for p in [100, 100, 100, 100, 100, 99, 98, 97, 96, 95]:  # downtrend -> sell signal
        bot.on_tick("X", p)
    assert any(o["side"] == "S" for o in fake_socket.orders())
    for p in [96, 98, 101, 105, 110, 116, 123, 131]:          # uptrend -> buy signal
        bot.on_tick("X", p)
    assert any(o["side"] == "B" for o in fake_socket.orders())


# --------------------------------------------------------------------------- #
# Arbitrage
# --------------------------------------------------------------------------- #

def test_arbitrage_enters_on_stretched_ratio(fake_socket):
    import random
    random.seed(7)
    bot = attach(ArbitrageBot(client_id=1, symbol_a="A", symbol_b="B", window=8, entry_threshold=2.0), fake_socket)
    # a little noise so the ratio has a nonzero standard deviation to measure against
    for _ in range(10):
        bot.on_tick("A", 100 + random.uniform(-1, 1)); bot.on_tick("B", 50)
    bot.on_tick("A", 130); bot.on_tick("B", 50)  # ratio spikes well outside the band
    orders = fake_socket.orders()
    assert orders, "a stretched ratio should open a two-legged trade"
    symbols = {o["symbol"] for o in orders}
    assert symbols == {"A", "B"}  # both legs traded


def test_arbitrage_samples_one_ratio_per_synced_pair(fake_socket):
    # Regression: a sample was appended on every tick of either leg, so many ticks
    # of one symbol against a stale other symbol stuffed the window with duplicate
    # ratios and collapsed the standard deviation.
    bot = attach(ArbitrageBot(client_id=1, symbol_a="A", symbol_b="B", window=5), fake_socket)
    bot.on_tick("A", 100); bot.on_tick("B", 50)
    assert len(bot.ratio_history) == 1
    for _ in range(4):
        bot.on_tick("A", 100)  # B never moves
    assert len(bot.ratio_history) == 1  # no new samples from one-sided ticks
    bot.on_tick("B", 50)
    assert len(bot.ratio_history) == 2


# --------------------------------------------------------------------------- #
# Market maker
# --------------------------------------------------------------------------- #

def test_market_maker_quotes_both_sides(fake_socket):
    bot = attach(MarketMakerBot(client_id=1, symbol="X", spread=2.0, quote_qty=10), fake_socket)
    bot.on_tick("X", 100)
    orders = fake_socket.orders()
    assert {o["side"] for o in orders} == {"B", "S"}
    bid = next(o for o in orders if o["side"] == "B")
    ask = next(o for o in orders if o["side"] == "S")
    assert bid["limit_price"] < ask["limit_price"]  # bid below ask


def test_market_maker_respects_inventory_cap(fake_socket):
    # Regression: the cap gated whether to quote but not how much, so a full-size
    # quote near the limit could be filled straight through it.
    for inventory in [0, 45, 49, 50, -45, -50]:
        fs = type(fake_socket)()
        bot = MarketMakerBot(client_id=1, symbol="X", quote_qty=10, max_inventory=50)
        bot.client.send_socket = fs
        bot.positions["X"] = inventory
        bot.on_tick("X", 100)
        bid = next((o["qty"] for o in fs.orders() if o["side"] == "B"), 0)
        ask = next((o["qty"] for o in fs.orders() if o["side"] == "S"), 0)
        assert inventory + bid <= 50   # a full bid fill can't breach the long cap
        assert inventory - ask >= -50  # a full ask fill can't breach the short cap


def test_market_maker_requotes_when_inventory_moves(fake_socket):
    # Regression: it only re-quoted on price drift, so a fill could leave stale,
    # unskewed quotes resting even though inventory (a pricing input) had changed.
    bot = attach(MarketMakerBot(client_id=1, symbol="X", quote_qty=10,
                                requote_tolerance=0.5, skew_per_unit=0.05), fake_socket)
    bot.on_tick("X", 100)
    first_bid = next(o["limit_price"] for o in fake_socket.orders() if o["side"] == "B")
    sent_before = len(fake_socket.messages)

    bot.positions["X"] = 40           # a fill moved us long
    bot.on_tick("X", 100.1)           # price barely moved, inside tolerance
    assert len(fake_socket.messages) > sent_before  # still re-quoted
    new_bid = [o["limit_price"] for o in fake_socket.orders() if o["side"] == "B"][-1]
    assert new_bid < first_bid        # quotes skewed down to shed inventory


# --------------------------------------------------------------------------- #
# VWAP
# --------------------------------------------------------------------------- #

def test_vwap_completes_indivisible_target(fake_socket):
    # Regression: floor division dropped the remainder, so a target that didn't
    # divide evenly by the slice count could never fully execute.
    for target, slices in [(100, 3), (10, 4), (7, 10)]:
        fs = type(fake_socket)()
        bot = VWAPBot(client_id=1, symbol="X", target_side=Side.BUY,
                      target_qty=target, duration_seconds=0.0, num_slices=slices)
        bot.client.send_socket = fs
        bot.start_execution()
        for _ in range(slices * 3):
            bot.on_tick("X", 50)
        assert sum(o["qty"] for o in fs.orders()) == target


def test_vwap_accounting_tracks_fills_not_sends(fake_socket):
    # Regression: executed_qty was bumped when a slice was sent, so a rejected or
    # unfilled slice was still counted as done.
    bot = attach(VWAPBot(client_id=1, symbol="X", target_side=Side.BUY,
                         target_qty=100, duration_seconds=0.0, num_slices=4), fake_socket)
    bot.start_execution()
    for _ in range(12):
        bot.on_tick("X", 200)
    assert bot.sent_qty == 100
    assert bot.executed_qty == 0        # nothing filled yet
    assert not bot.is_complete()        # sending is not executing

    orders = fake_socket.orders()
    for i, o in enumerate(orders):
        bot.client._handle_response(make_ack(o["client_order_id"], 500 + i, "X"))
    # fill only three of the four slices
    for i in range(3):
        bot.client._handle_response(make_fill(500 + i, "X", "B", 25, 200 + i))
    assert bot.executed_qty == 75
    assert bot.get_working_qty() == 25
    assert not bot.is_complete()        # honestly reports the shortfall

    bot.client._handle_response(make_fill(503, "X", "B", 25, 203))
    assert bot.executed_qty == 100
    assert bot.is_complete()


def test_vwap_ignores_wrong_side_fills(fake_socket):
    bot = attach(VWAPBot(client_id=1, symbol="X", target_side=Side.BUY,
                         target_qty=20, duration_seconds=0.0, num_slices=2), fake_socket)
    bot.start_execution()
    for _ in range(5):
        bot.on_tick("X", 50)
    bot.client._handle_response(make_fill(900, "X", "S", 10, 50))  # a stray sell
    assert bot.executed_qty == 0
    bot.client._handle_response(make_fill(901, "X", "B", 10, 50))
    assert bot.executed_qty == 10