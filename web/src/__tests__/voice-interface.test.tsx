import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { VoiceInputButton, EXAMPLE_VOICE_COMMANDS } from "../components/assistant/VoiceInputButton";
import { AssistantChat } from "../components/assistant/AssistantChat";
import { isSpeechRecognitionSupported } from "../hooks/useSpeechRecognition";

// Mock scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn();

// Mock Auth
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { id: 1, email: "officer@trafficos.local", role: "traffic_officer" },
    accessToken: "valid-jwt",
    logout: vi.fn(),
    isAdmin: () => false,
    isOfficer: () => true,
    canWrite: () => true,
  }),
}));

describe("Voice Interface & SpeechRecognition (voice-interface.test.tsx)", () => {
  let mockRecognitionInstance: any = null;

  class MockSpeechRecognition {
    continuous = false;
    interimResults = true;
    lang = "en-US";
    onstart: (() => void) | null = null;
    onresult: ((event: any) => void) | null = null;
    onerror: ((event: any) => void) | null = null;
    onend: (() => void) | null = null;

    start = vi.fn(() => {
      mockRecognitionInstance = this;
      if (this.onstart) this.onstart();
    });

    stop = vi.fn(() => {
      if (this.onend) this.onend();
    });

    abort = vi.fn(() => {
      if (this.onend) this.onend();
    });
  }

  const originalSpeech = (window as any).SpeechRecognition;
  const originalWebkitSpeech = (window as any).webkitSpeechRecognition;

  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    mockRecognitionInstance = null;
  });

  afterEach(() => {
    (window as any).SpeechRecognition = originalSpeech;
    (window as any).webkitSpeechRecognition = originalWebkitSpeech;
  });

  // ============================================================================
  // 1. Feature Detection (Supported vs Unsupported Browsers)
  // ============================================================================

  it("feature-detects unsupported browsers (e.g. Firefox) and displays honest fallback message", () => {
    delete (window as any).SpeechRecognition;
    delete (window as any).webkitSpeechRecognition;

    expect(isSpeechRecognitionSupported()).toBe(false);

    render(
      <VoiceInputButton onTranscript={vi.fn()} onAutoSubmit={vi.fn()} />
    );

    const button = screen.getByTestId("voice-input-button");
    expect(button).toBeDefined();
    expect((button as HTMLButtonElement).disabled).toBe(true);

    // Honest fallback message explaining browser limitation
    const fallbackMsg = screen.getByTestId("voice-unsupported-message");
    expect(fallbackMsg.textContent).toContain("Firefox");
    expect(fallbackMsg.textContent).toContain("Chromium");
  });

  it("feature-detects supported browsers when window.SpeechRecognition is available", () => {
    (window as any).SpeechRecognition = MockSpeechRecognition;

    expect(isSpeechRecognitionSupported()).toBe(true);

    render(
      <VoiceInputButton onTranscript={vi.fn()} onAutoSubmit={vi.fn()} />
    );

    const button = screen.getByTestId("voice-input-button");
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  // ============================================================================
  // 2. State Transitions: Idle -> Listening -> Result -> Idle
  // ============================================================================

  it("handles state transitions: idle -> listening -> interim result -> final result -> idle", () => {
    (window as any).SpeechRecognition = MockSpeechRecognition;
    const handleTranscript = vi.fn();
    const handleAutoSubmit = vi.fn();

    render(
      <VoiceInputButton
        onTranscript={handleTranscript}
        onAutoSubmit={handleAutoSubmit}
      />
    );

    const button = screen.getByTestId("voice-input-button");

    // 1. Initial State: Idle
    expect(screen.queryByTestId("voice-listening-indicator")).toBeNull();

    // 2. Click to Start: Transitions to Listening
    fireEvent.click(button);
    expect(screen.getByTestId("voice-listening-indicator")).toBeDefined();
    expect(screen.getByText("Listening…")).toBeDefined();

    // 3. Emit interim recognition result
    act(() => {
      mockRecognitionInstance.onresult({
        resultIndex: 0,
        results: [
          {
            0: { transcript: "show junction 5", confidence: 0.9 },
            isFinal: false,
            length: 1,
          },
        ],
      });
    });

    // Check interim transcript displayed in honest popover
    expect(screen.getByTestId("voice-interim-transcript").textContent).toContain("show junction 5");
    expect(handleTranscript).toHaveBeenCalledWith("show junction 5");
    expect(handleAutoSubmit).not.toHaveBeenCalled();

    // 4. Emit final recognition result
    act(() => {
      mockRecognitionInstance.onresult({
        resultIndex: 0,
        results: [
          {
            0: { transcript: "show junction 5 status", confidence: 0.98 },
            isFinal: true,
            length: 1,
          },
        ],
      });
    });

    expect(handleTranscript).toHaveBeenCalledWith("show junction 5 status");
    expect(handleAutoSubmit).toHaveBeenCalledWith("show junction 5 status");

    // 5. Click button again to Stop: Transitions back to Idle
    fireEvent.click(button);
    expect(screen.queryByTestId("voice-listening-indicator")).toBeNull();
  });

  // ============================================================================
  // 3. Example Voice Commands Mapping to Existing Intents
  // ============================================================================

  it("renders example voice commands hint list mapping to existing assistant intents", () => {
    (window as any).SpeechRecognition = MockSpeechRecognition;
    const handleTranscript = vi.fn();

    render(<VoiceInputButton onTranscript={handleTranscript} />);

    const hintsToggle = screen.getByTestId("voice-hints-toggle");
    fireEvent.click(hintsToggle);

    const hintsPanel = screen.getByTestId("voice-command-hints");
    expect(hintsPanel).toBeDefined();

    // Contains examples matching existing intents
    expect(screen.getByText(/show junction 5 status/i)).toBeDefined();
    expect(screen.getByText(/list today's violations/i)).toBeDefined();

    // Clicking a voice command hint invokes onTranscript
    const hintBtn = screen.getByTestId("voice-hint-0");
    fireEvent.click(hintBtn);

    expect(handleTranscript).toHaveBeenCalledWith(EXAMPLE_VOICE_COMMANDS[0]);
  });

  // ============================================================================
  // 4. Transcript Submission Wiring into Existing Assistant Pipeline
  // ============================================================================

  it("wires transcript into AssistantChat composer textarea and auto-submits through pipeline", async () => {
    (window as any).SpeechRecognition = MockSpeechRecognition;

    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        answer: "Junction 5 is operating normally at congestion level 24.",
        conversation_id: "conv-voice-test",
        tool_calls: [],
        provenance: [{ segment: "Junction 5 is operating normally", label: "observed" }],
        insufficient_data: false,
        suggested_followups: [],
      }),
    });
    global.fetch = mockFetch;

    render(<AssistantChat />);

    const textarea = screen.getByTestId("assistant-composer-textarea") as HTMLTextAreaElement;
    expect(textarea.value).toBe("");

    const voiceBtn = screen.getByTestId("voice-input-button");
    fireEvent.click(voiceBtn);

    // Simulate speech recognition finishing with final transcript
    await act(async () => {
      mockRecognitionInstance.onresult({
        resultIndex: 0,
        results: [
          {
            0: { transcript: "show junction 5 status", confidence: 0.95 },
            isFinal: true,
            length: 1,
          },
        ],
      });
    });

    // Check that transcript filled input and submitted to existing assistant pipeline
    expect(mockFetch).toHaveBeenCalled();
    const fetchBody = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(fetchBody.message).toBe("show junction 5 status");
  });
});
