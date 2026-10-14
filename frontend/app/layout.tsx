import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 即兴剧场 | 你的调查故事",
  description: "创建属于你的调查故事，保存每一段选择与分支。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
