class LocalCache:
    """Small process-local cache replacing Redis for a single PM2 process."""

    def __init__(self):
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value

    async def publish(self, channel: str, value: str) -> None:
        return None
