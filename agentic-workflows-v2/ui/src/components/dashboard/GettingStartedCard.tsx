import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Circle, Lightbulb, X } from "lucide-react";
import BBox from "../common/BBox";

const DISMISSED_KEY = "agentic-getting-started-dismissed";

interface GettingStartedCardProps {
  showQuickStartWhenDismissed?: boolean;
}

interface Step {
  id: number;
  title: string;
  description: string;
  link?: string;
  inlineGuidance?: string;
}

const steps: Step[] = [
  {
    id: 1,
    title: "Run your first workflow",
    description: "Try the test_deterministic workflow first - no API keys needed",
    link: "/workflows/test_deterministic",
  },
  {
    id: 2,
    title: "Configure an LLM provider",
    description: "When you're ready for LLM-backed workflows, add a provider key to .env",
    inlineGuidance:
      "Add OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY to your .env file",
  },
  {
    id: 3,
    title: "Explore the workflow library",
    description: "Browse available workflows and learn what's possible",
    link: "/workflows",
  },
];

function readDismissedState(): boolean {
  if (globalThis.window === undefined) {
    return false;
  }

  try {
    return globalThis.window.localStorage.getItem(DISMISSED_KEY) === "true";
  } catch {
    return false;
  }
}

function setDismissedState(nextDismissed: boolean): void {
  if (globalThis.window === undefined) {
    return;
  }

  try {
    if (nextDismissed) {
      globalThis.window.localStorage.setItem(DISMISSED_KEY, "true");
      return;
    }

    globalThis.window.localStorage.removeItem(DISMISSED_KEY);
  } catch {
    // Best-effort only; the UI should still work if storage is unavailable.
  }
}

export default function GettingStartedCard({
  showQuickStartWhenDismissed = false,
}: Readonly<GettingStartedCardProps>) {
  const [dismissed, setDismissed] = useState(readDismissedState);

  useEffect(() => {
    const handleStorageChange = () => {
      setDismissed(readDismissedState());
    };
    globalThis.window?.addEventListener("storage", handleStorageChange);
    globalThis.window?.addEventListener("getting-started-dismissed-change", handleStorageChange);
    return () => {
      globalThis.window?.removeEventListener("storage", handleStorageChange);
      globalThis.window?.removeEventListener("getting-started-dismissed-change", handleStorageChange);
    };
  }, []);

  const handleDismiss = () => {
    setDismissedState(true);
    setDismissed(true);
    globalThis.window?.dispatchEvent(new CustomEvent("getting-started-dismissed-change"));
  };

  const handleReopen = () => {
    setDismissedState(false);
    setDismissed(false);
    globalThis.window?.dispatchEvent(new CustomEvent("getting-started-dismissed-change"));
  };

  if (showQuickStartWhenDismissed) {
    if (!dismissed) {
      return null;
    }

    return (
      <button
        onClick={handleReopen}
        className="flex items-center gap-2 font-mono text-[11px] text-b-clay hover:underline"
        type="button"
      >
        <Lightbulb className="h-3 w-3" />
        <span>Quick Start</span>
      </button>
    );
  }

  if (dismissed) {
    return null;
  }

  return (
    <div data-testid="getting-started-card">
      <BBox className="relative overflow-hidden">
        {/* Primary card: clay accent bar across the top. */}
        <div className="absolute left-0 right-0 top-0 h-[3px] bg-b-clay" />
        <div className="p-[18px]">
          {/* Header */}
          <div className="flex items-start justify-between">
            <div>
              <h2
                style={{ fontFamily: "var(--b-font-heading)" }}
                className="text-[20px] font-semibold tracking-[-0.3px] text-b-text"
              >
                Get Started with Agentic
              </h2>
              <p className="mt-1 font-mono text-[11px] text-b-text-dim">
                Complete these steps to unlock the full platform
              </p>
            </div>
            <button
              onClick={handleDismiss}
              className="text-b-text-dim transition-colors hover:text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay"
              aria-label="Dismiss"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Checklist */}
          <div className="mt-4 space-y-3">
            {steps.map((step) => (
              <div
                key={step.id}
                style={{
                  borderWidth: "var(--b-bw)",
                  borderStyle: "solid",
                  borderRadius: "var(--b-rad-sm)",
                }}
                className="flex items-start gap-3 border-b-line-soft bg-b-bg2/50 p-3 transition-colors hover:border-b-line hover:bg-b-bg2"
              >
                <div className="mt-0.5 text-b-clay">
                  <Circle className="h-4 w-4" />
                </div>
                <div className="flex-1">
                  {step.link ? (
                    <Link
                      to={step.link}
                      className="font-mono text-[12px] font-semibold text-b-text hover:text-b-clay hover:underline"
                    >
                      {step.title}
                    </Link>
                  ) : (
                    <div className="font-mono text-[12px] font-semibold text-b-text">
                      {step.title}
                    </div>
                  )}
                  <p className="mt-1 font-mono text-[11px] text-b-text-mid">
                    {step.description}
                  </p>
                  {step.inlineGuidance && (
                    <div
                      style={{
                        borderWidth: "var(--b-bw)",
                        borderStyle: "solid",
                        borderRadius: "var(--b-rad-sm)",
                      }}
                      className="mt-2 border-b-line bg-b-bg3 px-2 py-1.5 font-mono text-[10px] text-b-text-dim"
                    >
                      [i] {step.inlineGuidance}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </BBox>
    </div>
  );
}
