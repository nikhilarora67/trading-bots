from .base_bot import BaseBot


class MarketMakerBot(BaseBot):
    """Quotes both sides of the market around the last price and tries to earn
    the spread. Inventory skews the quotes: long inventory shifts both prices
    down to attract buyers, short inventory shifts them up. This is the only
    bot whose orders rest on the book, so it's also the only one that uses
    cancels and reacts to its own fills."""

    def __init__(self, client_id, symbol, spread=2.0, quote_qty=10,
                 max_inventory=50, skew_per_unit=0.05, requote_tolerance=0.5, **kwargs):
        super().__init__(client_id, [symbol], **kwargs)
        self.symbol = symbol
        self.spread = spread
        self.quote_qty = quote_qty
        self.max_inventory = max_inventory
        self.skew_per_unit = skew_per_unit
        self.requote_tolerance = requote_tolerance

        # quote state lives on the tick path only. Fills land on the listener
        # thread and just move inventory, which the next re-quote reads.
        self.quote_mid = None
        self.bid_id = None
        self.ask_id = None

    def on_tick(self, symbol, price, timestamp=None):
        if symbol != self.symbol:
            return
        # leave quotes alone until price drifts away from where they're centered
        if self.quote_mid is not None and abs(price - self.quote_mid) < self.requote_tolerance:
            return
        self._requote(price)

    def _requote(self, price):
        # pull the old quotes first. If one was already filled, the cancel is
        # a no-op on our side and the exchange ignores it.
        if self.bid_id is not None:
            self.cancel(self.symbol, client_order_id=self.bid_id)
        if self.ask_id is not None:
            self.cancel(self.symbol, client_order_id=self.ask_id)

        inventory = self.get_position(self.symbol)
        mid = price - inventory * self.skew_per_unit
        half = self.spread / 2
        bid_price = round(mid - half, 2)
        ask_price = round(mid + half, 2)

        # stop quoting the side that would grow a maxed-out position
        self.bid_id = self.buy(self.symbol, self.quote_qty, bid_price) if inventory < self.max_inventory else None
        self.ask_id = self.sell(self.symbol, self.quote_qty, ask_price) if inventory > -self.max_inventory else None

        self.quote_mid = price
        print(f"[MM] quoting {bid_price} / {ask_price} | inventory {inventory}")
