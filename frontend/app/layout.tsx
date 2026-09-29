import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AlphaMonitor",
  description: "Live Telegram calls and TokenScan feeds",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
