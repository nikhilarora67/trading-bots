import math
from .base_bot import BaseBot
from ..models.enums import Side


class MeanReversionBot(BaseBot):
    """
    The principle of mean reversion is that prices tend to return to average.
    
    One method is to use the z-score of the prices and compare them (how many standard deviations from mean):
    - z-score < -entry_threshold = price too low = BUY
    - z-score > +entry_threshold = price too high = SELL
    - z-score returns to exit_threshold = close position
    """
    
    def __init__(self, client_id, symbols, window=20, entry_threshold=2.0, exit_threshold=0.5, order_qty=10, **kwargs):
        super().__init__(client_id, symbols, **kwargs)
        
        self.window = window
        self.entry_threshold = entry_threshold  # Standard deviations to enter
        self.exit_threshold = exit_threshold    # Standard deviations to exit
        self.order_qty = order_qty
        
        # Price history
        self.price_history = {symbol: [] for symbol in self.symbols}
    
    
    def on_tick(self, symbol, price, timestamp=None):
        """Process new price and trade based on z-score."""
        
        if symbol not in self.symbols:
            return
        
        # Add to history
        self.price_history[symbol].append(price)
        
        if len(self.price_history[symbol]) > self.window + 10:
            self.price_history[symbol].pop(0)
        
        # Need full window
        if len(self.price_history[symbol]) < self.window:
            return
        
        # Calculate mean and standard deviation
        prices = self.price_history[symbol][-self.window:]
        mean = sum(prices) / len(prices)
        variance = sum((p - mean) ** 2 for p in prices) / len(prices)
        std = math.sqrt(variance)
        
        if std == 0:
            return
        
        # Z-score: how many standard deviations from mean
        z_score = (price - mean) / std
        
        pos = self.get_position(symbol)
        
        # Entry signals (only if flat)
        if pos == 0:
            if z_score < -self.entry_threshold:
                # Price way below average - buy expecting reversion up
                self.buy(symbol, self.order_qty, price)
                print(f"[MEAN REV] {symbol} ENTER LONG | z-score: {z_score:.2f}")
                
            elif z_score > self.entry_threshold:
                # Price way above average - sell expecting reversion down
                self.sell(symbol, self.order_qty, price)
                print(f"[MEAN REV] {symbol} ENTER SHORT | z-score: {z_score:.2f}")
        
        # Exit signals (if we have a position)
        elif pos > 0:  # Long position
            if z_score > -self.exit_threshold:
                # Price reverted back toward mean - take profit
                self.sell(symbol, pos, price)
                print(f"[MEAN REV] {symbol} EXIT LONG | z-score: {z_score:.2f}")
        
        elif pos < 0:  # Short position
            if z_score < self.exit_threshold:
                # Price reverted back toward mean - take profit
                self.buy(symbol, abs(pos), price)
                print(f"[MEAN REV] {symbol} EXIT SHORT | z-score: {z_score:.2f}")