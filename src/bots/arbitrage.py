import math
from .base_bot import BaseBot
from ..models.enums import Side


class ArbitrageBot(BaseBot):
    """
    Pairs arbitrage strategy.
    
    Trades two correlated symbols (e.g., AAPL and MSFT).
    When their price ratio diverges from historical mean, bet on convergence:
    - Ratio too high = symbol_a overpriced = short A, long B
    - Ratio too low = symbol_a underpriced = long A, short B
    """
    
    def __init__(self, client_id, symbol_a, symbol_b, window=20, entry_threshold=2.0, exit_threshold=0.5, order_qty=10, **kwargs):
        super().__init__(client_id, [symbol_a, symbol_b], **kwargs)
        
        self.symbol_a = symbol_a
        self.symbol_b = symbol_b
        self.window = window
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.order_qty = order_qty
        
        # Current prices
        self.prices = {symbol_a: None, symbol_b: None}
        
        # Ratio history (price_a / price_b)
        self.ratio_history = []
        
        # Track if we're in a trade
        self.in_trade = False
        self.trade_direction = None  # "long_ratio" or "short_ratio"
    
    
    def on_tick(self, symbol, price, timestamp=None):
        """Update price and check for arbitrage opportunity."""
        
        if symbol not in [self.symbol_a, self.symbol_b]:
            return
        
        self.prices[symbol] = price
        
        # Need both prices
        if self.prices[self.symbol_a] is None or self.prices[self.symbol_b] is None:
            return
        
        if self.prices[self.symbol_b] == 0:
            return
        
        # Calculate ratio
        ratio = self.prices[self.symbol_a] / self.prices[self.symbol_b]
        self.ratio_history.append(ratio)
        
        if len(self.ratio_history) > self.window + 10:
            self.ratio_history.pop(0)
        
        # Need full window
        if len(self.ratio_history) < self.window:
            return
        
        # Calculate z-score of ratio
        ratios = self.ratio_history[-self.window:]
        mean = sum(ratios) / len(ratios)
        variance = sum((r - mean) ** 2 for r in ratios) / len(ratios)
        std = math.sqrt(variance)
        
        if std == 0:
            return
        
        z_score = (ratio - mean) / std
        
        # Entry signals
        if not self.in_trade:
            if z_score > self.entry_threshold:
                # Ratio too high: A overpriced relative to B
                # Short A, Long B - bet ratio will decrease
                self.sell(self.symbol_a, self.order_qty, self.prices[self.symbol_a])
                self.buy(self.symbol_b, self.order_qty, self.prices[self.symbol_b])
                self.in_trade = True
                self.trade_direction = "short_ratio"
                print(f"[ARBITRAGE] ENTER: Short {self.symbol_a}, Long {self.symbol_b} | z-score: {z_score:.2f}")
                
            elif z_score < -self.entry_threshold:
                # Ratio too low: A underpriced relative to B
                # Long A, Short B - bet ratio will increase
                self.buy(self.symbol_a, self.order_qty, self.prices[self.symbol_a])
                self.sell(self.symbol_b, self.order_qty, self.prices[self.symbol_b])
                self.in_trade = True
                self.trade_direction = "long_ratio"
                print(f"[ARBITRAGE] ENTER: Long {self.symbol_a}, Short {self.symbol_b} | z-score: {z_score:.2f}")
        
        # Exit signals
        elif self.in_trade:
            should_exit = False
            
            if self.trade_direction == "short_ratio" and z_score < self.exit_threshold:
                should_exit = True
            elif self.trade_direction == "long_ratio" and z_score > -self.exit_threshold:
                should_exit = True
            
            if should_exit:
                # Close both positions
                pos_a = self.get_position(self.symbol_a)
                pos_b = self.get_position(self.symbol_b)
                
                if pos_a > 0:
                    self.sell(self.symbol_a, pos_a, self.prices[self.symbol_a])
                elif pos_a < 0:
                    self.buy(self.symbol_a, abs(pos_a), self.prices[self.symbol_a])
                
                if pos_b > 0:
                    self.sell(self.symbol_b, pos_b, self.prices[self.symbol_b])
                elif pos_b < 0:
                    self.buy(self.symbol_b, abs(pos_b), self.prices[self.symbol_b])
                
                self.in_trade = False
                self.trade_direction = None
                print(f"[ARBITRAGE] EXIT | z-score: {z_score:.2f}")