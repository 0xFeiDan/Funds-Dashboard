from decimal import Decimal
from .schemas import RiskLevel,Side
ZERO=Decimal("0")
def effective_leverage(notional:Decimal,equity:Decimal)->Decimal|None:return notional/equity if equity>ZERO else None
def liquidation_distance(side:Side,mark:Decimal|None,liquidation:Decimal|None)->Decimal|None:
    if not mark or not liquidation or mark<=ZERO:return None
    return ((mark-liquidation)/mark if side==Side.LONG else (liquidation-mark)/mark)*Decimal("100")
def risk_level(distance:Decimal|None)->RiskLevel:
    if distance is None or distance<ZERO:return RiskLevel.UNKNOWN
    if distance<Decimal("5"):return RiskLevel.CRITICAL
    if distance<Decimal("10"):return RiskLevel.DANGER
    if distance<=Decimal("20"):return RiskLevel.WATCH
    return RiskLevel.SAFE
