import React from "react";
import Link from "next/link";

export const Footer: React.FC = () => {
  return (
    <footer className="mt-auto border-t border-white/10 bg-ink/60 py-10">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col md:flex-row items-center justify-between gap-6">
          <div className="flex flex-col items-center md:items-start gap-1">
            <div className="flex items-center gap-2">
              <span className="font-display font-bold text-text text-base">
                AI TrafficOS
              </span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20">
                Phase 1 Foundation
              </span>
            </div>
            <p className="text-xs text-muted max-w-md text-center md:text-left mt-1">
              Phase 1 foundation & architecture build. Intelligent traffic management capabilities will be phased in throughout Phases 2 through 11.
            </p>
          </div>

          <div className="flex items-center gap-6 text-sm text-muted">
            <Link
              href="/"
              className="hover:text-text transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
            >
              Home
            </Link>
            <Link
              href="/platform"
              className="hover:text-text transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
            >
              Platform Shell
            </Link>
            <a
              href="https://github.com/Abdanzaki/AI-TrafficOS"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-text transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded flex items-center gap-1.5"
            >
              <span>GitHub Repository</span>
              <svg
                className="w-3.5 h-3.5 opacity-70"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </a>
          </div>
        </div>

        <div className="mt-8 pt-6 border-t border-white/5 flex flex-col sm:flex-row items-center justify-between text-xs text-muted/80 gap-3">
          <p>© {new Date().getFullYear()} AI TrafficOS. Open architecture foundation.</p>
          <p className="font-mono text-[11px] text-muted/60">
            Next.js 15 App Router • React 19 • Tailwind CSS v4
          </p>
        </div>
      </div>
    </footer>
  );
};
