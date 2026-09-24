import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host =
    requestHeaders.get("x-forwarded-host") ??
    requestHeaders.get("host") ??
    "localhost:5173";
  const protocol =
    requestHeaders.get("x-forwarded-proto") ??
    (host.startsWith("localhost") ? "http" : "https");

  return {
    metadataBase: new URL(protocol + "://" + host),
    title: "You Just Lead · Competition Training Agent",
    description:
      "面向模型训练与竞赛打榜的智能工作台：从规则、研究资料到训练框架，形成可确认的完整流程。",
    icons: {
      icon: "/favicon.svg",
      shortcut: "/favicon.svg",
    },
    openGraph: {
      title: "You Just Lead · Competition Training Agent",
      description: "规则、研究资料与训练框架的一体化竞赛工作台。",
      images: [{ url: "/og-workspace.png", width: 1728, height: 912 }],
    },
    twitter: {
      card: "summary_large_image",
      title: "You Just Lead · Competition Training Agent",
      description: "规则、研究资料与训练框架的一体化竞赛工作台。",
      images: ["/og-workspace.png"],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
