from enum import IntEnum

# These match the C++ exchange definitions in types.hpp
# Values must be identical or messages won't parse correctly
 
class Side(IntEnum):
    BUY = 1
    SELL = 2

    def as_string(self):
        if self == Side.BUY:
            return "B"
        else:
            return "S"

    @classmethod   
    def parse(cls, side):
        side = side.upper()
        if side in ("B", "BUY", "BID"):
            return cls.BUY
        elif side in ("S", "SELL", "ASK"):
            return cls.SELL
        raise ValueError(f"Invalid Side: {side}")



class OrdType(IntEnum):
    MARKET = 1
    LIMIT = 2

    def as_string(self):
        if self == OrdType.MARKET:
            return "MKT"
        else:
            return "LMT"

    @classmethod   
    def parse(cls, ord_type):
        ord_type = ord_type.upper()
        if ord_type in ("MKT", "MARKET"):
            return cls.MARKET
        elif ord_type in ("LMT", "LIMIT"):
            return cls.LIMIT
        raise ValueError(f"Invalid OrdType: {ord_type}")
    


class TimeInForce(IntEnum):
    DAY = 1 # Order valid until end of trading day
    IOC = 2 # Immediate or cancel

    def as_string(self):
        if self == TimeInForce.DAY:
            return "DAY"
        else:
            return "IOC"
    
    @classmethod
    def parse(cls, tif):
        tif = tif.upper()
        if tif == "DAY":
            return cls.DAY
        elif tif == "IOC":
            return cls.IOC
        raise ValueError(f"Invalid TimeInForce: {tif}")
    


class MsgType(IntEnum):
    # Outbound (bot to exchange)
    NEW_ORDER = 1
    CANCEL = 2

    # Inbound (exchange to bot)
    ACK = 100
    REJECT = 101
    FILL = 102

    # System
    HEARTBEAT = 900