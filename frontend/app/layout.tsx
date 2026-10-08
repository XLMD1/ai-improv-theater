import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "雾港最后一夜 | AI 即兴剧场",
  description: "在没有固定剧本的雾港，决定故事的下一幕。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
