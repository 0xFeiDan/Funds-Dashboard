# 多平台永续合约持仓仪表盘

这是一个只读仪表盘：没有下单、撤单、划转、提现、钱包签名或交易开关。一个 PM2 进程同时提供网页和 API；SQLite 数据库、登录密码和加密密钥都会自动在 Ubuntu 服务器本地创建。

## Ubuntu 一次性启动

前提：Ubuntu 已有 `git`、`python3`、Node.js/npm 和 PM2。若缺 PM2，执行一次：

```bash
sudo npm install -g pm2
```

部署只需：

```bash
git clone https://github.com/0xFeiDan/Funds-Dashboard.git
cd Funds-Dashboard
bash deploy/setup-ubuntu.sh
```

脚本会安装 Python 依赖、构建网页、创建 SQLite 数据库、生成加密密钥和随机登录密码，并用 PM2 启动服务。无需 Docker、Redis、PostgreSQL 或 `.env`。

查看首次登录信息：

```bash
cat backend/data/first-login.txt
```

从 Windows 浏览器访问：

```text
http://Ubuntu服务器IP:8089
```

常用命令：

```bash
pm2 status
pm2 logs funds-dashboard
pm2 restart funds-dashboard
pm2 save
pm2 startup systemd -u "$USER" --hp "$HOME"
```

若 Ubuntu 启用了 UFW，只放行你的 Windows IP 到 8089：

```bash
sudo ufw allow from 你的WindowsIP to any port 8089 proto tcp
```

首次登录后，在“账户配置”中填交易所账户。Hyperliquid/Lighter 只需公开地址或账户索引；Binance/Bitget 只接受禁用交易和提现权限的只读 API Key，并应限制为 Ubuntu 服务器 IP。

## 数据位置

所有本地状态位于 `backend/data/`：SQLite 数据库、自动生成的运行密钥及首次登录凭据。这个目录不能提交到 Git；备份时整体复制它即可。

## 开发验证

```bash
cd backend
.venv/bin/python -m pytest -q
curl http://127.0.0.1:8089/api/health/live
```
