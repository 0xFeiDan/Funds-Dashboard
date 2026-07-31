from decimal import Decimal
from app.risk import effective_leverage,liquidation_distance,risk_level
from app.schemas import RiskLevel,Side
def test_effective_leverage_and_zero_equity():
    assert effective_leverage(Decimal("100"),Decimal("20"))==Decimal("5")
    assert effective_leverage(Decimal("100"),Decimal("0")) is None
def test_liquidation_distance_for_both_sides():
    assert liquidation_distance(Side.LONG,Decimal("100"),Decimal("90"))==Decimal("10.0")
    assert liquidation_distance(Side.SHORT,Decimal("100"),Decimal("105"))==Decimal("5.00")
    assert risk_level(Decimal("3"))==RiskLevel.CRITICAL
    assert risk_level(None)==RiskLevel.UNKNOWN
