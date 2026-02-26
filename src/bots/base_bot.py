from abc import ABC, abstractmethod
from ..models.enums import Side
from ..connection.exchange_client import ExchangeClient


class BaseBot(ABC):
    """
    Base class for all trading bots.
    Handles connection, position tracking, and orders.
    
    Subclasses must implement:
        on_tick(symbol, price, timestamp) - Called when market data arrives
    """
    
    def __init__(self, client_id, symbols, host="localhost", send_port=5555, recv_port=5556):
        self.client_id = client_id
        self.symbols = symbols if isinstance(symbols, list) else [symbols]
        
        # Exchange connection
        self.client = ExchangeClient(
            client_id=client_id,
            host=host,
            send_port=send_port,
            recv_port=recv_port
        )
        
        # Position tracking
        # Positive = long, negative = short, zero = flat
        self.positions = {symbol: 0 for symbol in self.symbols}
        self.avg_cost = {symbol: 0.0 for symbol in self.symbols}
        self.realized_pnl = 0.0
        
        self._running = False
    
    
    # ==================== Connection ====================
    
    def start(self):
        """Connect to exchange and start listening for responses."""
        self.client.connect()
        self.client.start_listening()
        self._running = True
        print(f"[BOT {self.client_id}] Started | Symbols: {self.symbols}")
    
    
    def stop(self):
        """Disconnect from exchange."""
        self._running = False
        self.client.disconnect()
        print(f"[BOT {self.client_id}] Stopped | Realized P&L: ${self.realized_pnl:.2f}")
    
    
    # ==================== Orders ====================
    
    def buy(self, symbol, qty, price):
        """Send a buy order. Returns client_order_id."""
        order_id = self.client.send_order(
            symbol=symbol,
            side=Side.BUY,
            qty=qty,
            price=price
        )
        print(f"[BOT {self.client_id}] BUY {qty} {symbol} @ {price}")
        return order_id
    
    
    def sell(self, symbol, qty, price):
        """Send a sell order. Returns client_order_id."""
        order_id = self.client.send_order(
            symbol=symbol,
            side=Side.SELL,
            qty=qty,
            price=price
        )
        print(f"[BOT {self.client_id}] SELL {qty} {symbol} @ {price}")
        return order_id
    
    
    def cancel(self, symbol, order_id=None, client_order_id=None):
        """Cancel an existing order."""
        self.client.cancel_order(
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id
        )
        print(f"[BOT {self.client_id}] CANCEL {symbol} order")
    
    
    # ==================== Position Tracking ====================
    
    def get_position(self, symbol):
        """Get current position. Positive=long, negative=short, zero=flat."""
        return self.positions.get(symbol, 0)
    
    
    def on_fill(self, symbol, side, qty, price):
        """
        Call this when a fill is received from exchange.
        Updates position and calculates P&L.
        """
        current_pos = self.positions.get(symbol, 0)
        current_cost = self.avg_cost.get(symbol, 0.0)
        
        if side == Side.BUY:
            # Buying
            if current_pos >= 0:
                # Adding to long position - update average cost
                total_cost = (current_cost * current_pos) + (price * qty)
                new_pos = current_pos + qty
                self.avg_cost[symbol] = total_cost / new_pos if new_pos > 0 else 0.0
                self.positions[symbol] = new_pos
            else:
                # Covering short - realize P&L
                cover_qty = min(qty, abs(current_pos))
                pnl = cover_qty * (current_cost - price)  # Short: profit when price goes down
                self.realized_pnl += pnl
                
                new_pos = current_pos + qty
                self.positions[symbol] = new_pos
                
                # If flipped to long, reset cost basis
                if new_pos > 0:
                    remaining_qty = qty - cover_qty
                    self.avg_cost[symbol] = price if remaining_qty > 0 else 0.0
                elif new_pos == 0:
                    self.avg_cost[symbol] = 0.0
        
        else:  # SELL
            # Selling
            if current_pos <= 0:
                # Adding to short position - update average cost
                total_cost = (current_cost * abs(current_pos)) + (price * qty)
                new_pos = current_pos - qty
                self.avg_cost[symbol] = total_cost / abs(new_pos) if new_pos < 0 else 0.0
                self.positions[symbol] = new_pos
            else:
                # Closing long - realize P&L
                close_qty = min(qty, current_pos)
                pnl = close_qty * (price - current_cost)  # Long: profit when price goes up
                self.realized_pnl += pnl
                
                new_pos = current_pos - qty
                self.positions[symbol] = new_pos
                
                # If flipped to short, reset cost basis
                if new_pos < 0:
                    remaining_qty = qty - close_qty
                    self.avg_cost[symbol] = price if remaining_qty > 0 else 0.0
                elif new_pos == 0:
                    self.avg_cost[symbol] = 0.0
        
        print(f"[BOT {self.client_id}] FILL: {side.name} {qty} {symbol} @ {price} | Position: {self.positions[symbol]} | P&L: ${self.realized_pnl:.2f}")
    
    
    def get_unrealized_pnl(self, symbol, current_price):
        """Calculate unrealized P&L at current market price."""
        pos = self.positions.get(symbol, 0)
        cost = self.avg_cost.get(symbol, 0.0)
        
        if pos > 0:
            return pos * (current_price - cost)
        elif pos < 0:
            return abs(pos) * (cost - current_price)
        return 0.0
    
    
    def get_total_pnl(self, current_prices):
        """
        Get total P&L (realized + unrealized).
        current_prices: dict of symbol -> current price
        """
        unrealized = sum(
            self.get_unrealized_pnl(symbol, current_prices.get(symbol, 0))
            for symbol in self.symbols
        )
        return self.realized_pnl + unrealized
    
    
    # ==================== Strategy Hook ====================
    
    @abstractmethod
    def on_tick(self, symbol, price, timestamp=None):
        """
        Called when new market data arrives.
        
        Args:
            symbol: The stock symbol (e.g., "AAPL")
            price: Current price
            timestamp: Optional timestamp of the tick
        
        Subclasses MUST implement this with their trading logic.
        """
        pass
