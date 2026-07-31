# 多平台永续合约只读持仓监控

一个 Docker 可部署的、只读的持仓与风险监控基础版本。它刻意没有下单、撤单、划转、提现、钱包签名或任何交易权限开关。所有交易所私有请求仅在 Python 后端发起；浏览器只能请求本系统的同源 API。

## 当前交付范围

第一阶段已经可运行：本地用户名/密码会话登录、账户配置（敏感字段 AES-256-GCM 加密）、四个独立 adapter、REST 快照、统一账户/仓位结构、风险/净敞口计算、连接状态和移动端页面。Hyperliquid 使用公开钱包/Vault 地址；Lighter 使用公开账户索引或 L1 地址。Binance/Bitget 必须使用禁用交易和提现的只读 API key。

第二阶段已开始实现：每个账户有独立的实时 worker；Binance listen key、Bitget 私有 account/positions、Hyperliquid 地址流、Lighter 公开 account stream 都只把事件作为“触发信号”。事件后由 REST 快照覆盖 Redis 状态，断线采用指数退避并在重连后强制对账。历史 Funding、交易、手续费、账变会写入独立账本表；未支持或缺少可验证历史的交易所会在 PnL 页面显示“不完整”，绝不以权益变动伪造 PnL。

## 官方 API 研究（2026-07-31）

| 平台 | 当前实现的只读入口 | 身份方式与关键限制 | 口径/风险 |
|---|---|---|---|
| Binance USDⓈ-M | `/fapi/v3/account`、`/fapi/v3/positionRisk` | `X-MBX-APIKEY` + HMAC-SHA256 signed `USER_DATA` 请求；服务器 IP 应加入白名单。账户数据流需 listen key 与 keepalive（第二阶段）。 | `totalMarginBalance` 作为平台权益，按结算币种/账户范围隔离，不能和异币种余额直接相加。 |
| Bitget Futures | `/api/v2/mix/account/accounts`、`/api/v2/mix/position/all-position` | API key + timestamp + HMAC Base64 签名 + passphrase。账户分 `USDT-FUTURES`、`USDC-FUTURES`、`COIN-FUTURES`；私有 account/positions WS 在第二阶段。 | 支持 one-way/hedge，使用 `holdSide` 标准化成长/短；每个产品类型建议单独配置一个账户。 |
| Hyperliquid | `POST /info` 的 `clearinghouseState` | 公共地址查询，不需也不保存私钥。`marginSummary.accountValue`、`withdrawable`、`assetPositions` 可读；WS 有 clearinghouseState/asset context 订阅。 | 公开状态是地址可见数据；cross 清算会受同账户资产、资金费率等影响，强平价始终标为估计。 |
| Lighter | `GET /api/v1/account`，按 account index / L1 address | 公开账户查询优先。官方文档有 read-only auth token；不接受写权限 API 私钥。一个 L1 地址可映射多个 account/subaccount index。 | 官方响应字段会演进：缺少值保持为空/零且保留口径说明，不虚构字段。 |

权威资料：[Binance API catalog](https://developers.binance.com/en/docs/catalog)、[Binance request security](https://developers.binance.com/en/docs/products/spot/rest-api#request-security)、[Bitget futures best practices](https://www.bitget.com/api-doc/classic/best-practices)、[Bitget positions channel](https://www.bitget.com/api-doc/classic/contract/websocket/private/Positions-Channel)、[Hyperliquid perpetuals](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals)、[Hyperliquid rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits)、[Lighter get started](https://apidocs.lighter.xyz/docs/get-started)、[Lighter read-only authentication](https://apidocs.lighter.xyz/docs/api-keys)。生产配置前请再核对文档，因为交易所字段和配额会变动。

## 架构与目录

```
backend/app/adapters/  每个平台独立认证、请求和标准化边界
backend/app/schemas.py 统一 Pydantic/Decimal 数据契约
backend/app/risk.py    强平距离、风险等级、有效杠杆
backend/app/services/  快照聚合、缓存、重连/对账机制
backend/alembic/       PostgreSQL 迁移
frontend/app/          Next.js 页面与移动端样式
frontend/components/   总览、持仓、净敞口、状态、配置页面
deploy/nginx/          同源反向代理（仅暴露 Nginx）
```

## 第二阶段运行机制

服务启动后 `SyncSupervisor` 每 60 秒发现启用账户，并为每个账户创建相互隔离的任务。任务启动、每 45 秒定时、收到实时事件、以及重连成功后，都会调用 REST 快照；连续失败五次后本账户的熔断器暂停 60 秒，不影响其他账户。历史同步最少间隔 180 秒，避免因事件高峰过度请求交易所。

浏览器连接 `/backend/ws/dashboard` 后只收到“数据已更新”通知，再经同源 REST 拉取已标准化数据。Nginx 已配置 WebSocket upgrade。`trades`、`funding_payments`、`trading_fees`、`balance_movements` 根据账户+外部事件 ID 去重，时间统一 UTC。

数据表均 UTC：`users`、`exchange_accounts`、`encrypted_credentials`、`account_snapshots`、`positions_snapshots`、`current_positions`、`trades`、`fills`、`funding_payments`、`trading_fees`、`balance_movements`、`daily_pnl`、`daily_equity`、`connection_status`、`reconciliation_logs`、`audit_logs`。账户维度和时间维度均有索引；账户名称按用户+交易所唯一。建议：实时快照 30 天、仓位快照 90 天、交易/资金/审计 2 年（按合规需要调整）。

## Ubuntu 部署

1. 安装 Docker Engine 和 Compose plugin，并在 Tailscale 上让服务器加入私有 tailnet。
2. `cp .env.example .env`，生成 `APP_ENCRYPTION_KEY`，修改 PostgreSQL 密码与初始登录密码。不要提交 `.env`。
3. 执行 `docker compose up -d --build`。
4. 默认只监听 `127.0.0.1:8089`。通过 `tailscale serve --https=443 http://127.0.0.1:8089` 访问，或只把 Nginx 绑定到 Tailscale IP；不要把 PostgreSQL/Redis 映射端口。
5. 首次登录后，在“账户配置”页面填入地址或只读 API 凭据。Binance/Bitget key 必须禁用 Trade/Withdraw 并限定服务器 IP。

检查：`curl http://127.0.0.1:8089/backend/health/live` 和 `docker compose ps`。生产站点保持 `COOKIE_SECURE=true`；纯本机 HTTP 调试才可临时设为 false。

## 验证与测试

```bash
cd backend
python -m pytest -q
docker compose config
docker compose up -d --build
```

测试覆盖 Decimal 标准化、零权益杠杆、双向强平距离、风险分级、AES-GCM/日志脱敏，以及第二阶段 WebSocket 断线后 REST 对账与实时账本事件提取。Adapter HTTP/WS 测试必须使用 mock；此项目没有任何真实下单代码或测试。
