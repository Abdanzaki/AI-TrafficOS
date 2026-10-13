"use client";

import React from "react";
import Link from "next/link";
import { Shield, ArrowLeft } from "lucide-react";
import { CitizenChatWidget } from "@/components/citizen/CitizenChatWidget";

export default function CitizenPage() {
  return (
    <div className="min-h-screen bg-[#070B14] text-white flex flex-col">
      {/* Public Top Navbar */}
      <header className="border-b border-white/10 bg-[#0B1020]/80 backdrop-blur-md px-4 sm:px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="flex items-center gap-2 text-xs font-mono text-gray-400 hover:text-white transition-colors mr-4"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Home</span>
          </Link>
          <div className="flex items-center gap-2 font-bold text-sm tracking-wider">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-pulse" />
            <span className="text-white">AI TRAFFICOS</span>
            <span className="text-xs font-mono text-cyan-400 px-2 py-0.5 rounded-full bg-cyan-400/10 border border-cyan-400/20">
              CITIZEN PORTAL
            </span>
          </div>
        </div>

        <Link
          href="/login"
          className="text-xs font-mono px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 border border-white/10 transition-colors"
        >
          Operator Sign In
        </Link>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-4xl w-full mx-auto p-4 sm:p-8 flex flex-col justify-center">
        <div className="mb-6 text-center sm:text-left">
          <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-white mb-2">
            Municipal Traffic & Road Advisory
          </h1>
          <p className="text-sm text-gray-400 max-w-2xl leading-relaxed">
            Real-time verified public traffic conditions, active road obstruction advisories,
            and guidance for reporting street issues.
          </p>
        </div>

        <CitizenChatWidget className="h-[600px]" />
      </main>
    </div>
  );
}
