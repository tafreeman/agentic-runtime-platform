import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { Circle, Info, Lightbulb, X } from "lucide-react";

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
        className="focus-ring inline-flex min-h-9 items-center gap-2 rounded-md px-2 font-mono text-micro text-el-secondary underline-offset-2 transition-colors hover:text-el-ink hover:underline"
        type="button"
      >
        <Lightbulb aria-hidden="true" className="size-3.5" />
        <span>Quick Start</span>
      </button>
    );
  }

  if (dismissed) {
    return null;
  }

  return (
    <section
      data-testid="getting-started-card"
      aria-labelledby="getting-started-title"
      className="rounded-lg border border-el-divider bg-el-surface p-[18px]"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2
            id="getting-started-title"
            className="font-display text-[20px] font-semibold tracking-[-0.3px] text-el-ink"
          >
            Get Started with Agentic
          </h2>
          <p className="mt-1 font-mono text-micro text-el-muted">
            Complete these steps to unlock the full platform
          </p>
        </div>
        <button
          type="button"
          onClick={handleDismiss}
          className="focus-ring inline-flex size-9 flex-none items-center justify-center rounded-md text-el-muted transition-colors hover:bg-el-hover hover:text-el-ink"
          aria-label="Dismiss getting started guide"
        >
          <X aria-hidden="true" className="size-4" />
        </button>
      </div>

      {/* Checklist */}
      <ol className="mt-4 space-y-3">
        {steps.map((step) => (
          <li
            key={step.id}
            className="flex items-start gap-3 rounded-md border border-el-divider-soft bg-el-canvas p-3"
          >
            <div className="mt-0.5 text-el-muted">
              <Circle aria-hidden="true" className="size-4" />
            </div>
            <div className="flex-1">
              {step.link ? (
                <Link
                  to={step.link}
                  className="focus-ring relative rounded-sm font-mono text-xs font-semibold text-el-ink underline-offset-2 after:absolute after:-inset-x-1 after:-inset-y-3 hover:text-el-accent-strong hover:underline"
                >
                  {step.title}
                </Link>
              ) : (
                <div className="font-mono text-xs font-semibold text-el-ink">
                  {step.title}
                </div>
              )}
              <p className="mt-1 font-mono text-micro text-el-secondary">
                {step.description}
              </p>
              {step.inlineGuidance && (
                <div className="mt-2 flex items-start gap-1.5 rounded-md border border-el-divider-soft bg-el-surface px-2 py-1.5 font-mono text-micro text-el-secondary">
                  <Info aria-hidden="true" className="mt-px size-3.5 flex-none text-el-info" />
                  <span>{step.inlineGuidance}</span>
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
