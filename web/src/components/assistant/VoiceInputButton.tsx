"use client";

import React, { useState } from "react";
import { Mic, MicOff, AlertCircle, Sparkles, Volume2 } from "lucide-react";
import {
  useSpeechRecognition,
  isSpeechRecognitionSupported,
} from "@/hooks/useSpeechRecognition";

export interface VoiceInputButtonProps {
  onTranscript: (transcript: string) => void;
  onAutoSubmit?: (transcript: string) => void;
  disabled?: boolean;
  className?: string;
}

export const EXAMPLE_VOICE_COMMANDS = [
  "show junction 5 status",
  "list today's violations",
  "most congested junctions",
  "active incidents downtown",
  "why was green extended at junction 2?",
  "how do I get from junction 1 to junction 4?",
];

export const VoiceInputButton: React.FC<VoiceInputButtonProps> = ({
  onTranscript,
  onAutoSubmit,
  disabled = false,
  className = "",
}) => {
  const [showHints, setShowHints] = useState<boolean>(false);

  const {
    isSupported,
    isListening,
    interimTranscript,
    finalTranscript,
    error,
    startListening,
    stopListening,
  } = useSpeechRecognition({
    onTranscript: (text, isFinal) => {
      onTranscript(text);
      if (isFinal && onAutoSubmit) {
        onAutoSubmit(text);
      }
    },
  });

  const handleToggle = () => {
    if (!isSupported || disabled) return;
    if (isListening) {
      stopListening();
    } else {
      startListening();
    }
  };

  return (
    <div className={`relative flex items-center ${className}`}>
      {/* Listening pulse overlay / interim transcript popover */}
      {isListening && (
        <div
          data-testid="voice-listening-popover"
          className="absolute bottom-14 right-0 w-72 sm:w-80 p-3 rounded-2xl bg-surface border border-line shadow-xl z-50 animate-in fade-in zoom-in-95 duration-150"
        >
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-line">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-danger animate-ping" />
              <span
                data-testid="voice-listening-indicator"
                className="text-xs font-mono font-semibold text-rose-400"
              >
                Listening…
              </span>
            </div>
            <button
              type="button"
              onClick={stopListening}
              className="text-[10px] font-mono text-muted hover:text-ink px-2 py-0.5 rounded bg-ink/5"
            >
              Stop
            </button>
          </div>

          <div
            data-testid="voice-interim-transcript"
            className="text-xs text-text italic min-h-[32px] leading-relaxed break-words bg-cream/60 p-2 rounded-lg"
          >
            {interimTranscript || finalTranscript || "Speak now into microphone…"}
          </div>

          <div className="mt-2 text-[10px] text-muted font-mono flex items-center gap-1">
            <Volume2 className="w-3 h-3 text-accent shrink-0" />
            <span>Browser Web Speech API • Speaks directly to assistant</span>
          </div>
        </div>
      )}

      {/* Unsupported browser fallback badge/banner */}
      {!isSupported && (
        <div
          data-testid="voice-unsupported-banner"
          className="hidden group-hover:block absolute bottom-14 right-0 w-72 p-3 rounded-2xl bg-surface border border-amber/30 text-accent-deep text-xs shadow-xl z-50 font-mono"
        >
          <div className="flex items-center gap-2 font-semibold text-amber mb-1">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>Voice Input Unavailable</span>
          </div>
          <p
            data-testid="voice-unsupported-message"
            className="text-[11px] text-muted leading-normal"
          >
            Web Speech API is not supported in this browser (e.g. Firefox). Please use
            a Chromium-based browser (Chrome, Edge) or Safari for live voice transcription.
          </p>
        </div>
      )}

      {/* Voice command hints dropdown */}
      {showHints && isSupported && !isListening && (
        <div
          data-testid="voice-command-hints"
          className="absolute bottom-14 right-0 w-72 p-3 rounded-2xl bg-surface border border-line shadow-xl z-50 text-xs text-text"
        >
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-line text-xs font-semibold text-ink">
            <span className="flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-accent" />
              Example Voice Commands
            </span>
            <button
              type="button"
              onClick={() => setShowHints(false)}
              className="text-muted hover:text-ink"
            >
              ×
            </button>
          </div>
          <p className="text-[11px] text-muted mb-2">
            Mapped directly to existing NLU engineering intents:
          </p>
          <div className="space-y-1">
            {EXAMPLE_VOICE_COMMANDS.map((cmd, i) => (
              <button
                key={i}
                type="button"
                data-testid={`voice-hint-${i}`}
                onClick={() => {
                  onTranscript(cmd);
                  setShowHints(false);
                }}
                className="w-full text-left text-xs px-2 py-1.5 rounded-lg bg-cream/60 hover:bg-cream text-pine-deep font-mono transition-colors block"
              >
                &ldquo;{cmd}&rdquo;
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Main Microphone Button */}
      <div className="relative group flex items-center">
        <button
          type="button"
          data-testid="voice-input-button"
          disabled={disabled || !isSupported}
          onClick={handleToggle}
          aria-label={
            isListening
              ? "Stop listening"
              : isSupported
              ? "Start voice input"
              : "Voice input not supported in this browser"
          }
          className={`h-11 w-11 rounded-xl flex items-center justify-center transition-all cursor-pointer font-semibold shadow-md ${
            isListening
              ? "bg-danger text-white ring-4 ring-danger/30 animate-pulse"
              : isSupported
              ? "bg-pine-tint hover:bg-pine-tint text-pine-deep border border-pine/25 hover:border-pine/40"
              : "bg-ink/5 text-faint border border-line cursor-not-allowed opacity-50"
          }`}
        >
          {isListening ? (
            <MicOff className="w-4 h-4" />
          ) : (
            <Mic className="w-4 h-4" />
          )}
        </button>

        {/* Small hints trigger button */}
        {isSupported && !isListening && (
          <button
            type="button"
            data-testid="voice-hints-toggle"
            onClick={() => setShowHints((prev) => !prev)}
            aria-label="Show voice command examples"
            className="absolute -top-2 -right-2 w-4 h-4 rounded-full bg-accent/20 text-accent hover:bg-accent/40 text-[9px] flex items-center justify-center font-bold"
          >
            ?
          </button>
        )}
      </div>
    </div>
  );
};

export default VoiceInputButton;
