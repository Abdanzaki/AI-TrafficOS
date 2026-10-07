import type { Metadata } from "next";
import { Space_Grotesk, Inter } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/Providers";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap",
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI TrafficOS | Intelligent Traffic Management System",
  description:
    "AI TrafficOS is an AI-powered intelligent traffic management system. Phase 1 foundation and architecture.",
};


export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${spaceGrotesk.variable} ${inter.variable} dark`}
    >
      <body className="min-h-screen bg-ink text-text font-body antialiased flex flex-col selection:bg-accent/20 selection:text-accent">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
