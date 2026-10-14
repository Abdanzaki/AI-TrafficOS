"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  Send,
  AlertCircle,
  HelpCircle,
  Car,
  AlertTriangle,
  FileText,
  Shield,
  RefreshCw,
  ExternalLink,
} from "lucide-react";
import {
  postCitizenChatMessage,
  CitizenAuthError,
  type CitizenChatMessage,
} from "@/lib/citizen";

export interface CitizenChatWidgetProps {
  className?: string;
  defaultOpen?: boolean;
}

const QUICK_SUGGESTIONS = [
  {
    label: "Traffic Overview",
    prompt: "How is traffic right now across the city?",
    icon: Car,
  },
  {
    label: "Road Hazards",
    prompt: "Are there any active road incidents or hazard notices?",
    icon: AlertTriangle,
  },
  {
    label: "Report a Hazard",
    prompt: "How do I report a traffic hazard or broken light?",
    icon: FileText,
  },
  {
    label: "Public Help",
    prompt: "What information can you provide?",
    icon: HelpCircle,
  },
];

export const CitizenChatWidget: React.FC<CitizenChatWidgetProps> = ({
  className = "",
}) => {
  const [messages, setMessages] = useState<CitizenChatMessage[]>([
    {
      id: "welcome-1",
      role: "assistant",
      content:
        "Welcome to the AI TrafficOS Public Information Service. You can check current road traffic conditions, view active road hazard notices, or get guidance on reporting municipal traffic issues.",
      timestamp: new Date().toISOString(),
      provenance: "observed",
      refused: false,
    },
  ]);
  const [inputMessage, setInputMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [authNote, setAuthNote] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleSendMessage = async (textToSend?: string) => {
    const text = (textToSend ?? inputMessage).trim();
    if (!text || isLoading) return;

    setInputMessage("");
    setAuthNote(null);

    const userMsg: CitizenChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      const response = await postCitizenChatMessage(text);
      const asstMsg: CitizenChatMessage = {
        id: `asst-${Date.now()}`,
        role: "assistant",
        content: response.answer,
        timestamp: new Date().toISOString(),
        provenance: response.provenance,
        toolsUsed: response.tools_used,
        refused: response.refused,
        confidence: response.confidence,
      };
      setMessages((prev) => [...prev, asstMsg]);
    } catch (err: unknown) {
      let errorMessage = "Unable to reach public traffic information. Please try again shortly.";
      if (err instanceof CitizenAuthError) {
        errorMessage = "Citizen portal authentication required. Please sign in or register for public access.";
        setAuthNote("Authentication required to query public traffic services.");
      }
      const errorMsg: CitizenChatMessage = {
        id: `err-${Date.now()}`,
        role: "assistant",
        content: errorMessage,
        timestamp: new Date().toISOString(),
        isError: true,
        errorMessage,
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div
      data-testid="citizen-chat-widget"
      className={`flex flex-col bg-surface border border-line rounded-2xl overflow-hidden shadow-[0_2px_8px_rgba(28,25,23,0.08)] ${className}`}
    >
      {/* Citizen Header */}
      <div className="px-4 py-3.5 bg-pine-deep bg-grid-civic-light border-b border-pine-ink/40 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-paper/10 border border-paper/25 flex items-center justify-center text-paper">
            <Shield className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-paper tracking-wide flex items-center gap-2">
              Citizen Traffic Information
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-paper/10 text-paper border border-paper/25">
                Public Verified
              </span>
            </h2>
            <p className="text-[11px] text-paper/70">
              Live traffic flow, verified road advisories, and reporting guidance
            </p>
          </div>
        </div>
      </div>

      {/* Auth Note Banner if 401 */}
      {authNote && (
        <div
          data-testid="citizen-auth-banner"
          className="px-4 py-2 bg-amber/10 border-b border-amber/20 text-amber text-xs flex items-center gap-2 font-mono"
        >
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{authNote}</span>
        </div>
      )}

      {/* Quick Suggestions Bar */}
      <div className="px-4 py-2.5 bg-cream/50 border-b border-line flex items-center gap-2 overflow-x-auto scrollbar-none">
        <span className="text-[10px] text-muted font-medium shrink-0 uppercase tracking-wider">
          Quick queries:
        </span>
        {QUICK_SUGGESTIONS.map((item, idx) => {
          const Icon = item.icon;
          return (
            <button
              key={idx}
              data-testid={`quick-suggestion-${idx}`}
              onClick={() => handleSendMessage(item.prompt)}
              disabled={isLoading}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs bg-paper hover:bg-cream text-text hover:text-ink border border-line transition-colors shrink-0 disabled:opacity-40"
            >
              <Icon className="w-3 h-3 text-accent" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Messages Thread */}
      <div className="flex-1 min-h-[300px] max-h-[500px] overflow-y-auto p-4 space-y-3.5 bg-cream/40">
        {messages.map((msg) => {
          const isUser = msg.role === "user";
          return (
            <div
              key={msg.id}
              data-testid={`citizen-message-${msg.role}`}
              className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-xs sm:text-sm leading-relaxed ${
                  isUser
                    ? "bg-pine text-paper font-medium rounded-tr-xs"
                    : msg.isError
                    ? "bg-danger/10 border border-danger/30 text-danger rounded-tl-xs"
                    : msg.refused
                    ? "bg-amber/10 border border-amber/30 text-accent-deep rounded-tl-xs"
                    : "bg-paper border border-line text-text rounded-tl-xs"
                }`}
              >
                {/* Out of scope refusal badge */}
                {msg.refused && (
                  <div
                    data-testid="citizen-refusal-badge"
                    className="mb-1.5 flex items-center gap-1.5 text-[10px] font-mono font-semibold text-amber uppercase tracking-wider"
                  >
                    <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                    <span>Out of Scope for Public Service</span>
                  </div>
                )}

                {/* Message Body */}
                <div className="whitespace-pre-wrap">{msg.content}</div>

                {/* Provenance Footer for Assistant Responses */}
                {!isUser && !msg.isError && msg.provenance && (
                  <div className="mt-2 pt-1.5 border-t border-line flex items-center justify-between gap-2 text-[10px] font-mono text-muted">
                    <span
                      data-testid="citizen-provenance-tag"
                      className="px-1.5 py-0.5 rounded bg-pine-tint text-pine-deep font-semibold"
                    >
                      {msg.provenance.toUpperCase()}
                    </span>
                    {msg.toolsUsed && msg.toolsUsed.length > 0 && (
                      <span className="truncate text-faint">
                        {msg.toolsUsed.join(", ")}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Loading Indicator */}
        {isLoading && (
          <div
            data-testid="citizen-loading-indicator"
            className="flex items-center gap-2 text-xs text-accent-deep font-mono px-3 py-2 rounded-xl bg-accent-tint w-fit"
          >
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>Consulting verified traffic data…</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Composer */}
      <div className="p-3 bg-cream/60 border-t border-line">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="flex items-center gap-2"
        >
          <input
            ref={inputRef}
            data-testid="citizen-chat-input"
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            placeholder="Ask about traffic conditions, road incidents, or reporting issues…"
            className="flex-1 bg-surface border border-line focus:border-accent/50 focus:ring-1 focus:ring-accent/30 rounded-xl px-3.5 py-2.5 text-xs sm:text-sm text-text placeholder:text-faint outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            data-testid="citizen-send-button"
            disabled={isLoading || !inputMessage.trim()}
            className="h-10 w-10 rounded-xl bg-accent hover:bg-accent-deep text-paper flex items-center justify-center transition-all disabled:opacity-30 disabled:cursor-not-allowed shrink-0 font-bold"
            aria-label="Send query"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
        <p className="text-[10px] text-faint text-center mt-2 font-mono">
          Public Roadway Information • Verified Municipal Data Only
        </p>
      </div>
    </div>
  );
};

export default CitizenChatWidget;
