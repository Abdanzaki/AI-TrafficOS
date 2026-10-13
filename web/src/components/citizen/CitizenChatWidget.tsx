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
      className={`flex flex-col bg-[#0E1528] border border-cyan-500/20 rounded-2xl overflow-hidden shadow-2xl ${className}`}
    >
      {/* Citizen Header */}
      <div className="px-4 py-3.5 bg-gradient-to-r from-[#0E1528] via-[#14203A] to-[#0E1528] border-b border-white/10 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-cyan-500/10 border border-cyan-500/30 flex items-center justify-center text-cyan-400">
            <Shield className="w-4 h-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white tracking-wide flex items-center gap-2">
              Citizen Traffic Information
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/30">
                Public Verified
              </span>
            </h2>
            <p className="text-[11px] text-gray-400">
              Live traffic flow, verified road advisories, and reporting guidance
            </p>
          </div>
        </div>
      </div>

      {/* Auth Note Banner if 401 */}
      {authNote && (
        <div
          data-testid="citizen-auth-banner"
          className="px-4 py-2 bg-amber-500/10 border-b border-amber-500/20 text-amber-300 text-xs flex items-center gap-2 font-mono"
        >
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{authNote}</span>
        </div>
      )}

      {/* Quick Suggestions Bar */}
      <div className="px-4 py-2.5 bg-white/[0.02] border-b border-white/5 flex items-center gap-2 overflow-x-auto scrollbar-none">
        <span className="text-[10px] text-gray-400 font-medium shrink-0 uppercase tracking-wider">
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
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs bg-white/5 hover:bg-white/10 text-gray-300 hover:text-white border border-white/10 transition-colors shrink-0 disabled:opacity-40"
            >
              <Icon className="w-3 h-3 text-cyan-400" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Messages Thread */}
      <div className="flex-1 min-h-[300px] max-h-[500px] overflow-y-auto p-4 space-y-3.5 bg-black/20">
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
                    ? "bg-cyan-500 text-black font-medium rounded-tr-xs"
                    : msg.isError
                    ? "bg-rose-500/10 border border-rose-500/30 text-rose-200 rounded-tl-xs"
                    : msg.refused
                    ? "bg-amber-500/10 border border-amber-500/30 text-amber-200 rounded-tl-xs"
                    : "bg-white/5 border border-white/10 text-gray-100 rounded-tl-xs"
                }`}
              >
                {/* Out of scope refusal badge */}
                {msg.refused && (
                  <div
                    data-testid="citizen-refusal-badge"
                    className="mb-1.5 flex items-center gap-1.5 text-[10px] font-mono font-semibold text-amber-400 uppercase tracking-wider"
                  >
                    <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                    <span>Out of Scope for Public Service</span>
                  </div>
                )}

                {/* Message Body */}
                <div className="whitespace-pre-wrap">{msg.content}</div>

                {/* Provenance Footer for Assistant Responses */}
                {!isUser && !msg.isError && msg.provenance && (
                  <div className="mt-2 pt-1.5 border-t border-white/10 flex items-center justify-between gap-2 text-[10px] font-mono text-gray-400">
                    <span
                      data-testid="citizen-provenance-tag"
                      className="px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 font-semibold"
                    >
                      {msg.provenance.toUpperCase()}
                    </span>
                    {msg.toolsUsed && msg.toolsUsed.length > 0 && (
                      <span className="truncate text-gray-500">
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
            className="flex items-center gap-2 text-xs text-cyan-400 font-mono px-3 py-2 rounded-xl bg-white/5 w-fit"
          >
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>Consulting verified traffic data…</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Composer */}
      <div className="p-3 bg-[#0B1020] border-t border-white/10">
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
            className="flex-1 bg-white/5 border border-white/10 focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/30 rounded-xl px-3.5 py-2.5 text-xs sm:text-sm text-white placeholder:text-gray-500 outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            data-testid="citizen-send-button"
            disabled={isLoading || !inputMessage.trim()}
            className="h-10 w-10 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-black flex items-center justify-center transition-all disabled:opacity-30 disabled:cursor-not-allowed shrink-0 font-bold"
            aria-label="Send query"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
        <p className="text-[10px] text-gray-500 text-center mt-2 font-mono">
          Public Roadway Information • Verified Municipal Data Only
        </p>
      </div>
    </div>
  );
};

export default CitizenChatWidget;
