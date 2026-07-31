# Security model

This repository is intentionally read-only. Do not add order, cancellation, transfer, withdrawal, signer, wallet-private-key, seed phrase, or arbitrary URL proxy endpoints.

## Credentials

- `.env` is ignored. Keep `APP_ENCRYPTION_KEY` and `SESSION_SECRET` in deployment secret management, never Git or logs.
- API credentials are AES-256-GCM encrypted at rest; the 32-byte key is only injected by environment variable and decrypted only while an adapter makes a request.
- API Secret, passphrase, password, session token, signatures and private keys are redacted from logs and are never returned from `GET /accounts`.
- Binance/Bitget keys must be least-privilege, read-only, withdrawal/trading disabled, and IP allowlisted. Revoke any key that has more permission.
- Hyperliquid stores only a public address. Lighter uses public index/address or official read-only token; never use a wallet/private signing key.
- Lighter 官方一般 API key 同时具备读写能力；本项目不使用其私钥/API signing key。仅使用公开流，或未来由用户提供官方 read-only token 时才启用认证通道。

## Network and browser

- Nginx exposes only localhost by default; PostgreSQL and Redis are Docker-internal only. Prefer Tailscale access.
- Login uses HttpOnly, Secure, SameSite=Strict session cookies; state-changing requests require a CSRF header matching the CSRF cookie; failed logins are rate-limited.
- No generic URL fetch/proxy exists. SQLAlchemy parameterization is used for database access. Dashboard only renders text values (not exchange HTML).
- For an externally reachable deployment, terminate TLS before the app, retain `COOKIE_SECURE=true`, restrict CORS to exact origins, and review reverse-proxy headers.

## Operations

Rotate credentials on suspected exposure, invalidate sessions by changing `SESSION_SECRET`, and rotate database encryption after implementing a controlled re-encryption migration. Audit account creation/deletion/configuration changes and inspect connection errors without storing request secrets. Run containers as non-root users.
