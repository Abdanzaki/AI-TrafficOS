"use client";

import React from "react";
import Link from "next/link";
import { Shield, ArrowLeft } from "lucide-react";
import { CitizenChatWidget } from "@/components/citizen/CitizenChatWidget";

export default function CitizenPage() {
  return (
    <div className="min-h-screen bg-paper text-text flex flex-col">
      {/* Public Top Navbar */}
      <header className="border-b border-line bg-pine-deep px-4 sm:px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-2 text-xs font-mono text-paper/70 hover:text-paper transition-colors mr-4"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Home</span>
          </Link>
          <div className="flex items-center gap-2 font-bold text-sm tracking-wider">
            <span className="w-2.5 h-2.5 rounded-full bg-accent animate-pulse" />
            <span className="text-paper">AI TRAFFICOS</span>
            <span className="text-xs font-mono text-paper px-2 py-0.5 rounded-full bg-paper/10 border border-paper/25">
              CITIZEN PORTAL
            </span>
          </div>
        </div>

        <Link
          href="/login"
          className="text-xs font-mono px-3 py-1.5 rounded-lg bg-paper/10 hover:bg-paper/15 text-paper border border-paper/25 transition-colors"
        >
          Operator Sign In
        </Link>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-4xl w-full mx-auto p-4 sm:p-8 flex flex-col justify-center">
        <div className="mb-6 text-center sm:text-left">
          <p className="text-[11px] uppercase tracking-[0.18em] font-semibold text-pine mb-2">
            Public Service
          </p>
          <h1 className="text-3xl sm:text-4xl font-display font-semibold tracking-tight text-text mb-2">
            Municipal Traffic &amp; Road Advisory
          </h1>
          <p className="text-sm text-muted max-w-2xl leading-relaxed">
            Real-time verified public traffic conditions, active road obstruction advisories,
            and guidance for reporting street issues.
          </p>
        </div>

        <CitizenChatWidget className="h-[600px]" />
      </main>
    </div>
  );
}
