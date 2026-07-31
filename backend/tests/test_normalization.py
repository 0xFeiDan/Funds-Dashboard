from datetime import datetime,timezone
from decimal import Decimal
from app.schemas import Exchange,NormalizedPosition,Side
def test_decimal_serializes_without_float_loss():
    position=NormalizedPosition(exchange=Exchange.HYPERLIQUID,account_id="a",account_name="a",symbol="BTC",exchange_symbol="BTC",base_asset="BTC",side=Side.LONG,quantity=Decimal("0.100000000000000001"),position_value=Decimal("10000.01"),updated_at=datetime.now(timezone.utc))
    assert position.model_dump(mode="json")["quantity"]=="0.100000000000000001"
