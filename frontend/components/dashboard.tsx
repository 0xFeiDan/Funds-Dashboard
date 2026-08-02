"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import type { AccountItem } from "../services/api";
import type { DashboardData, EquityHistory, HistoricalSnapshot, PnlAttribution, PnlData, Position } from "../types";

type Page = "overview" | "positions" | "exposure" | "pnl" | "status" | "settings";
type Row = Record<string, string | number | undefined>;
type RequestState<T> = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: T };

const nf = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 });
const fmt = (value?: string, short = false) => (short ? compact : nf).format(Number(value ?? 0) || 0);
const signed = (value?: string) => `${Number(value ?? 0) >= 0 ? "+" : ""}${fmt(value)}`;
const money = (value?: string) => `$${fmt(value)}`;
const pct = (value: number) => `${value < 0.01 && value > 0 ? "<0.01" : fmt(String(value))}%`;
const cnRisk = (risk?: string) => ({ SAFE: "低风险", WATCH: "留意", DANGER: "高风险", CRITICAL: "紧急" }[risk ?? ""] ?? "待确认");
const cnState = (state?: string) => ({ LIVE: "实时", CONNECTED: "已连接", WARNING: "延迟", STALE: "过期", DISCONNECTED: "断开", ERROR: "异常" }[state ?? ""] ?? "等待同步");
const icon = (symbol: string) => <span className="icon" aria-hidden>{symbol}</span>;
const scopedAccount = (accountId: string) => accountId === "all" ? undefined : accountId;
const requestMessage = (reason: unknown) => reason instanceof Error && reason.message ? reason.message : "暂时无法连接数据服务";

function useRequest<T>(request: () => Promise<T>, dependencies: unknown[]) {
  const [state, setState] = useState<RequestState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    void request().then(data => { if (!cancelled) setState({ status: "ready", data }); }).catch(reason => { if (!cancelled) setState({ status: "error", message: requestMessage(reason) }); });
    return () => { cancelled = true; };
  // The caller controls refetches through the explicit dependency list.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, attempt]);
  return { state, retry: () => setAttempt(value => value + 1) };
}

function RequestFeedback({ state, loadingText, onRetry }: { state: Extract<RequestState<unknown>, { status: "loading" | "error" }>; loadingText: string; onRetry: () => void }) {
  if (state.status === "loading") return <div className="request-feedback" role="status"><span className="loading-dot" aria-hidden />{loadingText}</div>;
  return <div className="request-feedback error" role="alert"><b>暂时无法加载</b><span>{state.message}</span><button className="refresh" onClick={onRetry}>重试</button></div>;
}

function Sidebar({ page, setPage, theme, onThemeToggle, healthText }: { page: Page; setPage: (page: Page) => void; theme: "light" | "dark"; onThemeToggle: () => void; healthText: string }) {
  const nav: Array<[Page, string, string]> = [["overview", "总览", "▦"], ["positions", "持仓", "▤"], ["exposure", "风险敞口", "◔"], ["pnl", "盈亏分析", "↗"], ["status", "系统状态", "◌"], ["settings", "账户配置", "⚙"]];
  return <aside className="sidebar"><div className="brand"><b>◈</b><span>资金驾驶舱</span></div><small className="nav-caption">监控中心</small><nav aria-label="主导航">{nav.map(([key, label, mark]) => <button key={key} className={page === key ? "active" : ""} aria-current={page === key ? "page" : undefined} title={label} onClick={() => setPage(key)}>{icon(mark)}<span>{label}</span></button>)}</nav><div className="sidebar-footer"><button className="theme-toggle" type="button" aria-pressed={theme === "dark"} title={theme === "dark" ? "切换浅色模式" : "切换深色模式"} onClick={onThemeToggle}>{icon(theme === "dark" ? "☀" : "◐")}<span>{theme === "dark" ? "浅色模式" : "深色模式"}</span></button><div className="health"><i />{healthText}</div></div></aside>;
}

function Login({ done }: { done: () => void }) {
  const [username, setUsername] = useState("admin"); const [password, setPassword] = useState(""); const [message, setMessage] = useState("");
  const submit = async (event: FormEvent) => { event.preventDefault(); try { await api.login(username, password); done(); } catch { setMessage("用户名或密码错误，请检查 Ubuntu 服务器中的首次登录信息。"); } };
  return <main className="login-screen"><form className="login-card" onSubmit={submit}><div className="login-logo">◈</div><p className="eyebrow">READ-ONLY PORTFOLIO MONITOR</p><h1>资金驾驶舱</h1><p>只读监控，不执行任何交易操作。</p><label>用户名<input value={username} onChange={event => setUsername(event.target.value)} /></label><label>密码<input type="password" autoFocus value={password} onChange={event => setPassword(event.target.value)} /></label><button className="primary">安全登录 <span>→</span></button>{message && <em>{message}</em>}</form></main>;
}

function Metric({ label, value, unit = "USDT", kind = "plain", detail, mark }: { label: string; value?: string; unit?: string; kind?: string; detail: string; mark: string }) {
  return <article className="metric"><div><span className={`metric-mark ${kind}`}>{icon(mark)}</span><label>{label}</label><b className="info">i</b></div><strong className={kind === "gain" ? "positive" : kind === "loss" ? "negative" : ""}>{fmt(value)} <small>{unit}</small></strong><footer>{detail}<span className="spark" /></footer></article>;
}

function Exposure({ rows }: { rows: Record<string, unknown>[] }) {
  const visible = rows.map(row => ({ asset: String(row.asset ?? "其他"), value: Math.abs(Number(row.gross_notional ?? 0)), long: Number(row.long_notional ?? 0), short: Number(row.short_notional ?? 0) })).filter(row => row.value > 0).sort((a, b) => b.value - a.value);
  const total = visible.reduce((sum, row) => sum + row.value, 0);
  const colors = ["#197a86", "#e5962d", "#3e73df", "#8b97a9"];
  return <section className="panel exposure"><header><div><p className="eyebrow">EXPOSURE</p><h2>资产敞口</h2></div><span className="mini-chip">按可计价市值</span></header>{visible.length ? <div className="exposure-list">{visible.map((row, index) => { const share = row.value / total * 100; const directional = row.long + row.short > 0; return <div className="exposure-item" key={row.asset}><div className="exposure-item-heading"><span><i style={{ background: colors[index] }} />{row.asset}</span><b>{money(String(row.value))}</b><strong>{pct(share)}</strong></div><div className="exposure-track"><i style={{ width: `${Math.max(share, .6)}%`, background: colors[index] }} /></div>{directional && <small>合约方向：多 {money(String(row.long))} · 空 {money(String(row.short))}</small>}</div>; })}</div> : <Empty text="配置账户后，跨平台敞口会在这里汇总。" />}</section>;
}

function Radar({ positions }: { positions: Position[] }) {
  const danger = positions.filter(position => ["DANGER", "CRITICAL"].includes(position.risk_level)).length;
  const near = positions.reduce((minimum, position) => Math.min(minimum, Number(position.liquidation_distance_percent ?? Infinity)), Infinity);
  const entries = [["强平风险", Number.isFinite(near) ? `最近强平距离 ${fmt(String(near))}%` : "暂未返回强平距离", danger ? "高风险" : "低风险", danger ? "danger" : "safe"], ["杠杆风险", `当前有 ${positions.length} 个活跃仓位`, positions.length > 5 ? "留意" : "正常", positions.length > 5 ? "watch" : "safe"], ["集中度风险", "持续监控资产及方向集中度", "正常", "safe"]];
  return <section className="panel radar"><header><div><p className="eyebrow">RISK RADAR</p><h2>风险雷达</h2></div>{icon("◇")}</header>{entries.map(([name, description, badge, tone]) => <div className="radar-row" key={name as string}><span className={`radar-icon ${tone}`}>⌁</span><div><b>{name}</b><p>{description}</p></div><span className={`risk ${tone}`}>{badge}</span></div>)}<footer>风险等级仅基于当前可读取的仓位快照。</footer></section>;
}

function Positions({ rows }: { rows: Position[] }) {
  const [query, setQuery] = useState(""); const [side, setSide] = useState("ALL");
  const list = useMemo(() => rows.filter(row => (!query || `${row.symbol} ${row.exchange} ${row.account_name}`.toLowerCase().includes(query.toLowerCase())) && (side === "ALL" || row.side === side)), [rows, query, side]);
  const kind = (row: Position) => ({ PERPETUAL: "永续", SPOT: "现货", VAULT_EQUITY: "Vault", STAKING: "质押", ONCHAIN_NATIVE: "链上原生币", ERC20: "链上 ERC-20", SPL: "链上 SPL Token" }[row.contract_type ?? ""] ?? "资产");
  const unpriced = (row: Position) => row.contract_type !== "PERPETUAL" && !row.mark_price;
  return <section className="panel positions"><header><div><p className="eyebrow">POSITIONS</p><h2>统一持仓</h2></div><div className="filters"><input placeholder="搜索资产或平台" value={query} onChange={event => setQuery(event.target.value)} /><select value={side} onChange={event => setSide(event.target.value)}><option value="ALL">全部方向</option><option value="LONG">仅多头</option><option value="SHORT">仅空头</option></select></div></header>{list.length ? <div className="table-scroll"><table><thead><tr><th>资产 / 账户</th><th>方向</th><th>持仓规模</th><th>开仓均价</th><th>标记价格</th><th>未实现盈亏</th><th>强平距离</th><th>风险</th></tr></thead><tbody>{list.map((row, index) => <tr key={`${row.exchange}-${row.symbol}-${index}`}><td><b>{row.symbol}</b><small>{kind(row)} · {row.exchange} · {row.account_name}</small></td><td><span className={`side ${row.side === "LONG" ? "long" : "short"}`}>{row.side === "LONG" ? "多" : "空"}</span></td><td>{unpriced(row) ? "未报价" : fmt(row.position_value, true)}<small>{unpriced(row) ? "未计入总权益" : "USDT"}</small></td><td>{row.contract_type === "PERPETUAL" ? fmt(row.entry_price) : "—"}</td><td>{unpriced(row) ? "未报价" : fmt(row.mark_price)}</td><td className={Number(row.unrealized_pnl) >= 0 ? "positive" : "negative"}><b>{row.contract_type === "PERPETUAL" ? signed(row.unrealized_pnl) : "—"}</b><small>{row.contract_type === "PERPETUAL" ? "USDT" : ""}</small></td><td><span className="distance">{row.contract_type === "PERPETUAL" && row.liquidation_distance_percent ? `${fmt(row.liquidation_distance_percent)}%` : "—"}<i style={{ width: `${Math.min(100, Number(row.liquidation_distance_percent ?? 0) * 3)}%` }} /></span></td><td><span className={`risk ${row.risk_level === "SAFE" ? "safe" : row.risk_level === "WATCH" ? "watch" : "danger"}`}>{row.contract_type === "PERPETUAL" ? cnRisk(row.risk_level) : "—"}</span></td></tr>)}</tbody></table></div> : <Empty text="尚无可展示的资产。添加账户后会自动同步。" />}</section>;
}

function Accounts({ accounts, connections }: { accounts: Row[]; connections: Row[] }) {
  const rows = accounts.length ? accounts : connections;
  return <section className="panel accounts"><header><div><p className="eyebrow">CONNECTIONS</p><h2>账户状态</h2></div>{icon("◌")}</header>{rows.length ? rows.map((account, index) => { const matched = connections.find(connection => connection.account_id === account.account_id); const state = String(matched?.state ?? account.state ?? account.data_state ?? "CONNECTED"); const failure = String(matched?.error ?? account.error ?? ""); return <div className="account" key={String(account.account_id ?? index)}><span>{String(account.exchange ?? "?").slice(0, 1).toUpperCase()}</span><div><b>{String(account.account_name ?? account.name ?? account.exchange)}</b><p>{failure ? `同步失败：${failure}` : account.account_equity ? `${fmt(String(account.account_equity), true)} USDT` : "等待快照"}</p></div><em className={state.toLowerCase()}><i />{cnState(state)}</em></div>; }) : <Empty text="没有已连接账户。" />}</section>;
}

function EquityChart({ history }: { history: EquityHistory | null }) {
  const points = history?.points ?? [];
  if (points.length < 2) return <section className="hero-chart empty-chart"><div><p className="eyebrow">EQUITY TREND</p><h2>近 30 天权益</h2></div><Empty text="净值快照正在累积，稍后会在这里显示权益趋势。" /></section>;
  const values = points.map(point => Number(point.equity));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const polyline = values.map((value, index) => `${(index / (values.length - 1)) * 100},${100 - ((value - min) / range) * 76 - 10}`).join(" ");
  const first = points[0]; const last = points.at(-1)!;
  return <section className="hero-chart"><header><div><p className="eyebrow">EQUITY TREND</p><h2>近 30 天权益</h2></div><span className="mini-chip">{history?.data_complete ? "快照完整" : "部分数据"}</span></header><div className="chart-value"><b className={Number(history?.change) >= 0 ? "positive" : "negative"}>{signed(history?.change)} <small>USDT</small></b><span>区间权益变化</span></div><div className="line-chart" aria-label="近 30 天权益曲线"><svg viewBox="0 0 100 100" preserveAspectRatio="none"><defs><linearGradient id="equity-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#2678ee" stopOpacity=".18" /><stop offset="1" stopColor="#2678ee" stopOpacity="0" /></linearGradient></defs><path d={`M 0,100 L ${polyline.replace(/ /g, " L ")} L 100,100 Z`} fill="url(#equity-fill)" /><polyline points={polyline} fill="none" stroke="#168f98" strokeWidth="1.7" vectorEffect="non-scaling-stroke" /></svg></div><footer><span>{new Date(first.at).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })}</span><span>{new Date(last.at).toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" })}</span></footer></section>;
}

function AssetAllocation({ rows }: { rows: Record<string, unknown>[] }) {
  const items = rows.map(row => ({ asset: String(row.asset ?? "其他"), value: Math.abs(Number(row.gross_notional ?? 0)) })).filter(item => item.value > 0).sort((a, b) => b.value - a.value);
  const total = items.reduce((sum, item) => sum + item.value, 0);
  const colors = ["#197a86", "#e5962d", "#3e73df", "#8b97a9"];
  return <section className="panel allocation"><header><div><p className="eyebrow">ALLOCATION</p><h2>资产配置</h2></div><span className="mini-chip">按市值</span></header>{items.length ? <div className="allocation-list">{items.slice(0, 5).map((item, index) => { const share = item.value / total * 100; return <div className="allocation-row" key={item.asset}><div><i style={{ backgroundColor: colors[index] }} /><b>{item.asset}</b></div><span className="allocation-track"><i style={{ width: `${Math.max(share, .6)}%`, backgroundColor: colors[index] }} /></span><strong>{pct(share)}</strong><small>{money(String(item.value))}</small></div>; })}</div> : <Empty text="尚无可计价资产。" />}</section>;
}

function AssetBalances({ rows }: { rows: Position[] }) {
  const assets = rows.filter(row => row.contract_type !== "PERPETUAL");
  return <section className="panel asset-balances"><header><div><p className="eyebrow">BALANCES</p><h2>资产余额</h2></div><span className="mini-chip">{assets.length} 项资产</span></header>{assets.length ? <div className="table-scroll"><table><thead><tr><th>资产</th><th>平台 / 网络</th><th>数量</th><th>USD 价值</th><th>占比</th></tr></thead><tbody>{assets.map((row, index) => <tr key={`${row.exchange}-${row.symbol}-${index}`}><td><b>{row.symbol}</b><small>{row.account_name}</small></td><td>{row.exchange}</td><td>{fmt(row.quantity)}</td><td><b>{money(row.position_value)}</b></td><td>{pct(Number(row.position_value) / Math.max(assets.reduce((sum, item) => sum + Number(item.position_value || 0), 0), 1) * 100)}</td></tr>)}</tbody></table></div> : <Empty text="尚无可展示的资产余额。" />}</section>;
}

function ContractPositions({ rows }: { rows: Position[] }) {
  const positions = rows.filter(row => row.contract_type === "PERPETUAL");
  return <section className="panel contract-positions"><header><div><p className="eyebrow">PERPETUALS</p><h2>合约仓位</h2></div><span className="mini-chip">{positions.length} 个活跃仓位</span></header>{positions.length ? <div className="table-scroll"><table><thead><tr><th>平台 / 合约</th><th>方向</th><th>持仓规模</th><th>开仓均价</th><th>标记价格</th><th>未实现盈亏</th></tr></thead><tbody>{positions.map((row, index) => <tr key={`${row.exchange}-${row.symbol}-${index}`}><td><b>{row.symbol}</b><small>{row.exchange} · {row.account_name}</small></td><td><span className={`side ${row.side === "LONG" ? "long" : "short"}`}>{row.side === "LONG" ? "多" : "空"}</span></td><td>{money(row.position_value)}</td><td>{fmt(row.entry_price)}</td><td>{fmt(row.mark_price)}</td><td className={Number(row.unrealized_pnl) >= 0 ? "positive" : "negative"}>{signed(row.unrealized_pnl)} USDT</td></tr>)}</tbody></table></div> : <div className="intentional-empty"><span>▱</span><b>当前无合约仓位</b><p>没有杠杆风险，也没有待监控的强平价格。</p></div>}</section>;
}

function Coverage({ rows }: { rows: DashboardData["coverage"] }) {
  return <section className="coverage-grid">{rows.map(row => <article className="coverage-card" key={row.account_id}><header><div><p className="eyebrow">ASSET COVERAGE</p><h2>{row.account_name}</h2><p>{row.exchange}</p></div><span className={row.state === "ERROR" ? "coverage-error" : "coverage-ready"}>{row.state === "ERROR" ? "异常" : "已核对"}</span></header>{row.error ? <div className="coverage-message">{row.error}</div> : <div className="coverage-items">{row.items.map(item => <div key={item.name}><b>{item.name}</b><span className={item.state === "READY" ? "ready" : "missing"}>{item.detail}</span></div>)}</div>}</article>)}</section>;
}

function SetupPrompt({ onConfigure }: { onConfigure: () => void }) {
  return <section className="setup-prompt"><div><p className="eyebrow">开始使用</p><h2>先添加一个只读账户</h2><p>连接交易所 API 或公开钱包地址后，系统会自动同步持仓、权益和风险数据；不会提供下单能力。</p></div><button className="primary" onClick={onConfigure}>添加账户 <span>→</span></button></section>;
}

function Overview({ data, refresh, accountId, accountOptions, onAccountChange, onConfigure }: { data: DashboardData; refresh: () => void; accountId: string; accountOptions: AccountItem[]; onAccountChange: (accountId: string) => void; onConfigure: () => void }) {
  const overview = data.overview;
  const equityRequest = useRequest(() => api.equity("30d", scopedAccount(accountId)), [accountId]);
  const updated = overview.updated_at ? new Date(overview.updated_at).toLocaleString("zh-CN", { hour12: false }) : "等待同步";
  const allocations = data.net_exposure.map(row => ({ asset: String(row.asset ?? ""), value: Math.abs(Number(row.gross_notional ?? 0)) }));
  const largest = allocations.reduce((top, row) => row.value > top.value ? row : top, { asset: "—", value: 0 });
  const allocationTotal = allocations.reduce((sum, row) => sum + row.value, 0) || 1;
  const perpetuals = data.positions.filter(row => row.contract_type === "PERPETUAL");
  const dangerous = perpetuals.filter(row => ["DANGER", "CRITICAL"].includes(row.risk_level)).length;
  const nearest = perpetuals.reduce((minimum, row) => Math.min(minimum, Number(row.liquidation_distance_percent ?? Infinity)), Infinity);
  return <><header className="topbar"><div><p className="eyebrow"><i className="live" />实时同步</p><h1>资产总览</h1><p>最后更新：{updated}</p></div><div><button className="refresh" onClick={refresh}>↻ 刷新数据</button><select className="selector" aria-label="账户范围" value={accountId} onChange={event => onAccountChange(event.target.value)} disabled={!accountOptions.length}><option value="all">全部账户</option>{accountOptions.map(account => <option value={account.id} key={account.id}>{account.name} · {account.exchange}</option>)}</select></div></header>{!data.connections.length && <SetupPrompt onConfigure={onConfigure} />}<section className="overview-hero"><article className="portfolio-summary"><p className="eyebrow">PORTFOLIO VALUE</p><h2>总资产</h2><strong>{money(overview.account_equity)} <small>USDT</small></strong><p className="updated-label">已汇总可计价资产 · {updated}</p><div className="summary-stats"><div><span>可用资金</span><b>{money(overview.available_balance)}</b></div><div><span>未实现盈亏</span><b className={Number(overview.unrealized_pnl) >= 0 ? "positive" : "negative"}>{signed(overview.unrealized_pnl)} USDT</b></div><div><span>有效杠杆</span><b>{fmt(overview.effective_leverage)}×</b></div></div></article>{equityRequest.state.status === "ready" ? <EquityChart history={equityRequest.state.data} /> : <section className="hero-chart"><div><p className="eyebrow">EQUITY TREND</p><h2>近 30 天权益</h2></div><RequestFeedback state={equityRequest.state} loadingText="正在读取权益趋势…" onRetry={equityRequest.retry} /></section>}</section><section className="overview-secondary"><AssetAllocation rows={data.net_exposure} /><section className="panel risk-summary"><header><div><p className="eyebrow">RISK SUMMARY</p><h2>风险摘要</h2></div><span className={`risk ${dangerous ? "danger" : "safe"}`}>{dangerous ? "需要处理" : "状态正常"}</span></header><div className="risk-summary-list"><div><span>杠杆仓位</span><b>{perpetuals.length} 个</b><small>{perpetuals.length ? `名义价值 ${money(overview.total_position_notional)}` : "当前没有合约敞口"}</small></div><div><span>强平风险</span><b className={dangerous ? "negative" : "positive"}>{dangerous ? `${dangerous} 个高风险` : "低"}</b><small>{Number.isFinite(nearest) ? `最近强平距离 ${fmt(String(nearest))}%` : "无强平价格需要监控"}</small></div><div><span>最大资产配置</span><b>{largest.asset} {pct(largest.value / allocationTotal * 100)}</b><small>按当前可计价资产市值计算</small></div></div></section><Accounts accounts={data.accounts as Row[]} connections={data.connections as Row[]} /></section><section className="overview-tables"><AssetBalances rows={data.positions} /><ContractPositions rows={data.positions} /></section></>;
}

function PositionsPage({ data }: { data: DashboardData }) {
  const perpetuals = data.positions.filter(row => row.contract_type === "PERPETUAL");
  const balances = data.positions.filter(row => row.contract_type !== "PERPETUAL");
  const assetValue = balances.reduce((sum, row) => sum + Number(row.position_value || 0), 0);
  const perpetualValue = perpetuals.reduce((sum, row) => sum + Number(row.position_value || 0), 0);
  return <section className="page page-shell"><div className="page-heading"><div><p className="eyebrow">PORTFOLIO INVENTORY</p><h1>统一持仓</h1><p>资产余额与合约仓位分开呈现，避免把现货套进合约字段。</p></div><span className="page-note">只显示可计价资产</span></div><section className="position-kpis"><article><span>资产余额</span><b>{balances.length} 项</b><small>{money(String(assetValue))} USD 价值</small></article><article><span>合约仓位</span><b>{perpetuals.length} 个</b><small>{money(String(perpetualValue))} 名义价值</small></article><article><span>未实现盈亏</span><b className={Number(data.overview.unrealized_pnl) >= 0 ? "positive" : "negative"}>{signed(data.overview.unrealized_pnl)}</b><small>仅合约仓位计入</small></article></section><section className="overview-tables"><AssetBalances rows={data.positions} /><ContractPositions rows={data.positions} /></section></section>;
}

function ExposurePage({ data }: { data: DashboardData }) {
  const total = data.net_exposure.reduce((sum, row) => sum + Math.abs(Number(row.gross_notional ?? 0)), 0);
  const perpetuals = data.positions.filter(row => row.contract_type === "PERPETUAL");
  return <section className="page page-shell"><div className="page-heading"><div><p className="eyebrow">RISK EXPOSURE</p><h1>风险敞口</h1><p>按可计价资产市值汇总；合约方向仅在存在杠杆仓位时单独展示。</p></div><span className="page-note">总市值 {money(String(total))}</span></div><section className="exposure-page-grid"><Exposure rows={data.net_exposure} /><section className="panel exposure-context"><p className="eyebrow">POSITION CONTEXT</p><h2>仓位语境</h2><div><span>活跃合约</span><b>{perpetuals.length} 个</b></div><div><span>有效杠杆</span><b>{fmt(data.overview.effective_leverage)}×</b></div><div><span>可用资金</span><b>{money(data.overview.available_balance)}</b></div><p>现货、链上原生币和稳定币不显示虚假的强平风险。</p></section></section><AssetAllocation rows={data.net_exposure} /></section>;
}

function Settings({ reload }: { reload: () => void }) {
  const [form, setForm] = useState<Record<string, string>>({ exchange: "hyperliquid", name: "主账户", public_identifier: "", api_key: "", api_secret: "", passphrase: "", product_type: "USDT-FUTURES" }); const [message, setMessage] = useState("");
  const [accounts, setAccounts] = useState<Awaited<ReturnType<typeof api.accounts>>>([]); const [draftNames, setDraftNames] = useState<Record<string, string>>({}); const [savingId, setSavingId] = useState("");
  const privateExchange = form.exchange === "binance" || form.exchange === "bitget";
  const requiresIdentifier = ["hyperliquid", "lighter", "bitcoin", "ethereum", "arbitrum", "solana"].includes(form.exchange);
  const loadAccounts = async () => { try { const rows = await api.accounts(); setAccounts(rows); setDraftNames(Object.fromEntries(rows.map(row => [row.id, row.name]))); } catch { setMessage("账户列表读取失败，请刷新后重试。"); } };
  useEffect(() => { void loadAccounts(); }, []);
  const save = async (event: FormEvent) => { event.preventDefault(); if (!form.name.trim()) { setMessage("请填写账户名称。"); return; } if (requiresIdentifier && !form.public_identifier.trim()) { setMessage("请填写公开地址或账户标识后再保存。"); return; } if (privateExchange && (!form.api_key.trim() || !form.api_secret.trim())) { setMessage("请填写只读 API Key 和 API Secret 后再保存。"); return; } try { await api.createAccount(form); setMessage("账户已加密保存，正在等待首次快照。"); await loadAccounts(); reload(); } catch (error) { setMessage(`保存失败：${requestMessage(error)}`); } };
  const rename = async (id: string) => { const name = (draftNames[id] ?? "").trim(); if (!name) { setMessage("账户名称不能为空。"); return; } setSavingId(id); try { const updated = await api.renameAccount(id, name); setAccounts(rows => rows.map(row => row.id === id ? updated : row)); setDraftNames(names => ({ ...names, [id]: updated.name })); setMessage("账户名称已保存；下一次同步会同时更新仪表盘中的名称。"); reload(); } catch (error) { setMessage(`修改失败：${String(error)}`); } finally { setSavingId(""); } };
  return <section className="page"><p className="eyebrow">ACCOUNTS</p><h1>账户配置</h1><p>只接受只读凭据，系统不提供任何下单能力。</p><section className="panel managed-accounts"><header><div><p className="eyebrow">SAVED ACCOUNTS</p><h2>已添加账户</h2></div><span className="mini-chip">可直接改名</span></header>{accounts.length ? <div className="managed-account-list">{accounts.map(account => <div className="managed-account" key={account.id}><div><b>{account.exchange}</b><small>{account.public_identifier ? "公开地址 / API 配置保持不变" : "仅修改显示名称"}</small></div><input aria-label={`${account.name} 的账户名称`} value={draftNames[account.id] ?? account.name} maxLength={128} onChange={event => setDraftNames(names => ({ ...names, [account.id]: event.target.value }))} /><button className="refresh" disabled={savingId === account.id || (draftNames[account.id] ?? account.name).trim() === account.name} onClick={() => void rename(account.id)}>{savingId === account.id ? "保存中…" : "保存名称"}</button></div>)}</div> : <Empty text="尚未添加账户。" />}</section><form className="settings" onSubmit={save}><label>交易所 / 链<select value={form.exchange} onChange={event => setForm({ ...form, exchange: event.target.value })}>{["hyperliquid", "lighter", "binance", "bitget", "bitcoin", "ethereum", "arbitrum", "solana"].map(item => <option key={item}>{item}</option>)}</select></label><label>账户名称<input value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></label><label>{form.exchange === "hyperliquid" ? "公开钱包 / Vault 地址" : form.exchange === "lighter" ? "账户索引或 L1 地址" : ["bitcoin","ethereum","arbitrum","solana"].includes(form.exchange) ? "公开链上地址" : "账户标识（可选）"}<input value={form.public_identifier} onChange={event => setForm({ ...form, public_identifier: event.target.value })} /></label>{privateExchange && <><label>只读 API Key<input value={form.api_key} onChange={event => setForm({ ...form, api_key: event.target.value })} /></label><label>只读 API Secret<input type="password" value={form.api_secret} onChange={event => setForm({ ...form, api_secret: event.target.value })} /></label>{form.exchange === "bitget" && <label>Passphrase<input type="password" value={form.passphrase} onChange={event => setForm({ ...form, passphrase: event.target.value })} /></label>}</>}<button className="primary">加密保存账户 <span>→</span></button>{message && <div className="notice">{message}</div>}</form></section>;
}

function EquityHistoryCard({ history }: { history: EquityHistory | null }) {
  if (!history) return <section className="panel"><Empty text="正在读取净值历史…" /></section>;
  const latest = history.points.at(-1); const values = history.points.map(point => Number(point.equity)); const high = Math.max(...values, 1);
  return <section className="panel"><header><div><p className="eyebrow">EQUITY HISTORY</p><h2>净值历史</h2></div><span className="mini-chip">{history.data_complete ? "快照完整" : "存在数据缺口"}</span></header>{latest ? <><strong className={Number(history.change) >= 0 ? "positive" : "negative"}>{fmt(latest.equity)} USDT</strong><p className="history-change">区间权益变化：{signed(history.change)} USDT</p><div className="history-bars">{history.points.map(point => <i key={point.at} title={`${point.at.slice(0,10)} · ${fmt(point.equity)} USDT`} style={{height:`${Math.max(5,Number(point.equity)/high*100)}%`}} className={point.complete ? "" : "partial"} />)}</div></> : <Empty text="尚无快照；系统会从现在开始按 5 分钟保存净值。" />}</section>;
}

function PnlPage({ positions }: { positions: Position[] }) {
  const [range, setRange] = useState("7d"); const [pnl, setPnl] = useState<PnlData | null>(null);
  const [equity, setEquity] = useState<EquityHistory | null>(null);
  useEffect(() => { api.pnl(range).then(setPnl).catch(() => setPnl(null)); }, [range]);
  useEffect(() => { api.equity(range === "1d" ? "7d" : range).then(setEquity).catch(() => setEquity(null)); }, [range]);
  return <section className="page"><div className="page-heading"><div><p className="eyebrow">PERFORMANCE</p><h1>盈亏分析</h1><p>基于已同步的交易、资金费与手续费账本。</p></div><select value={range} onChange={event => setRange(event.target.value)}><option value="1d">今日</option><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="all">全部时间</option></select></div>{pnl ? <><section className="metric-grid"><Metric label="已实现盈亏" value={pnl.realized_pnl} kind={Number(pnl.realized_pnl) >= 0 ? "gain" : "loss"} detail="已关闭仓位" mark="↗" /><Metric label="资金费" value={pnl.funding_pnl} kind={Number(pnl.funding_pnl) >= 0 ? "gain" : "loss"} detail="资金费收支" mark="⌁" /><Metric label="交易手续费" value={pnl.trading_fee} kind="loss" detail="已记录手续费" mark="▦" /><Metric label="净交易盈亏" value={pnl.net_trading_pnl} kind={Number(pnl.net_trading_pnl) >= 0 ? "gain" : "loss"} detail="不含账户余额变化" mark="◔" /></section>{!pnl.data_complete && <div className="notice">部分交易所历史数据尚未完整同步，系统不会用权益变化伪造盈亏。</div>}</> : <Empty text="正在读取历史账本…" />}<Positions rows={positions} /></section>;
}

function Empty({ text }: { text: string }) { return <div className="empty"><span aria-hidden>◇</span><p>{text}</p></div>; }

function AttributionPanel({ accountId }: { accountId: string }) {
  const [range,setRange]=useState("30d"); const attributionRequest=useRequest(()=>api.attribution(range,scopedAccount(accountId)),[range,accountId]);
  const table=(title:string,rows:PnlAttribution["by_exchange"]) => <section className="panel attribution-table"><h2>{title}</h2>{rows.length ? <div className="table-scroll"><table><thead><tr><th>维度</th><th>已实现</th><th>资金费</th><th>手续费</th><th>净交易盈亏</th></tr></thead><tbody>{rows.slice(0,8).map(row=><tr key={row.name}><td><b>{row.name}</b></td><td>{signed(row.realized_pnl)}</td><td>{signed(row.funding_pnl)}</td><td className="negative">-{fmt(row.trading_fee)}</td><td className={Number(row.net_trading_pnl)>=0?"positive":"negative"}>{signed(row.net_trading_pnl)}</td></tr>)}</tbody></table></div> : <Empty text="该区间尚无可归因的账本记录。" />}</section>;
  return <section className="page attribution-page"><div className="page-heading"><div><p className="eyebrow">PNL ATTRIBUTION</p><h1>盈亏归因</h1><p>仅归因已同步的成交、资金费和手续费；充值提现不计入交易盈亏。</p></div><select value={range} onChange={event=>setRange(event.target.value)}><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="all">全部历史</option></select></div>{attributionRequest.state.status === "ready" ? <><div className="attribution-grid">{table("按交易所",attributionRequest.state.data.by_exchange)}{table("按账户",attributionRequest.state.data.by_account)}</div>{table("按资产 / 合约",attributionRequest.state.data.by_asset)}<div className="performance-notes">数据完整性说明：{attributionRequest.state.data.missing.join(" ")}</div></> : <RequestFeedback state={attributionRequest.state} loadingText="正在读取归因账本…" onRetry={attributionRequest.retry} />}</section>;
}

function HistoricalSnapshotPanel({ accountId }: { accountId: string }) {
  const [at,setAt]=useState(()=>new Date().toISOString().slice(0,16)); const [requestedAt,setRequestedAt]=useState<string|null>(null);
  const historicalRequest=useRequest(()=>api.historical(new Date(requestedAt ?? at).toISOString(),scopedAccount(accountId)),[requestedAt,accountId]);
  const load=()=>setRequestedAt(at);
  return <section className="page attribution-page"><div className="page-heading"><div><p className="eyebrow">HISTORICAL RECONCILIATION</p><h1>历史资产对账</h1><p>返回所选时刻之前最近的完整账户快照。</p></div><div className="history-controls"><input type="datetime-local" value={at} onChange={event=>setAt(event.target.value)} /><button className="refresh" onClick={load}>查询快照</button></div></div>{!requestedAt ? <div className="performance-notes">选择时间后查询。完整快照从部署本版本后的新采样开始累积。</div> : historicalRequest.state.status === "ready" ? <section className="panel snapshot-table"><header><div><p className="eyebrow">SNAPSHOT</p><h2>{historicalRequest.state.data.data_complete ? "账户快照完整" : "部分账户缺少快照"}</h2></div><span className="mini-chip">{historicalRequest.state.data.accounts.length} 个账户</span></header>{historicalRequest.state.data.accounts.length ? <div className="table-scroll"><table><thead><tr><th>账户</th><th>交易所</th><th>快照时间</th><th>权益</th><th>可用余额</th><th>持仓数</th></tr></thead><tbody>{historicalRequest.state.data.accounts.map(row=><tr key={row.account_id}><td><b>{row.summary.account_name}</b></td><td>{row.summary.exchange}</td><td>{new Date(row.captured_at).toLocaleString("zh-CN",{hour12:false})}</td><td>{fmt(row.summary.account_equity)} USDT</td><td>{fmt(row.summary.available_balance)} USDT</td><td>{row.positions.length}</td></tr>)}</tbody></table></div> : <Empty text="该时间之前尚无完整快照。" />}{historicalRequest.state.data.missing_account_ids.length>0 && <div className="performance-notes">缺少快照的账户数：{historicalRequest.state.data.missing_account_ids.length}</div>}</section> : <RequestFeedback state={historicalRequest.state} loadingText="正在查询历史快照…" onRetry={historicalRequest.retry} />}</section>;
}

function PerformancePage({ positions, accountId }: { positions: Position[]; accountId: string }) {
  const [range, setRange] = useState("30d"); const pnlRequest=useRequest(()=>api.pnl(range === "90d" ? "all" : range,scopedAccount(accountId)),[range,accountId]); const equityRequest=useRequest(()=>api.equity(range,scopedAccount(accountId)),[range,accountId]);
  const equity=equityRequest.state.status === "ready" ? equityRequest.state.data : null; const pnl=pnlRequest.state.status === "ready" ? pnlRequest.state.data : null; const points=equity?.points ?? []; const values=points.map(point=>Number(point.equity)); const hasHistory=points.length>=2; const latest=values.at(-1) ?? 0; const previous=values.at(-2) ?? latest; const peak=hasHistory ? Math.max(...values) : 0; const drawdown=hasHistory && peak>0 ? (latest-peak)/peak*100 : null; const max=Math.max(...values,1);
  return <section className="page"><div className="page-heading"><div><p className="eyebrow">PERFORMANCE</p><h1>盈亏分析</h1><p>净值来自已保存的账户快照；交易盈亏仅来自已同步账本。</p></div><select value={range} onChange={event=>setRange(event.target.value)}><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="all">全部历史</option></select></div><div className="performance-grid"><section className="panel equity-chart"><header><div><p className="eyebrow">EQUITY HISTORY</p><h2>账户净值</h2></div><span className="mini-chip">{equity?.data_complete ? "快照完整" : "存在数据缺口"}</span></header>{equityRequest.state.status === "ready" ? points.length ? <><strong className={Number(equity!.change) >= 0 ? "positive" : "negative"}>{fmt(String(latest))} USDT</strong><p>区间权益变化 {signed(equity!.change)} USDT</p><div className="equity-bars">{points.map(point=><i key={point.at} className={point.complete ? "" : "partial"} title={`${point.at.slice(0,10)} · ${fmt(point.equity)} USDT`} style={{height:`${Math.max(4,Number(point.equity)/max*100)}%`}} />)}</div><div className="equity-foot"><span>{points[0].at.slice(0,10)}</span><span>{points.at(-1)?.at.slice(0,10)}</span></div></> : <Empty text="尚无快照。系统会从现在开始每 5 分钟保存净值。" /> : <RequestFeedback state={equityRequest.state} loadingText="正在读取净值历史…" onRetry={equityRequest.retry} />}</section><aside className="performance-summary"><article><label>最近日权益变化</label><b className={hasHistory && latest-previous<0 ? "negative" : "positive"}>{hasHistory ? `${signed(String(latest-previous))} USDT` : "—"}</b><small>{hasHistory ? "相邻快照的权益变化，包含出入金和价格波动" : "至少需要两条净值快照后计算"}</small></article><article><label>历史回撤</label><b className={drawdown !== null && drawdown < 0 ? "negative" : "plain-value"}>{drawdown === null ? "—" : `${fmt(String(drawdown))}%`}</b><small>{drawdown === null ? "净值历史不足，暂不计算回撤" : "以所选区间最高净值计算，出入金会影响结果"}</small></article><article><label>已记录出入金</label><b>{pnl ? `${fmt(pnl.deposit_withdrawal)} USDT` : "—"}</b><small>{pnl ? "来自已同步账本，不完整时会提示" : "账本加载完成后显示"}</small></article></aside></div>{pnlRequest.state.status === "ready" ? <><section className="metric-grid"><Metric label="已实现盈亏" value={pnlRequest.state.data.realized_pnl} kind={Number(pnlRequest.state.data.realized_pnl)>=0?"gain":"loss"} detail="已同步成交账本" mark="↗" /><Metric label="资金费" value={pnlRequest.state.data.funding_pnl} kind={Number(pnlRequest.state.data.funding_pnl)>=0?"gain":"loss"} detail="已同步资金费" mark="⌁" /><Metric label="交易手续费" value={pnlRequest.state.data.trading_fee} kind="loss" detail="已同步手续费" mark="▣" /><Metric label="净交易盈亏" value={pnlRequest.state.data.net_trading_pnl} kind={Number(pnlRequest.state.data.net_trading_pnl)>=0?"gain":"loss"} detail="不含余额变动" mark="◔" /></section>{!pnlRequest.state.data.data_complete && <div className="performance-notes">数据完整性说明：<ul>{pnlRequest.state.data.missing.map(note=><li key={note}>{note}</li>)}</ul></div>}</> : <RequestFeedback state={pnlRequest.state} loadingText="正在读取交易账本…" onRetry={pnlRequest.retry} />}<Positions rows={positions} /></section>;
}

function PnlWorkspace({ positions, accountId }: { positions: Position[]; accountId: string }) {
  const [section, setSection] = useState<"performance" | "attribution" | "history">("performance");
  const tabs: Array<[typeof section, string]> = [["performance", "收益概览"], ["attribution", "盈亏归因"], ["history", "历史对账"]];
  return <><nav className="pnl-sections" aria-label="盈亏分析分区" role="tablist">{tabs.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={section === key} className={section === key ? "active" : ""} onClick={() => setSection(key)}>{label}</button>)}</nav>{section === "performance" && <PerformancePage positions={positions} accountId={accountId} />}{section === "attribution" && <AttributionPanel accountId={accountId} />}{section === "history" && <HistoricalSnapshotPanel accountId={accountId} />}</>;
}

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null); const [page, setPage] = useState<Page>("overview"); const [error, setError] = useState(""); const [accountId, setAccountId] = useState("all"); const [accountOptions, setAccountOptions] = useState<AccountItem[]>([]); const [theme, setTheme] = useState<"light" | "dark">("light");
  const load = async (refresh = false) => { try { setData(await api.dashboard(refresh,scopedAccount(accountId))); setError(""); } catch (reason) { setError(requestMessage(reason)); } };
  useEffect(() => { void api.accounts().then(setAccountOptions).catch(() => setAccountOptions([])); }, []);
  useEffect(() => { void load(true); const timer = window.setInterval(() => { void load(false); }, 15000); return () => window.clearInterval(timer); }, [accountId]);
  useEffect(() => { const saved = window.localStorage.getItem("dashboard-theme"); if (saved === "dark") setTheme("dark"); }, []);
  useEffect(() => { document.documentElement.dataset.theme = theme; window.localStorage.setItem("dashboard-theme", theme); }, [theme]);
  if (error.includes("UNAUTHENTICATED")) return <Login done={() => load(true)} />;
  if (!data) return <main className="loading"><span /><p>{error ? "暂时无法读取仪表盘" : "正在建立只读数据连接…"}</p>{error && <button className="refresh" onClick={() => load(true)}>重试</button>}</main>;
  const configure = () => setPage("settings");
  let content: React.ReactNode = <Overview data={data} refresh={() => void load(true)} accountId={accountId} accountOptions={accountOptions} onAccountChange={setAccountId} onConfigure={configure} />;
  if (page === "positions") content = <PositionsPage data={data} />;
  if (page === "exposure") content = <ExposurePage data={data} />;
  if (page === "pnl") content = <PnlWorkspace positions={data.positions} accountId={accountId} />;
  if (page === "status") content = <section className="page"><p className="eyebrow">CONNECTIONS</p><h1>资产覆盖与核对</h1><p>总权益只汇总已读取且可计价的资产。</p>{data.connections.length ? <><Coverage rows={data.coverage ?? []} /><Accounts accounts={data.accounts as Row[]} connections={data.connections as Row[]} /></> : <SetupPrompt onConfigure={configure} />}</section>;
  if (page === "settings") content = <Settings reload={() => { void api.accounts().then(setAccountOptions).catch(() => undefined); void load(true); }} />;
  const connectionErrors = data.connections.filter(row => ["ERROR", "DISCONNECTED"].includes(String(row.state))).length;
  const healthText = !data.connections.length ? "尚未配置账户" : connectionErrors ? `${connectionErrors} 个账户异常` : "系统运行正常";
  return <main className="app"><Sidebar page={page} setPage={setPage} theme={theme} onThemeToggle={() => setTheme(value => value === "dark" ? "light" : "dark")} healthText={healthText} /><section className="workspace">{content}</section></main>;
}
