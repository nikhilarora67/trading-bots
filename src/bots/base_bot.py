from abc import ABC, abstractmethod
from ..models.enums import Side
from ..connection.exchange_client import ExchangeClient


class BaseBot(ABC):
    """Shared plumbing for the bots: exchange connection, order helpers, and a
    per-symbol position count. Subclasses implement on_tick() with their own
    signal logic."""

    def __init__(self, client_id, symbols, host="localhost", send_port=5555, recv_port=5556):
        self.client_id = client_id
        self.symbols = symbols if isinstance(symbols, list) else [symbols]

        self.client = ExchangeClient(client_id=client_id, host=host,
                                     send_port=send_port, recv_port=recv_port)
        # positions update off actual exchange fills, not off order sends
        self.client.on_fill = self.on_fill

        # positive = long, negative = short, zero = flat
        self.positions = {symbol: 0 for symbol in self.symbols}
        self._running = False

    def start(self):
        self.client.connect()
        self.client.start_listening()
        self._running = True
        print(f"[BOT {self.client_id}] started | symbols: {self.symbols}")

    def stop(self):
        self._running = False
        self.client.disconnect()
        print(f"[BOT {self.client_id}] stopped")

    def buy(self, symbol, qty, price):
        order_id = self.client.send_order(symbol=symbol, side=Side.BUY, qty=qty, price=price)
        print(f"[BOT {self.client_id}] BUY {qty} {symbol} @ {price}")
        return order_id

    def sell(self, symbol, qty, price):
        order_id = self.client.send_order(symbol=symbol, side=Side.SELL, qty=qty, price=price)
        print(f"[BOT {self.client_id}] SELL {qty} {symbol} @ {price}")
        return order_id

    def cancel(self, symbol, order_id=None, client_order_id=None):
        self.client.cancel_order(symbol=symbol, order_id=order_id, client_order_id=client_order_id)
        print(f"[BOT {self.client_id}] CANCEL {symbol}")

    def get_position(self, symbol):
        return self.positions.get(symbol, 0)

    def on_fill(self, symbol, side, qty, price):
        """Update the position count when the exchange reports a fill."""
        change = qty if side == Side.BUY else -qty
        self.positions[symbol] = self.positions.get(symbol, 0) + change
        print(f"[BOT {self.client_id}] FILL {side.name} {qty} {symbol} @ {price} | position: {self.positions[symbol]}")

    @abstractmethod
    def on_tick(self, symbol, price, timestamp=None):
        """Called on new market data. Each strategy implements its own logic."""
