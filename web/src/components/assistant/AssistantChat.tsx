"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import {
  Sparkles,
  Send,
  Plus,
  RefreshCw,
  AlertTriangle,
  ShieldAlert,
  Clock,
  Trash2,
  Menu,
  X,
  Database,
  ExternalLink,
  ChevronRight,
  Info,
} from "lucide-react";
import { useAuth } from "@/lib/auth";
import {
  postChatMessage,
  MarkdownRenderer,
  loadStoredConversationsIndex,
  loadStoredMessages,
  saveStoredConversation,
  deleteStoredConversation,
  AssistantAuthError,
  AssistantForbiddenError,
  AssistantTimeoutError,
  AssistantNetworkError,
  AssistantServerError,
  type ChatMessage,
  type ConversationSummary,
  type ToolCall,
  type ProvenanceSegment,
  type ChatHistoryEntry,
} from "@/lib/assistant";
import { formatDateTime, formatRelativeTime, formatTime } from "@/lib/format";

export interface AssistantChatProps {
  className?: string;
}

export const AssistantChat: React.FC<AssistantChatProps> = ({ className = "" }) => {
  const { user, logout } = useAuth();
  const userId = user?.id ? String(user.id) : "anonymous";
  const userRole = user?.role || "analyst";

  // Conversations & History State
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(false);

  // In-flight abort controller for timeouts / cancellation
  const abortControllerRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // Initialize or load conversation
  useEffect(() => {
    const list = loadStoredConversationsIndex(userId);
    setConversations(list);

    if (list.length > 0) {
      const firstId = list[0].id;
      setActiveConversationId(firstId);
      const stored = loadStoredMessages(userId, firstId);
      setMessages(stored);
    } else {
      const newId = `conv-${Date.now()}`;
      setActiveConversationId(newId);
      setMessages([]);
    }
  }, [userId]);

  // Scroll to bottom on new messages or loading change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  // Focus textarea when not loading
  useEffect(() => {
    if (!isLoading) {
      textareaRef.current?.focus();
    }
  }, [isLoading]);

  // Switch to an existing conversation
  const handleSelectConversation = useCallback(
    (id: string) => {
      setActiveConversationId(id);
      const loaded = loadStoredMessages(userId, id);
      setMessages(loaded);
      setSidebarOpen(false);
    },
    [userId]
  );

  // Create a new conversation
  const handleNewConversation = useCallback(() => {
    const newId = `conv-${Date.now()}`;
    setActiveConversationId(newId);
    setMessages([]);
    setInputMessage("");
    setSidebarOpen(false);
  }, []);

  // Delete a conversation
  const handleDeleteConversation = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation();
      deleteStoredConversation(userId, id);
      const updated = loadStoredConversationsIndex(userId);
      setConversations(updated);

      if (id === activeConversationId) {
        if (updated.length > 0) {
          handleSelectConversation(updated[0].id);
        } else {
          handleNewConversation();
        }
      }
    },
    [userId, activeConversationId, handleSelectConversation, handleNewConversation]
  );

  // Core send message handler
  const handleSendMessage = async (textToSend?: string) => {
    const content = (textToSend ?? inputMessage).trim();
    if (!content || isLoading) return;

    setInputMessage("");

    // Build user message
    const userMessage: ChatMessage = {
      id: `msg-user-${Date.now()}`,
      role: "user",
      content,
      timestamp: new Date().toISOString(),
      conversationId: activeConversationId,
    };

    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setIsLoading(true);

    // Save user message immediately to storage
    const currentConvTitle =
      conversations.find((c) => c.id === activeConversationId)?.title ||
      content.slice(0, 32) + (content.length > 32 ? "…" : "");

    saveStoredConversation(userId, {
      id: activeConversationId,
      title: currentConvTitle,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      messages: newMessages,
    });
    setConversations(loadStoredConversationsIndex(userId));

    // Prepare API history
    const historyPayload: ChatHistoryEntry[] = newMessages
      .filter((m) => !m.isError)
      .map((m) => ({
        role: m.role,
        content: m.content,
      }));
    // Exclude the current user prompt from history as it is sent as the message parameter
    historyPayload.pop();

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const response = await postChatMessage(
        content,
        historyPayload,
        activeConversationId,
        {
          signal: controller.signal,
        }
      );

      const assistantMessage: ChatMessage = {
        id: `msg-asst-${Date.now()}`,
        role: "assistant",
        content: response.answer,
        timestamp: new Date().toISOString(),
        conversationId: response.conversation_id || activeConversationId,
        toolCalls: response.tool_calls,
        provenance: response.provenance,
        insufficientData: response.insufficient_data,
        suggestedFollowups: response.suggested_followups,
      };

      const finalMessages = [...newMessages, assistantMessage];
      setMessages(finalMessages);

      // Persist assistant reply
      saveStoredConversation(userId, {
        id: activeConversationId,
        title: currentConvTitle,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        messages: finalMessages,
      });
      setConversations(loadStoredConversationsIndex(userId));
    } catch (err: unknown) {
      let errorType: "auth" | "forbidden" | "server" | "timeout" | "network" = "server";
      let errorMessage = "An error occurred while contacting the assistant.";

      if (err instanceof AssistantAuthError) {
        errorType = "auth";
        errorMessage = err.message || "Session expired. Please sign in again.";
      } else if (err instanceof AssistantForbiddenError) {
        errorType = "forbidden";
        errorMessage = `Access restricted: Role '${userRole}' is not authorized to perform this assistant query.`;
      } else if (err instanceof AssistantTimeoutError) {
        errorType = "timeout";
        errorMessage = err.message || "Request timed out after 60 seconds.";
      } else if (err instanceof AssistantNetworkError) {
        errorType = "network";
        errorMessage = err.message || "Network failure. Please check your connection.";
      } else if (err instanceof AssistantServerError) {
        errorType = "server";
        errorMessage = err.message || `Service error (${err.status}). Please try again.`;
      } else if (err instanceof Error && err.name === "AbortError") {
        errorType = "timeout";
        errorMessage = "Request was cancelled.";
      }

      const errorMessageObj: ChatMessage = {
        id: `msg-err-${Date.now()}`,
        role: "assistant",
        content: errorMessage,
        timestamp: new Date().toISOString(),
        conversationId: activeConversationId,
        isError: true,
        errorType,
        errorMessage,
      };

      const finalMessages = [...newMessages, errorMessageObj];
      setMessages(finalMessages);

      saveStoredConversation(userId, {
        id: activeConversationId,
        title: currentConvTitle,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        messages: finalMessages,
      });
      setConversations(loadStoredConversationsIndex(userId));
    } finally {
      setIsLoading(false);
      abortControllerRef.current = null;
    }
  };

  // Retry handler for retryable errors
  const handleRetry = () => {
    // Find the last user message and resend it
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        const text = messages[i].content;
        // Strip the trailing error message if any
        const cleanedMessages = messages.filter((_, idx) => idx < i);
        setMessages(cleanedMessages);
        handleSendMessage(text);
        return;
      }
    }
  };

  // Cancel in-flight request
  const handleCancelRequest = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setIsLoading(false);
  };

  // Composer keydown (Enter to send, Shift+Enter for newline)
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div
      data-testid="assistant-chat-panel"
      className={`flex h-full w-full bg-[#0B1020] text-text overflow-hidden rounded-2xl border border-white/10 shadow-2xl ${className}`}
    >
      {/* SIDEBAR: Recent Conversations */}
      <div
        className={`fixed inset-y-0 left-0 z-40 w-64 bg-[#0B1020]/95 backdrop-blur-md border-r border-white/10 flex flex-col transition-transform duration-300 md:static md:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        }`}
      >
        <div className="p-4 border-b border-white/10 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-[#00D9A8]" />
            <h2 className="font-display font-semibold text-sm tracking-tight text-text">
              Conversations
            </h2>
          </div>
          <button
            type="button"
            onClick={() => setSidebarOpen(false)}
            className="md:hidden p-1 text-muted hover:text-text rounded-lg"
            aria-label="Close conversations menu"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-3">
          <button
            type="button"
            data-testid="new-conversation-button"
            onClick={handleNewConversation}
            className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-xl bg-[#00D9A8]/10 hover:bg-[#00D9A8]/20 text-[#00D9A8] border border-[#00D9A8]/30 font-medium text-xs transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            <span>New Conversation</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
          {conversations.length === 0 ? (
            <p className="text-xs text-muted/60 text-center py-6">No saved chats</p>
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.id}
                role="button"
                tabIndex={0}
                data-testid={`conversation-item-${conv.id}`}
                onClick={() => handleSelectConversation(conv.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    handleSelectConversation(conv.id);
                  }
                }}
                className={`group flex items-center justify-between px-3 py-2.5 rounded-xl text-xs cursor-pointer transition-colors ${
                  conv.id === activeConversationId
                    ? "bg-white/10 text-text font-medium border border-white/10"
                    : "text-muted hover:text-text hover:bg-white/5"
                }`}
              >
                <div className="truncate flex-1 mr-2">
                  <div className="truncate">{conv.title || "Conversation"}</div>
                  <div className="text-[10px] text-muted/60 font-mono mt-0.5">
                    {formatRelativeTime(conv.updatedAt)}
                  </div>
                </div>
                <button
                  type="button"
                  data-testid={`delete-conversation-${conv.id}`}
                  onClick={(e) => handleDeleteConversation(e, conv.id)}
                  title="Delete conversation"
                  aria-label="Delete conversation"
                  className="opacity-0 group-hover:opacity-100 p-1 text-muted hover:text-[#FF4D6D] transition-opacity"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))
          )}
        </div>

        <div className="p-3 border-t border-white/10 text-[10px] text-muted/60 font-mono text-center">
          Persisted locally • Role: {userRole}
        </div>
      </div>

      {/* Backdrop for mobile sidebar */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-xs md:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* MAIN CHAT AREA */}
      <div className="flex-1 flex flex-col min-w-0 h-full">
        {/* Header Bar */}
        <div className="h-14 px-4 border-b border-white/10 flex items-center justify-between bg-[#0B1020]/80 backdrop-blur-sm shrink-0">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="md:hidden p-1.5 rounded-lg text-muted hover:text-text hover:bg-white/5"
              aria-label="Open conversation list"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-[#00D9A8]/15 border border-[#00D9A8]/30 flex items-center justify-center text-[#00D9A8]">
                <Sparkles className="w-4 h-4" />
              </div>
              <div>
                <h1 className="font-display font-semibold text-sm text-text leading-none">
                  AI Traffic Assistant
                </h1>
                <p className="text-[10px] text-muted font-mono mt-0.5">
                  Phase 9 Operational Reasoning
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleNewConversation}
              className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium text-muted hover:text-text bg-white/5 hover:bg-white/10 border border-white/10 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New</span>
            </button>
          </div>
        </div>

        {/* Message Stream */}
        <div
          data-testid="assistant-messages-container"
          className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6"
        >
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center max-w-md mx-auto py-12">
              <div className="w-12 h-12 rounded-2xl bg-[#00D9A8]/10 border border-[#00D9A8]/30 flex items-center justify-center text-[#00D9A8] mb-4 shadow-sm">
                <Sparkles className="w-6 h-6" />
              </div>
              <h3 className="font-display font-semibold text-base text-text">
                How can I assist traffic operations?
              </h3>
              <p className="text-xs text-muted mt-1.5 max-w-xs leading-relaxed">
                Query junction sensor telemetry, signal timings, incident flags, and supervisory
                AI decisions.
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-6 w-full text-left">
                {[
                  "What is the congestion status at Junction 1?",
                  "Are there any active emergency vehicles dispatched?",
                  "Show recent incident stalls reported today",
                  "Why was the green phase extended at Signal S-101?",
                ].map((sample, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleSendMessage(sample)}
                    className="p-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-[#00D9A8]/40 text-xs text-text/80 transition-all text-left"
                  >
                    {sample}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                data-testid={`chat-message-${msg.role}`}
                className={`flex w-full ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                {msg.role === "user" ? (
                  // USER MESSAGE
                  <div className="max-w-[85%] sm:max-w-[75%] rounded-2xl rounded-tr-xs bg-[#00D9A8]/15 border border-[#00D9A8]/30 p-4 text-text shadow-sm">
                    <p className="text-sm leading-relaxed whitespace-pre-wrap">{msg.content}</p>
                    <div className="mt-1.5 text-[10px] text-text/60 font-mono text-right">
                      {formatTime(msg.timestamp)}
                    </div>
                  </div>
                ) : (
                  // ASSISTANT MESSAGE
                  <div className="max-w-[95%] sm:max-w-[85%] rounded-2xl rounded-tl-xs bg-white/5 border border-white/10 p-4 sm:p-5 text-text shadow-md space-y-3">
                    {/* Assistant Message Header */}
                    <div className="flex items-center justify-between gap-2 pb-1 border-b border-white/5">
                      <div className="flex items-center gap-2">
                        <Sparkles className="w-4 h-4 text-[#00D9A8]" />
                        <span className="font-display font-medium text-xs text-text">
                          AI TrafficOS
                        </span>
                        {/* Amber outline badge on every assistant message */}
                        <span
                          data-testid="ai-generated-badge"
                          className="px-1.5 py-0.5 rounded text-[9px] font-mono font-medium border border-[#FFB800] text-[#FFB800] uppercase tracking-wider"
                        >
                          AI-generated
                        </span>
                      </div>
                      <span className="text-[10px] text-muted font-mono">
                        {formatTime(msg.timestamp)}
                      </span>
                    </div>

                    {/* Insufficient Data Warning Banner */}
                    {msg.insufficientData && (
                      <div
                        data-testid="insufficient-data-banner"
                        className="p-3 rounded-xl bg-[#FFB800]/10 border border-[#FFB800]/40 text-[#FFB800] text-xs flex items-start gap-2.5"
                      >
                        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                        <div>
                          <strong className="font-semibold block">Limited Data Warning</strong>
                          <span>
                            Telemetry or historical records were insufficient to form an exhaustive
                            recommendation. Please verify physical sensor feeds before executing
                            manual overrides.
                          </span>
                        </div>
                      </div>
                    )}

                    {/* Error State Displays */}
                    {msg.isError ? (
                      <div
                        data-testid="assistant-error-container"
                        data-error-type={msg.errorType}
                        className={`p-3.5 rounded-xl border text-xs space-y-2.5 ${
                          msg.errorType === "auth"
                            ? "bg-[#FFB800]/10 border-[#FFB800]/40 text-[#FFB800]"
                            : msg.errorType === "forbidden"
                            ? "bg-[#FF4D6D]/10 border-[#FF4D6D]/40 text-[#FF4D6D]"
                            : "bg-[#FF4D6D]/10 border-[#FF4D6D]/40 text-[#FF4D6D]"
                        }`}
                      >
                        <div className="flex items-start gap-2">
                          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                          <div className="flex-1">
                            <span className="font-semibold block">
                              {msg.errorType === "auth" && "Authentication Required"}
                              {msg.errorType === "forbidden" && "Permission Restricted"}
                              {msg.errorType === "timeout" && "Request Timed Out"}
                              {msg.errorType === "network" && "Network Connection Error"}
                              {msg.errorType === "server" && "Service Unavailable"}
                            </span>
                            <span className="text-text/90 leading-relaxed block mt-0.5">
                              {msg.errorMessage || msg.content}
                            </span>
                          </div>
                        </div>

                        {/* Action buttons per error type */}
                        <div className="pt-1 flex items-center gap-2">
                          {msg.errorType === "auth" && (
                            <button
                              type="button"
                              onClick={() => logout()}
                              className="px-3 py-1.5 rounded-lg bg-[#FFB800] text-black font-semibold text-xs hover:bg-[#FFB800]/90 transition-colors"
                            >
                              Sign In Again
                            </button>
                          )}

                          {msg.errorType === "forbidden" && (
                            <div className="text-[11px] text-text/80 font-mono">
                              Role <strong>{userRole}</strong> does not possess required scopes.
                            </div>
                          )}

                          {(msg.errorType === "server" ||
                            msg.errorType === "network" ||
                            msg.errorType === "timeout") && (
                            <button
                              type="button"
                              data-testid="error-retry-button"
                              onClick={handleRetry}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-text font-medium text-xs transition-colors border border-white/20"
                            >
                              <RefreshCw className="w-3.5 h-3.5" />
                              <span>Retry</span>
                            </button>
                          )}
                        </div>
                      </div>
                    ) : (
                      // Markdown content
                      <MarkdownRenderer content={msg.content} />
                    )}

                    {/* System Data: Tool Calls & Provenance Panel */}
                    {((msg.provenance && msg.provenance.length > 0) ||
                      (msg.toolCalls && msg.toolCalls.length > 0)) && (
                      <div
                        data-testid="system-data-panel"
                        className="mt-3 p-3.5 rounded-xl bg-[#00D9A8]/5 border border-[#00D9A8]/30 space-y-3"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 text-xs font-semibold text-[#00D9A8] font-display">
                            <Database className="w-3.5 h-3.5" />
                            <span>System Data & Provenance</span>
                          </div>
                        </div>

                        {/* Tool Calls if present */}
                        {msg.toolCalls && msg.toolCalls.length > 0 && (
                          <div className="space-y-1.5">
                            <div className="text-[10px] uppercase font-mono tracking-wider text-muted font-semibold">
                              Executed Tools ({msg.toolCalls.length})
                            </div>
                            <div className="space-y-1">
                              {msg.toolCalls.map((tc, idx) => (
                                <div
                                  key={idx}
                                  className="text-xs font-mono p-2 rounded-lg bg-black/40 border border-white/5 text-text/80"
                                >
                                  <div className="text-[#00D9A8] font-bold">{tc.tool}()</div>
                                  <div className="text-[11px] text-muted mt-0.5">
                                    {tc.result_summary}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Provenance segments */}
                        {msg.provenance && msg.provenance.length > 0 && (
                          <div className="space-y-2">
                            <div className="text-[10px] uppercase font-mono tracking-wider text-muted font-semibold">
                              Verified Claims & Data Labels
                            </div>
                            <div className="space-y-1.5">
                              {msg.provenance.map((p, idx) => (
                                <div
                                  key={idx}
                                  className="flex items-start justify-between gap-2 text-xs p-2 rounded-lg bg-black/30 border border-white/5"
                                >
                                  <span className="text-text/90 italic leading-relaxed">
                                    &ldquo;{p.segment}&rdquo;
                                  </span>
                                  {p.label === "observed" && (
                                    <span
                                      data-testid="provenance-chip-observed"
                                      className="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium bg-[#00D9A8]/15 text-[#00D9A8] border border-[#00D9A8]/30"
                                    >
                                      Observed
                                    </span>
                                  )}
                                  {p.label === "predicted" && (
                                    <span
                                      data-testid="provenance-chip-predicted"
                                      className="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium bg-[#FFB800]/15 text-[#FFB800] border border-[#FFB800]/30"
                                    >
                                      Predicted
                                    </span>
                                  )}
                                  {p.label === "recommended" && (
                                    <span
                                      data-testid="provenance-chip-recommended"
                                      className="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium bg-violet-500/15 text-violet-300 border border-violet-500/30"
                                    >
                                      Recommended
                                    </span>
                                  )}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Mandatory Provenance Legend */}
                        <div
                          data-testid="provenance-legend"
                          className="pt-2 border-t border-[#00D9A8]/20 text-[10px] font-mono text-muted/80 leading-relaxed"
                        >
                          <span className="text-[#00D9A8]">observed</span> = real DB/telemetry,{" "}
                          <span className="text-[#FFB800]">predicted</span> = ML forecast,{" "}
                          <span className="text-violet-300">recommended</span> = AI suggestion not a command
                        </div>
                      </div>
                    )}

                    {/* Suggested Followups */}
                    {msg.suggestedFollowups && msg.suggestedFollowups.length > 0 && (
                      <div className="pt-2">
                        <div className="text-[10px] text-muted font-mono mb-2 uppercase tracking-wider font-semibold">
                          Suggested Inquiries
                        </div>
                        <div className="flex flex-wrap gap-1.5">
                          {msg.suggestedFollowups.map((followup, idx) => (
                            <button
                              key={idx}
                              type="button"
                              data-testid={`suggested-followup-${idx}`}
                              disabled={isLoading}
                              onClick={() => handleSendMessage(followup)}
                              className="px-2.5 py-1 rounded-xl text-xs bg-white/5 hover:bg-white/10 text-text/90 border border-white/10 hover:border-[#00D9A8]/40 transition-colors text-left disabled:opacity-50"
                            >
                              {followup}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))
          )}

          {/* Honest Loading State: NO fake streaming */}
          {isLoading && (
            <div
              data-testid="assistant-thinking-indicator"
              className="flex justify-start"
            >
              <div className="rounded-2xl rounded-tl-xs bg-white/5 border border-white/10 p-4 flex items-center gap-3 text-xs text-text shadow-md">
                <div className="w-2.5 h-2.5 rounded-full bg-[#00D9A8] animate-ping" />
                <span className="font-mono text-xs text-text/80">Thinking…</span>
                <button
                  type="button"
                  onClick={handleCancelRequest}
                  className="ml-2 text-[10px] font-mono text-muted hover:text-[#FF4D6D] underline underline-offset-2"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Composer */}
        <div className="p-3 sm:p-4 border-t border-white/10 bg-[#0B1020]/95 shrink-0">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendMessage();
            }}
            className="flex items-end gap-2 max-w-4xl mx-auto"
          >
            <div className="flex-1 relative rounded-2xl bg-white/5 border border-white/10 focus-within:border-[#00D9A8]/50 focus-within:ring-1 focus-within:ring-[#00D9A8]/30 transition-all">
              <textarea
                ref={textareaRef}
                data-testid="assistant-composer-textarea"
                rows={2}
                disabled={isLoading}
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about live traffic, signals, congestion, or incident actions…"
                className="w-full resize-none bg-transparent p-3 text-xs sm:text-sm text-text placeholder:text-muted/60 focus:outline-none disabled:opacity-50 min-h-[44px] max-h-36"
              />
            </div>

            <button
              type="submit"
              data-testid="assistant-send-button"
              disabled={isLoading || !inputMessage.trim()}
              className="h-11 w-11 rounded-xl bg-[#00D9A8] text-black flex items-center justify-center hover:bg-[#00D9A8]/90 disabled:opacity-30 disabled:hover:bg-[#00D9A8] transition-all shrink-0 font-semibold shadow-md cursor-pointer disabled:cursor-not-allowed"
              aria-label="Send message"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
          <div className="text-[10px] text-muted/50 text-center mt-2 font-mono">
            Press Enter to send • Shift + Enter for newline
          </div>
        </div>
      </div>
    </div>
  );
};

export default AssistantChat;
