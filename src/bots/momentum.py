from .base_bot import BaseBot


class MomentumBot(BaseBot):
    """Moving average crossover. Fast MA above slow MA means uptrend, go long.
    Fast below slow means downtrend, go short. Only trades when the signal
    flips so it doesn't spam orders every tick."""

    def __init__(self, client_id, symbols, short_window=5, long_window=20, order_qty=10, **kwargs):
        super().__init__(client_id, symbols, **kwargs)
        self.short_window = short_window
        self.long_window = long_window
        self.order_qty = order_qty
        self.price_history = {symbol: [] for symbol in self.symbols}
        self.last_signal = {symbol: None for symbol in self.symbols}

    def on_tick(self, symbol, price, timestamp=None):
        if symbol not in self.symbols:
            return

        history = self.price_history[symbol]
        history.append(price)
        if len(history) > self.long_window + 10:
            history.pop(0)

        if len(history) < self.long_window:
            return

        short_avg = sum(history[-self.short_window:]) / self.short_window
        long_avg = sum(history[-self.long_window:]) / self.long_window
        signal = "BUY" if short_avg > long_avg else "SELL"

        if signal == self.last_signal[symbol]:
            return

        pos = self.get_position(symbol)
        if signal == "BUY":
            if pos < 0:
                self.buy(symbol, abs(pos), price)  # cover the short first
            self.buy(symbol, self.order_qty, price)
        else:
            if pos > 0:
                self.sell(symbol, pos, price)  # close the long first
            self.sell(symbol, self.order_qty, price)

        self.last_signal[symbol] = signal
        print(f"[MOMENTUM] {symbol} {signal} | fast {short_avg:.2f} vs slow {long_avg:.2f}")
