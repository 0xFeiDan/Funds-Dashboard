import base64
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Sane single-server defaults; environment variables remain optional overrides."""

    model_config = SettingsConfigDict(extra="ignore")
    data_dir: str = str(BACKEND_DIR / "data")
    database_url: str | None = None
    frontend_dist: str = str(PROJECT_DIR / "frontend" / "out")
    app_encryption_key: str | None = None
    session_secret: str | None = None
    bootstrap_username: str = "admin"
    bootstrap_password: str | None = None
    cookie_secure: bool = False
    reconcile_interval_seconds: int = 30
    snapshot_interval_seconds: int = 300
    stale_warning_seconds: int = 45
    stale_seconds: int = 90
    disconnected_seconds: int = 180
    # Optional private RPCs stay in the server environment.  They are never
    # sent to the browser or committed with the application source.
    # ANKR_RPC_URL accepts any standard Ankr per-chain endpoint. The service
    # derives the ETH, Arbitrum, Solana, token-indexer and BTC Blockbook URLs
    # from its key without hard-coding it in source.
    ankr_rpc_url: str | None = None
    arbitrum_rpc_url: str | None = None  # Backward-compatible alias.
    ethereum_rpc_url: str | None = None
    ethereum_token_rpc_url: str | None = None
    arbitrum_token_rpc_url: str | None = None
    solana_rpc_url: str | None = None
    bitcoin_blockbook_url: str | None = None


def _runtime_values(directory: Path) -> dict[str, str]:
    """Persist generated secrets so encrypted exchange credentials survive restarts."""
    directory.mkdir(parents=True, exist_ok=True)
    runtime_file = directory / "runtime-secrets.json"
    try:
        values = json.loads(runtime_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        values = {}
    changed = False
    if not values.get("app_encryption_key"):
        values["app_encryption_key"] = base64.urlsafe_b64encode(os.urandom(32)).decode()
        changed = True
    if not values.get("session_secret"):
        values["session_secret"] = secrets.token_urlsafe(48)
        changed = True
    if not values.get("bootstrap_password"):
        values["bootstrap_password"] = secrets.token_urlsafe(18)
        changed = True
    if changed or not runtime_file.exists():
        runtime_file.write_text(json.dumps(values, indent=2), encoding="utf-8")
        runtime_file.chmod(0o600)
    first_login = directory / "first-login.txt"
    if not first_login.exists():
        first_login.write_text(
            f"username=admin\npassword={values['bootstrap_password']}\n",
            encoding="utf-8",
        )
        first_login.chmod(0o600)
    return values


settings = Settings()
data_dir = Path(settings.data_dir).expanduser().resolve()
runtime = _runtime_values(data_dir)
settings.app_encryption_key = settings.app_encryption_key or runtime["app_encryption_key"]
settings.session_secret = settings.session_secret or runtime["session_secret"]
settings.bootstrap_password = settings.bootstrap_password or runtime["bootstrap_password"]
settings.database_url = settings.database_url or f"sqlite+aiosqlite:///{(data_dir / 'dashboard.db').as_posix()}"


def _ankr_source() -> tuple[str, str, str] | None:
    """Extract scheme, host and key from a user-owned Ankr chain endpoint."""
    value = settings.ankr_rpc_url or settings.arbitrum_rpc_url
    if not value:
        return None
    parsed = urlsplit(value)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if parsed.hostname != "rpc.ankr.com" or len(segments) != 2 or not segments[1]:
        return None
    return parsed.scheme or "https", parsed.netloc, segments[1]


def ankr_chain_rpc_url(chain: str) -> str | None:
    source = _ankr_source()
    if not source:
        return None
    scheme, host, key = source
    return urlunsplit((scheme, host, f"/{chain}/{key}", "", ""))


def ankr_token_rpc_url() -> str | None:
    source = _ankr_source()
    if not source:
        return None
    scheme, host, key = source
    return urlunsplit((scheme, host, f"/multichain/{key}", "", ""))


def ankr_bitcoin_blockbook_url() -> str | None:
    source = _ankr_source()
    if not source:
        return None
    scheme, host, key = source
    return urlunsplit((scheme, host, f"/premium-http/btc_blockbook/{key}", "", ""))
