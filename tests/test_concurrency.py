"""Concurrency stress test for ExchangeClient.

This is the test that proves the locking works. It runs the client against a real
ZeroMQ fake exchange and fires a large volume of orders from several threads at
once, with cancels deliberately racing the fills, while another thread reads the
shared state the whole time. If the two locks or the register-before-send ordering
were wrong, this is where it would show up: duplicate order ids, leaked tracking
entries, wrong final position, or a crash in the reader thread.
"""

import contextlib
import io
import threading

from src.bots.base_bot import BaseBot
from tests.conftest import wait_until


class PassiveBot(BaseBot):
    """A bot that never trades on ticks, so the test controls all order flow."""
    def on_tick(self, symbol, price, timestamp=None):
        pass


def test_concurrent_orders_and_cancels(exchange):
    n_threads = 4
    orders_per_thread = 250
    total_orders = n_threads * orders_per_thread

    bot = PassiveBot(client_id=1, symbols=["AAPL"],
                     send_port=exchange.send_port, recv_port=exchange.recv_port)

    fills_seen = []
    original_on_fill = bot.client.on_fill
    def counting_on_fill(*args):
        fills_seen.append(args)
        original_on_fill(*args)
    bot.client.on_fill = counting_on_fill

    reader_errors = []
    stop_reader = threading.Event()
    def reader():
        # hammer the query methods so a torn read of shared state would surface
        while not stop_reader.is_set():
            try:
                bot.client.get_pending_orders()
                bot.get_position("AAPL")
            except Exception as e:  # pragma: no cover - the assertion is that this stays empty
                reader_errors.append(e)

    def sender(worker_id):
        for k in range(orders_per_thread):
            if (worker_id + k) % 2 == 0:
                order_id = bot.buy("AAPL", 1, 100)
            else:
                order_id = bot.sell("AAPL", 1, 100)
            if k % 5 == 0:  # ~20% of orders get cancelled, racing their own fills
                bot.cancel("AAPL", client_order_id=order_id)

    # silence the bots' own prints so pytest output stays readable
    with contextlib.redirect_stdout(io.StringIO()):
        bot.start()
        reader_thread = threading.Thread(target=reader, daemon=True)
        reader_thread.start()

        senders = [threading.Thread(target=sender, args=(i,)) for i in range(n_threads)]
        for t in senders:
            t.start()
        for t in senders:
            t.join()

        wait_until(lambda: len(fills_seen) >= total_orders, timeout=25)

        stop_reader.set()
        reader_thread.join(timeout=2)

        final_position = bot.get_position("AAPL")
        pending, forward_map, reverse_map = (
            len(bot.client._pending_orders),
            len(bot.client._order_id_map),
            len(bot.client._exchange_id_map),
        )
        next_id = bot.client._next_order_id
        bot.stop()

    # every order got a unique, gapless id -> the counter never lost an update
    assert next_id == total_orders + 1
    # every order came back as a fill -> nothing was dropped
    assert len(fills_seen) == total_orders
    # 500 buys and 500 sells of size 1 -> net flat
    assert final_position == 0
    # no tracking left behind -> cancels and fills cleaned up under every interleaving
    assert (pending, forward_map, reverse_map) == (0, 0, 0)
    # reads never saw a half-updated structure
    assert reader_errors == []