import "./globals.css";
import "./pnl.css";

export const metadata = {
  title: "资金驾驶舱",
  description: "只读多平台永续合约持仓与风险监控",
};

export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="zh-Hans"><body>{children}</body></html>;
}
