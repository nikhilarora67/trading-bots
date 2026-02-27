import time
from .base_bot import BaseBot
from ..models.enums import Side


class VWAPBot(BaseBot):
    """
    VWAP execution algorithm.
    
    Not a trading strategy - it's an execution strategy.
    Takes a large order and splits it into smaller slices over time.
    Goal: achieve average fill price close to VWAP (Volume Weighted Average Price).
    
    Used when you need to buy/sell a lot without moving the market.
    """
    
    def __init__(self, client_id, symbol, target_side, target_qty, duration_seconds, num_slices=10, **kwargs):
        super().__init__(client_id, [symbol], **kwargs)
        
        self.symbol = symbol
        self.target_side = target_side      # Side.BUY or Side.SELL
        self.target_qty = target_qty        # Total quantity to execute
        self.duration_seconds = duration_seconds
        self.num_slices = num_slices
        
        # Calculate slice details
        self.slice_qty = target_qty // num_slices
        self.slice_interval = duration_seconds / num_slices
        
        # Track execution progress
        self.executed_qty = 0
        self.slices_sent = 0
        self.total_cost = 0.0  # For calculating average price
        
        # Timing
        self.start_time = None
        self.last_slice_time = None
        
        # Store prices for VWAP calculation
        self.tick_prices = []
        self.tick_volumes = []
    
    
    def start_execution(self):
        """Call this to begin VWAP execution."""
        self.start_time = time.time()
        self.last_slice_time = self.start_time
        print(f"[VWAP] Starting: {self.target_side.name} {self.target_qty} {self.symbol}")
        print(f"[VWAP] Plan: {self.num_slices} slices of {self.slice_qty} over {self.duration_seconds}s")
    
    
    def on_tick(self, symbol, price, timestamp=None, volume=None):
        """Process tick and send slice if it's time."""
        
        if symbol != self.symbol:
            return
        
        if self.start_time is None:
            return  # Execution not started yet
        
        # Track for VWAP calculation
        self.tick_prices.append(price)
        if volume:
            self.tick_volumes.append(volume)
        
        # Check if we're done
        if self.executed_qty >= self.target_qty:
            return
        
        # Check if it's time for next slice
        current_time = time.time()
        time_since_last = current_time - self.last_slice_time
        
        if time_since_last >= self.slice_interval and self.slices_sent < self.num_slices:
            self._send_slice(price)
    
    
    def _send_slice(self, price):
        """Send one slice of the order."""
        
        # Last slice gets remaining quantity
        remaining = self.target_qty - self.executed_qty
        qty = min(self.slice_qty, remaining)
        
        if qty <= 0:
            return
        
        # Send order
        if self.target_side == Side.BUY:
            self.buy(self.symbol, qty, price)
        else:
            self.sell(self.symbol, qty, price)
        
        # Track progress
        self.executed_qty += qty
        self.total_cost += qty * price
        self.slices_sent += 1
        self.last_slice_time = time.time()
        
        avg_price = self.total_cost / self.executed_qty if self.executed_qty > 0 else 0
        print(f"[VWAP] Slice {self.slices_sent}/{self.num_slices} | {self.executed_qty}/{self.target_qty} done | Avg price: {avg_price:.2f}")
    
    
    def get_market_vwap(self):
        """Calculate VWAP from observed ticks (for comparison)."""
        if not self.tick_prices:
            return 0.0
        
        if self.tick_volumes and len(self.tick_volumes) == len(self.tick_prices):
            # Proper VWAP with volume
            total_value = sum(p * v for p, v in zip(self.tick_prices, self.tick_volumes))
            total_volume = sum(self.tick_volumes)
            return total_value / total_volume if total_volume > 0 else 0.0
        else:
            # Simple average if no volume
            return sum(self.tick_prices) / len(self.tick_prices)
    
    
    def get_execution_avg_price(self):
        """Get our average execution price."""
        if self.executed_qty == 0:
            return 0.0
        return self.total_cost / self.executed_qty
    
    
    def get_slippage(self):
        """Compare our execution to market VWAP."""
        our_price = self.get_execution_avg_price()
        market_vwap = self.get_market_vwap()
        
        if market_vwap == 0:
            return 0.0
        
        # For BUY: negative slippage is good (we paid less than VWAP)
        # For SELL: positive slippage is good (we got more than VWAP)
        if self.target_side == Side.BUY:
            return our_price - market_vwap
        else:
            return market_vwap - our_price
    
    
    def is_complete(self):
        """Check if execution is finished."""
        return self.executed_qty >= self.target_qty