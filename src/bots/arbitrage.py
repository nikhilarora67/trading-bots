import math
from .base_bot import BaseBot


class ArbitrageBot(BaseBot):
    """Pairs trade on two correlated symbols. Tracks the price ratio A/B and
    bets on it reverting when its z-score gets stretched: short A / long B
    when the ratio is rich, long A / short B when it's cheap."""

    def __init__(self, client_id, symbol_a, symbol_b, window=20, entry_threshold=2.0, exit_threshold=0.5, order_qty=10, **kwargs):
        super().__init__(client_id, [symbol_a, symbol_b], **kwargs)
        self.symbol_a = symbol_a
        self.symbol_b = symbol_b
        self.window = window
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.order_qty = order_qty

        self.prices = {symbol_a: None, symbol_b: None}
        self.ratio_history = []
        self.in_trade = False
        self.trade_direction = None  # "long_ratio" or "short_ratio"

    def on_tick(self, symbol, price, timestamp=None):
        if symbol not in self.prices:
            return

        self.prices[symbol] = price
        price_a = self.prices[self.symbol_a]
        price_b = self.prices[self.symbol_b]
        if price_a is None or price_b is None or price_b == 0:
            return

        ratio = price_a / price_b
        self.ratio_history.append(ratio)
        if len(self.ratio_history) > self.window + 10:
            self.ratio_history.pop(0)

        if len(self.ratio_history) < self.window:
            return

        window = self.ratio_history[-self.window:]
        mean = sum(window) / len(window)
        variance = sum((r - mean) ** 2 for r in window) / len(window)
        std = math.sqrt(variance)
        if std == 0:
            return

        z = (ratio - mean) / std

        if not self.in_trade:
            if z > self.entry_threshold:
                self.sell(self.symbol_a, self.order_qty, price_a)
                self.buy(self.symbol_b, self.order_qty, price_b)
                self.in_trade = True
                self.trade_direction = "short_ratio"
                print(f"[ARB] enter: short {self.symbol_a} / long {self.symbol_b} | z={z:.2f}")
            elif z < -self.entry_threshold:
                self.buy(self.symbol_a, self.order_qty, price_a)
                self.sell(self.symbol_b, self.order_qty, price_b)
                self.in_trade = True
                self.trade_direction = "long_ratio"
                print(f"[ARB] enter: long {self.symbol_a} / short {self.symbol_b} | z={z:.2f}")
            return

        reverted = (self.trade_direction == "short_ratio" and z < self.exit_threshold) or \
                   (self.trade_direction == "long_ratio" and z > -self.exit_threshold)
        if reverted:
            self._close_out()
            print(f"[ARB] exit | z={z:.2f}")

    def _close_out(self):
        for symbol in (self.symbol_a, self.symbol_b):
            pos = self.get_position(symbol)
            if pos > 0:
                self.sell(symbol, pos, self.prices[symbol])
            elif pos < 0:
                self.buy(symbol, abs(pos), self.prices[symbol])
        self.in_trade = False
        self.trade_direction = None
