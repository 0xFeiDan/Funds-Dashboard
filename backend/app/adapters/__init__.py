from .base import ExchangeAdapter
from .binance import BinanceAdapter
from .bitget import BitgetAdapter
from .hyperliquid import HyperliquidAdapter
from .lighter import LighterAdapter
from ..schemas import Exchange
ADAPTERS={Exchange.BINANCE:BinanceAdapter,Exchange.BITGET:BitgetAdapter,Exchange.HYPERLIQUID:HyperliquidAdapter,Exchange.LIGHTER:LighterAdapter}
