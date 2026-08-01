# trading-bots

Python trading bots for a C++ matching exchange two friends of mine built. The
two projects talk over ZeroMQ using a small JSON protocol, and everything on
this side is built around one base class that owns the connection and position
tracking so each strategy file only has to worry about its signal logic.

## How it talks to the exchange

Two sockets: a PUSH socket on port 5555 carries orders and cancels out, and a
PULL socket on 5556 brings acks, rejects, and fills back. Every message is a
JSON envelope with a header (protocol version, message type, sequence number,
client id) and a typed body. The enum values in `src/models/enums.py` mirror
the exchange's `types.hpp`, so the integers have to match on both sides or
nothing parses.

Receiving happens on a background listener thread. When a fill arrives, the
client updates its order tracking and hands the fill up to the bot through a
callback. That callback is why positions reflect what actually executed rather
than what was optimistically sent.

## The bots

All four subclass `BaseBot` and implement `on_tick(symbol, price)`:

- `MomentumBot` keeps a fast and a slow moving average and trades when they
  cross, but only when the signal actually flips so it doesn't fire every tick
- `ArbitrageBot` computes a z-score on the price ratio of two symbols, enters
  when the ratio stretches past a threshold, and legs into both sides of the
  pair betting on convergence
- `MarketMakerBot` quotes a bid and an ask around the last price and tries to
  earn the spread, skewing both quotes against its inventory so fills push it
  back toward flat. The only bot whose orders rest, so the only one that
  cancels and reacts to its own fills
- `VWAPBot` is an execution algo, not a signal. It slices a parent order over
  a time window and grades itself against the VWAP it observed while working

## Running it

Start the exchange first, then:

```
pip install -r requirements.txt
```

```python
from src.bots import MomentumBot

bot = MomentumBot(client_id=1, symbols=["AAPL"], short_window=5, long_window=20)
bot.start()

# feed ticks from wherever your market data comes from
bot.on_tick("AAPL", 187.32)

bot.stop()
```

There's deliberately no market data feed in here. `on_tick` gets called by
whatever is driving the bot, which keeps the strategies testable with nothing
but a price list.

A new strategy is a subclass and one method:

```python
from src.bots import BaseBot

class DipBuyer(BaseBot):
    def on_tick(self, symbol, price, timestamp=None):
        if price < 100 and self.get_position(symbol) == 0:
            self.buy(symbol, 10, price)
```

## Design notes

A few decisions in `exchange_client.py` that took actual debugging to get
right.

Orders are registered in the pending map before they hit the wire. On a fast
exchange a fill can come back on the listener thread before `send_string()`
has even returned, and if the order isn't registered yet, that fill's cleanup
silently does nothing.

The fill callback runs outside the state lock. A fill handler is allowed to
turn around and send an order, which needs the lock again, and holding a
non-reentrant lock through the callback would deadlock. Socket writes have
their own separate lock because ZeroMQ sockets aren't thread-safe and sends
can now come from two threads.

Cancels clean up tracking immediately instead of waiting for a confirmation
the protocol doesn't have. If a cancel loses the race and the order fills
anyway, the fill callback still fires so positions stay correct, and an ack
arriving after a local cancel gets ignored so the id maps can't leak entries.

Both sockets set `LINGER=0`. Without it, shutdown blocks forever trying to
flush queued messages to an exchange that already went away.

## What it doesn't do

Positions update on confirmed fills, so between sending an order and its fill
there's a window where `get_position` is stale. The strategies live with that;
a production system would track pending exposure alongside confirmed
positions. There's also no persistence, no reconnect logic, and limit prices
are just the last tick, so treat the strategies as signal demos rather than
anything you'd point at real money.

## Layout

```
src/
  connection/   ExchangeClient: sockets, listener thread, order tracking
  models/       message dataclasses and the enums shared with the exchange
  bots/         BaseBot plus the four strategies
```
