"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "../services/api";
import type { DashboardData, EquityHistory, HistoricalSnapshot, PnlAttribution, PnlData, Position } from "../types";

type Page = "overview" | "positions" | "exposure" | "pnl" | "status" | "settings";
type Row = Record<string, string | number | undefined>;

const nf = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 });
const fmt = (value?: string, short = false) => (short ? compact : nf).format(Number(value ?? 0) || 0);
const signed = (value?: string) => `${Number(value ?? 0) >= 0 ? "+" : ""}${fmt(value)}`;
const cnRisk = (risk?: string) => ({ SAFE: "低风险", WATCH: "留意", DANGER: "高风险", CRITICAL: "紧急" }[risk ?? ""] ?? "待确认");
const cnState = (state?: string) => ({ LIVE: "实时", CONNECTED: "已连接", WARNING: "延迟", STALE: "过期", DISCONNECTED: "断开", ERROR: "异常" }[state ?? ""] ?? "等待同步");
const icon = (symbol: string) => <span className="icon" aria-hidden>{symbol}</span>;

function Sidebar({ page, setPage }: { page: Page; setPage: (page: Page) => void }) {
  const nav: Array<[Page, string, string]> = [["overview", "总览", "▦"], ["positions", "持仓", "▤"], ["exposure", "风险敞口", "◔"], ["pnl", "盈亏分析", "↗"], ["status", "系统状态", "◌"], ["settings", "账户配置", "⚙"]];
  return <aside className="sidebar"><div className="brand"><b>◈</b><span>资金驾驶舱</span></div><small className="nav-caption">监控中心</small><nav>{nav.map(([key, label, mark]) => <button key={key} className={page === key ? "active" : ""} onClick={() => setPage(key)}>{icon(mark)}{label}</button>)}</nav><div className="health"><i />系统运行正常</div></aside>;
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
  const visible = rows.slice(0, 4); const colors = ["#2d76ec", "#17a49d", "#f1993b", "#8e98a7"];
  const total = visible.reduce((sum, row) => sum + Math.abs(Number(row.gross_notional ?? 0)), 0);
  const stops = visible.map((row, index) => `${colors[index]} ${Math.max(3, (Math.abs(Number(row.gross_notional ?? 0)) / (total || 1)) * 100)}%`).join(", ");
  return <section className="panel exposure"><header><div><p className="eyebrow">EXPOSURE</p><h2>全局敞口概览</h2></div><span className="mini-chip">按名义价值</span></header>{visible.length ? <div className="exposure-body"><div className="asset-list">{visible.map((row, index) => { const long = Number(row.long_notional ?? 0); const short = Number(row.short_notional ?? 0); const longPart = long + short ? long / (long + short) * 100 : 50; return <div className="asset-row" key={String(row.asset)}><strong><i style={{ background: colors[index] }} />{String(row.asset)}</strong><span className="split"><i className="long" style={{ width: `${longPart}%` }} /><i className="short" style={{ width: `${100 - longPart}%` }} /></span><b>{fmt(String(row.gross_notional), true)}</b><small>{fmt(String(Math.abs(Number(row.gross_notional ?? 0)) / (total || 1) * 100))}%</small></div>; })}<p className="legend"><span><i />多头</span><span><i />空头</span></p></div><div className="donut-area"><div className="donut" style={{ background: `conic-gradient(${stops})` }}><div><b>{fmt(String(total), true)}</b><small>USDT</small></div></div><small>总敞口</small></div></div> : <Empty text="配置账户后，跨平台敞口会在这里汇总。" />}</section>;
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
  const kind = (row: Position) => ({ PERPETUAL: "永续", SPOT: "现货", VAULT_EQUITY: "Vault", STAKING: "质押", ONCHAIN_NATIVE: "链上原生币", ERC20: "链上 ERC-20" }[row.contract_type ?? ""] ?? "资产");
  const unpriced = (row: Position) => row.contract_type !== "PERPETUAL" && !row.mark_price;
  return <section className="panel positions"><header><div><p className="eyebrow">POSITIONS</p><h2>统一持仓</h2></div><div className="filters"><input placeholder="搜索资产或平台" value={query} onChange={event => setQuery(event.target.value)} /><select value={side} onChange={event => setSide(event.target.value)}><option value="ALL">全部方向</option><option value="LONG">仅多头</option><option value="SHORT">仅空头</option></select></div></header>{list.length ? <div className="table-scroll"><table><thead><tr><th>资产 / 账户</th><th>方向</th><th>持仓规模</th><th>开仓均价</th><th>标记价格</th><th>未实现盈亏</th><th>强平距离</th><th>风险</th></tr></thead><tbody>{list.map((row, index) => <tr key={`${row.exchange}-${row.symbol}-${index}`}><td><b>{row.symbol}</b><small>{kind(row)} · {row.exchange} · {row.account_name}</small></td><td><span className={`side ${row.side === "LONG" ? "long" : "short"}`}>{row.side === "LONG" ? "多" : "空"}</span></td><td>{unpriced(row) ? "未报价" : fmt(row.position_value, true)}<small>{unpriced(row) ? "未计入总权益" : "USDT"}</small></td><td>{row.contract_type === "PERPETUAL" ? fmt(row.entry_price) : "—"}</td><td>{unpriced(row) ? "未报价" : fmt(row.mark_price)}</td><td className={Number(row.unrealized_pnl) >= 0 ? "positive" : "negative"}><b>{row.contract_type === "PERPETUAL" ? signed(row.unrealized_pnl) : "—"}</b><small>{row.contract_type === "PERPETUAL" ? "USDT" : ""}</small></td><td><span className="distance">{row.contract_type === "PERPETUAL" && row.liquidation_distance_percent ? `${fmt(row.liquidation_distance_percent)}%` : "—"}<i style={{ width: `${Math.min(100, Number(row.liquidation_distance_percent ?? 0) * 3)}%` }} /></span></td><td><span className={`risk ${row.risk_level === "SAFE" ? "safe" : row.risk_level === "WATCH" ? "watch" : "danger"}`}>{row.contract_type === "PERPETUAL" ? cnRisk(row.risk_level) : "—"}</span></td></tr>)}</tbody></table></div> : <Empty text="尚无可展示的资产。添加账户后会自动同步。" />}</section>;
}

function Accounts({ accounts, connections }: { accounts: Row[]; connections: Row[] }) {
  const rows = accounts.length ? accounts : connections;
  return <section className="panel accounts"><header><div><p className="eyebrow">CONNECTIONS</p><h2>账户状态</h2></div>{icon("◌")}</header>{rows.length ? rows.map((account, index) => { const matched = connections.find(connection => connection.account_id === account.account_id); const state = String(matched?.state ?? account.state ?? account.data_state ?? "CONNECTED"); const failure = String(matched?.error ?? account.error ?? ""); return <div className="account" key={String(account.account_id ?? index)}><span>{String(account.exchange ?? "?").slice(0, 1).toUpperCase()}</span><div><b>{String(account.account_name ?? account.name ?? account.exchange)}</b><p>{failure ? `同步失败：${failure}` : account.account_equity ? `${fmt(String(account.account_equity), true)} USDT` : "等待快照"}</p></div><em className={state.toLowerCase()}><i />{cnState(state)}</em></div>; }) : <Empty text="没有已连接账户。" />}</section>;
}

function Coverage({ rows }: { rows: DashboardData["coverage"] }) {
  return <section className="coverage-grid">{rows.map(row => <article className="coverage-card" key={row.account_id}><header><div><p className="eyebrow">ASSET COVERAGE</p><h2>{row.account_name}</h2><p>{row.exchange}</p></div><span className={row.state === "ERROR" ? "coverage-error" : "coverage-ready"}>{row.state === "ERROR" ? "异常" : "已核对"}</span></header>{row.error ? <div className="coverage-message">{row.error}</div> : <div className="coverage-items">{row.items.map(item => <div key={item.name}><b>{item.name}</b><span className={item.state === "READY" ? "ready" : "missing"}>{item.detail}</span></div>)}</div>}</article>)}</section>;
}

function Overview({ data, refresh }: { data: DashboardData; refresh: () => void }) {
  const overview = data.overview; return <><header className="topbar"><div><p className="eyebrow"><i className="live" />实时同步</p><h1>资产总览</h1><p>最后更新：{overview.updated_at ? new Date(overview.updated_at).toLocaleString("zh-CN", { hour12: false }) : "等待同步"}</p></div><div><button className="refresh" onClick={refresh}>↻ 刷新数据</button><button className="selector">主账户　⌄</button></div></header><section className="metric-grid"><Metric label="总权益" value={overview.account_equity} detail="当前可汇总账户权益" mark="▦" /><Metric label="可用保证金" value={overview.available_balance} detail="可用作风险缓冲" mark="◇" /><Metric label="未实现盈亏" value={overview.unrealized_pnl} kind={Number(overview.unrealized_pnl) >= 0 ? "gain" : "loss"} detail="所有活跃仓位合计" mark="⌁" /><Metric label="有效杠杆" value={overview.effective_leverage} unit="×" detail={`名义仓位 ${fmt(overview.total_position_notional, true)} USDT`} mark="◔" /></section><div className="top-grid"><Exposure rows={data.net_exposure} /><Radar positions={data.positions} /></div><div className="bottom-grid"><Positions rows={data.positions} /><Accounts accounts={data.accounts as Row[]} connections={data.connections as Row[]} /></div></>;
}

function Settings({ reload }: { reload: () => void }) {
  const [form, setForm] = useState<Record<string, string>>({ exchange: "hyperliquid", name: "主账户", public_identifier: "", api_key: "", api_secret: "", passphrase: "", product_type: "USDT-FUTURES" }); const [message, setMessage] = useState("");
  const privateExchange = form.exchange === "binance" || form.exchange === "bitget";
  const save = async (event: FormEvent) => { event.preventDefault(); try { await api.createAccount(form); setMessage("账户已加密保存，正在等待首次快照。"); reload(); } catch (error) { setMessage(`保存失败：${String(error)}`); } };
  return <section className="page"><p className="eyebrow">ACCOUNTS</p><h1>账户配置</h1><p>只接受只读凭据，系统不提供任何下单能力。</p><form className="settings" onSubmit={save}><label>交易所 / 链<select value={form.exchange} onChange={event => setForm({ ...form, exchange: event.target.value })}>{["hyperliquid", "lighter", "binance", "bitget", "bitcoin", "ethereum", "arbitrum"].map(item => <option key={item}>{item}</option>)}</select></label><label>账户名称<input value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></label><label>{form.exchange === "hyperliquid" ? "公开钱包 / Vault 地址" : form.exchange === "lighter" ? "账户索引或 L1 地址" : ["bitcoin","ethereum","arbitrum"].includes(form.exchange) ? "公开链上地址" : "账户标识（可选）"}<input value={form.public_identifier} onChange={event => setForm({ ...form, public_identifier: event.target.value })} /></label>{privateExchange && <><label>只读 API Key<input value={form.api_key} onChange={event => setForm({ ...form, api_key: event.target.value })} /></label><label>只读 API Secret<input type="password" value={form.api_secret} onChange={event => setForm({ ...form, api_secret: event.target.value })} /></label>{form.exchange === "bitget" && <label>Passphrase<input type="password" value={form.passphrase} onChange={event => setForm({ ...form, passphrase: event.target.value })} /></label>}</>}<button className="primary">加密保存账户 <span>→</span></button>{message && <div className="notice">{message}</div>}</form></section>;
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

function Empty({ text }: { text: string }) { return <div className="empty"><span>◌</span><p>{text}</p></div>; }

function AttributionPanel() {
  const [range,setRange]=useState("30d"); const [data,setData]=useState<PnlAttribution|null>(null);
  useEffect(()=>{api.attribution(range).then(setData).catch(()=>setData(null));},[range]);
  const table=(title:string,rows:PnlAttribution["by_exchange"]) => <section className="panel attribution-table"><h2>{title}</h2>{rows.length ? <table><thead><tr><th>维度</th><th>已实现</th><th>资金费</th><th>手续费</th><th>净交易盈亏</th></tr></thead><tbody>{rows.slice(0,8).map(row=><tr key={row.name}><td><b>{row.name}</b></td><td>{signed(row.realized_pnl)}</td><td>{signed(row.funding_pnl)}</td><td className="negative">-{fmt(row.trading_fee)}</td><td className={Number(row.net_trading_pnl)>=0?"positive":"negative"}>{signed(row.net_trading_pnl)}</td></tr>)}</tbody></table> : <Empty text="该区间尚无可归因的账本记录。" />}</section>;
  return <section className="page attribution-page"><div className="page-heading"><div><p className="eyebrow">PNL ATTRIBUTION</p><h1>盈亏归因</h1><p>仅归因已同步的成交、资金费和手续费；充值提现不计入交易盈亏。</p></div><select value={range} onChange={event=>setRange(event.target.value)}><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="all">全部历史</option></select></div>{data ? <><div className="attribution-grid">{table("按交易所",data.by_exchange)}{table("按账户",data.by_account)}</div>{table("按资产 / 合约",data.by_asset)}<div className="performance-notes">数据完整性说明：{data.missing.join(" ")}</div></> : <Empty text="正在读取归因账本…" />}</section>;
}

function HistoricalSnapshotPanel() {
  const [at,setAt]=useState(()=>new Date().toISOString().slice(0,16)); const [data,setData]=useState<HistoricalSnapshot|null>(null);
  const load=()=>api.historical(new Date(at).toISOString()).then(setData).catch(()=>setData(null));
  return <section className="page attribution-page"><div className="page-heading"><div><p className="eyebrow">HISTORICAL RECONCILIATION</p><h1>历史资产对账</h1><p>返回所选时刻之前最近的完整账户快照。</p></div><div className="history-controls"><input type="datetime-local" value={at} onChange={event=>setAt(event.target.value)} /><button className="refresh" onClick={load}>查询快照</button></div></div>{data ? <section className="panel snapshot-table"><header><div><p className="eyebrow">SNAPSHOT</p><h2>{data.data_complete ? "账户快照完整" : "部分账户缺少快照"}</h2></div><span className="mini-chip">{data.accounts.length} 个账户</span></header>{data.accounts.length ? <table><thead><tr><th>账户</th><th>交易所</th><th>快照时间</th><th>权益</th><th>可用余额</th><th>持仓数</th></tr></thead><tbody>{data.accounts.map(row=><tr key={row.account_id}><td><b>{row.summary.account_name}</b></td><td>{row.summary.exchange}</td><td>{new Date(row.captured_at).toLocaleString("zh-CN",{hour12:false})}</td><td>{fmt(row.summary.account_equity)} USDT</td><td>{fmt(row.summary.available_balance)} USDT</td><td>{row.positions.length}</td></tr>)}</tbody></table> : <Empty text="该时间之前尚无完整快照。" />}{data.missing_account_ids.length>0 && <div className="performance-notes">缺少快照的账户数：{data.missing_account_ids.length}</div>}</section> : <div className="performance-notes">选择时间后查询。完整快照从部署本版本后的新采样开始累积。</div>}</section>;
}

function PerformancePage({ positions }: { positions: Position[] }) {
  const [range, setRange] = useState("30d"); const [pnl, setPnl] = useState<PnlData | null>(null); const [equity, setEquity] = useState<EquityHistory | null>(null);
  useEffect(() => { api.pnl(range === "90d" ? "all" : range).then(setPnl).catch(() => setPnl(null)); api.equity(range).then(setEquity).catch(() => setEquity(null)); }, [range]);
  const points=equity?.points ?? []; const values=points.map(point=>Number(point.equity)); const latest=values.at(-1) ?? 0; const previous=values.at(-2) ?? latest; const peak=Math.max(...values,1); const drawdown=(latest-peak)/peak*100; const max=Math.max(...values,1);
  return <section className="page"><div className="page-heading"><div><p className="eyebrow">PERFORMANCE</p><h1>盈亏分析</h1><p>净值来自已保存的账户快照；交易盈亏仅来自已同步账本。</p></div><select value={range} onChange={event=>setRange(event.target.value)}><option value="7d">近 7 天</option><option value="30d">近 30 天</option><option value="90d">近 90 天</option><option value="all">全部历史</option></select></div><div className="performance-grid"><section className="panel equity-chart"><header><div><p className="eyebrow">EQUITY HISTORY</p><h2>账户净值</h2></div><span className="mini-chip">{equity?.data_complete ? "快照完整" : "存在数据缺口"}</span></header>{points.length ? <><strong className={Number(equity?.change) >= 0 ? "positive" : "negative"}>{fmt(String(latest))} USDT</strong><p>区间权益变化 {signed(equity?.change)} USDT</p><div className="equity-bars">{points.map(point=><i key={point.at} className={point.complete ? "" : "partial"} title={`${point.at.slice(0,10)} · ${fmt(point.equity)} USDT`} style={{height:`${Math.max(4,Number(point.equity)/max*100)}%`}} />)}</div><div className="equity-foot"><span>{points[0].at.slice(0,10)}</span><span>{points.at(-1)?.at.slice(0,10)}</span></div></> : <Empty text="尚无快照。系统会从现在开始每 5 分钟保存净值。" />}</section><aside className="performance-summary"><article><label>最近日权益变化</label><b className={latest-previous>=0 ? "positive" : "negative"}>{signed(String(latest-previous))} USDT</b><small>包含充值、提现与资产价格变化，不等同交易收益</small></article><article><label>历史回撤</label><b className={drawdown>=0 ? "positive" : "negative"}>{fmt(String(drawdown))}%</b><small>以所选区间最高净值计算，出入金会影响结果</small></article><article><label>已记录出入金</label><b>{fmt(pnl?.deposit_withdrawal)} USDT</b><small>来自已同步账本，不完整时会提示</small></article></aside></div>{pnl ? <><section className="metric-grid"><Metric label="已实现盈亏" value={pnl.realized_pnl} kind={Number(pnl.realized_pnl)>=0?"gain":"loss"} detail="已同步成交账本" mark="↗" /><Metric label="资金费" value={pnl.funding_pnl} kind={Number(pnl.funding_pnl)>=0?"gain":"loss"} detail="已同步资金费" mark="⌁" /><Metric label="交易手续费" value={pnl.trading_fee} kind="loss" detail="已同步手续费" mark="▣" /><Metric label="净交易盈亏" value={pnl.net_trading_pnl} kind={Number(pnl.net_trading_pnl)>=0?"gain":"loss"} detail="不含余额变动" mark="◔" /></section>{!pnl.data_complete && <div className="performance-notes">数据完整性说明：<ul>{pnl.missing.map(note=><li key={note}>{note}</li>)}</ul></div>}</> : <Empty text="正在读取交易账本…" />}<Positions rows={positions} /></section>;
}

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null); const [page, setPage] = useState<Page>("overview"); const [error, setError] = useState("");
  const load = async (refresh = false) => { try { setData(await api.dashboard(refresh)); setError(""); } catch (reason) { setError(String(reason)); } };
  useEffect(() => { load(true); const timer = window.setInterval(() => load(false), 15000); return () => window.clearInterval(timer); }, []);
  if (error.includes("UNAUTHENTICATED")) return <Login done={() => load(true)} />;
  if (!data) return <main className="loading"><span /><p>{error ? "暂时无法读取仪表盘" : "正在建立只读数据连接…"}</p>{error && <button className="refresh" onClick={() => load(true)}>重试</button>}</main>;
  let content: React.ReactNode = <Overview data={data} refresh={() => load(true)} />;
  if (page === "positions") content = <section className="page"><p className="eyebrow">POSITIONS</p><h1>统一持仓</h1><p>跨交易所的当前仓位、盈亏与强平距离。</p><Positions rows={data.positions} /></section>;
  if (page === "exposure") content = <section className="page"><p className="eyebrow">EXPOSURE</p><h1>风险敞口</h1><p>按资产合并多空名义价值，不隐式进行汇率换算。</p><Exposure rows={data.net_exposure} /></section>;
  if (page === "pnl") content = <><PerformancePage positions={data.positions} /><AttributionPanel /><HistoricalSnapshotPanel /></>;
  if (page === "status") content = <section className="page"><p className="eyebrow">CONNECTIONS</p><h1>资产覆盖与核对</h1><p>总权益只汇总已读取且可计价的资产。</p><Coverage rows={data.coverage ?? []} /><Accounts accounts={data.accounts as Row[]} connections={data.connections as Row[]} /></section>;
  if (page === "settings") content = <Settings reload={() => load(true)} />;
  return <main className="app"><Sidebar page={page} setPage={setPage} /><section className="workspace">{content}</section></main>;
}
