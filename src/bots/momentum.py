from .base_bot import BaseBot
from ..models.enums import Side


class MomentumBot(BaseBot):
    """
    The Momentum bot uses two moving averages:
    - Short window (fast) - recent price trend
    - Long window (slow) - overall price trend
    
    When the short window crosses above the long window, that 
    signals an uptrend, which leads to a buy order 
    
    When the short window crosses below the long window, that 
    signals an downtrend, which leads to a sell order 
    """
    
    def __init__(self, client_id, symbols, short_window=5, long_window=20, order_qty=10, **kwargs):
        super().__init__(client_id, symbols, **kwargs)
        
        self.short_window = short_window
        self.long_window = long_window
        self.order_qty = order_qty
        
        # Price history for each symbol
        self.price_history = {symbol: [] for symbol in self.symbols}
        
        # Track last signal to avoid repeated orders
        self.last_signal = {symbol: None for symbol in self.symbols}
    
    
    def on_tick(self, symbol, price, timestamp=None):
        """Process new price data and trade if signal changes."""
        
        if symbol not in self.symbols:
            return
        
        # Add to history
        self.price_history[symbol].append(price)
        
        # Keep only what we need
        max_history = self.long_window + 10  # Small buffer
        if len(self.price_history[symbol]) > max_history:
            self.price_history[symbol].pop(0)
        
        # Need enough data for long average
        if len(self.price_history[symbol]) < self.long_window:
            return
        
        # Calculate moving averages
        prices = self.price_history[symbol]
        short_avg = sum(prices[-self.short_window:]) / self.short_window
        long_avg = sum(prices[-self.long_window:]) / self.long_window
        
        # Determine signal
        if short_avg > long_avg:
            signal = "BUY"
        else:
            signal = "SELL"
        
        # Only trade when signal changes
        if signal == self.last_signal[symbol]:
            return
        
        # Execute trade
        pos = self.get_position(symbol)
        
        if signal == "BUY":
            # Close short if we have one
            if pos < 0:
                self.buy(symbol, abs(pos), price)
            # Open long
            self.buy(symbol, self.order_qty, price)
            
        elif signal == "SELL":
            # Close long if we have one
            if pos > 0:
                self.sell(symbol, pos, price)
            # Open short
            self.sell(symbol, self.order_qty, price)
        
        self.last_signal[symbol] = signal
        print(f"[MOMENTUM] {symbol} signal: {signal} | Short avg: {short_avg:.2f} | Long avg: {long_avg:.2f}")