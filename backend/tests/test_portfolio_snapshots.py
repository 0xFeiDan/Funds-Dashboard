from app.services.portfolio import snapshot_changed


def test_snapshot_change_ignores_refresh_timestamps():
    previous={"summary":{"account_equity":"10","updated_at":"2026-01-01T00:00:00+00:00"},"positions":[{"symbol":"BTC","position_value":"5","updated_at":"2026-01-01T00:00:00+00:00"}]}
    refreshed={"summary":{"account_equity":"10","updated_at":"2026-01-01T00:01:00+00:00"},"positions":[{"symbol":"BTC","position_value":"5","updated_at":"2026-01-01T00:01:00+00:00"}]}
    assert not snapshot_changed(previous,refreshed)


def test_snapshot_change_keeps_real_balance_changes():
    previous={"summary":{"account_equity":"10"},"positions":[]}
    current={"summary":{"account_equity":"11"},"positions":[]}
    assert snapshot_changed(previous,current)
