import time
from .base_bot import BaseBot
from ..models.enums import Side


class VWAPBot(BaseBot):
    """Execution algo rather than a signal strategy. Splits a large parent
    order into equal slices sent over a fixed duration, then compares the
    average fill price against the market VWAP observed over the same
    window."""

    def __init__(self, client_id, symbol, target_side, target_qty, duration_seconds, num_slices=10, **kwargs):
        super().__init__(client_id, [symbol], **kwargs)
        self.symbol = symbol
        self.target_side = target_side
        self.target_qty = target_qty
        self.duration_seconds = duration_seconds
        self.num_slices = num_slices

        self.slice_qty = target_qty // num_slices
        self.slice_interval = duration_seconds / num_slices

        self.executed_qty = 0
        self.slices_sent = 0
        self.total_cost = 0.0

        self.start_time = None
        self.last_slice_time = None

        self.tick_prices = []
        self.tick_volumes = []

    def start_execution(self):
        self.start_time = time.time()
        self.last_slice_time = self.start_time
        print(f"[VWAP] {self.target_side.name} {self.target_qty} {self.symbol}: "
              f"{self.num_slices} slices of {self.slice_qty} over {self.duration_seconds}s")

    def on_tick(self, symbol, price, timestamp=None, volume=None):
        if symbol != self.symbol or self.start_time is None:
            return

        self.tick_prices.append(price)
        if volume:
            self.tick_volumes.append(volume)

        if self.executed_qty >= self.target_qty:
            return

        elapsed = time.time() - self.last_slice_time
        if elapsed >= self.slice_interval and self.slices_sent < self.num_slices:
            self._send_slice(price)

    def _send_slice(self, price):
        qty = min(self.slice_qty, self.target_qty - self.executed_qty)
        if qty <= 0:
            return

        if self.target_side == Side.BUY:
            self.buy(self.symbol, qty, price)
        else:
            self.sell(self.symbol, qty, price)

        self.executed_qty += qty
        self.total_cost += qty * price
        self.slices_sent += 1
        self.last_slice_time = time.time()
        print(f"[VWAP] slice {self.slices_sent}/{self.num_slices} | "
              f"{self.executed_qty}/{self.target_qty} filled | avg {self.get_execution_avg_price():.2f}")

    def get_market_vwap(self):
        if not self.tick_prices:
            return 0.0
        if self.tick_volumes and len(self.tick_volumes) == len(self.tick_prices):
            total_volume = sum(self.tick_volumes)
            if total_volume == 0:
                return 0.0
            return sum(p * v for p, v in zip(self.tick_prices, self.tick_volumes)) / total_volume
        # fall back to a simple average when no volume data comes through
        return sum(self.tick_prices) / len(self.tick_prices)

    def get_execution_avg_price(self):
        if self.executed_qty == 0:
            return 0.0
        return self.total_cost / self.executed_qty

    def get_slippage(self):
        """Positive means we did worse than market VWAP."""
        market_vwap = self.get_market_vwap()
        if market_vwap == 0:
            return 0.0
        if self.target_side == Side.BUY:
            return self.get_execution_avg_price() - market_vwap
        return market_vwap - self.get_execution_avg_price()

    def is_complete(self):
        return self.executed_qty >= self.target_qty
