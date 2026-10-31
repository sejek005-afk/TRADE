from .base import Context, Signal, Strategy
from .breakout import AsiaLondonBreakout, BreakRetest, OpeningRangeBreakout, Squeeze
from .reversal import BollingerRsiReversal, CandlePatterns
from .smc import SmartMoney
from .trend import EmaCross, MacdMomentum, Pullback, SupertrendEma, Vwap

ALL: dict[str, Strategy] = {s.name: s for s in (
    EmaCross(), SupertrendEma(), Pullback(), MacdMomentum(), OpeningRangeBreakout(), AsiaLondonBreakout(),
    BreakRetest(), Squeeze(), BollingerRsiReversal(), Vwap(), SmartMoney(), CandlePatterns(),
)}

NAMES_FA = {k: v.fa for k, v in ALL.items()}

__all__ = ["ALL", "NAMES_FA", "Context", "Signal", "Strategy"]
