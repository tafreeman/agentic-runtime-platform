import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EvaluationRubricAccordion from "../components/evaluations/EvaluationRubricAccordion";

const mockUseRunEvaluationDetail = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRunEvaluationDetail: (...args: unknown[]) =>
    mockUseRunEvaluationDetail(...args),
}));

const baseEvaluation = {
  enabled: true,
  rubric: "default",
  rubric_id: "default",
  rubric_version: "1",
  criteria: [],
  overall_score: 50,
  weighted_score: 50,
  objective_weighted_score: 50,
  grade: "C",
  grade_capped: false,
  passed: false,
  pass_threshold: 70,
  hard_gates: null,
  hard_gate_failures: [],
  floor_violations: [],
  step_scores: [],
  score_layers: null,
  hybrid_weights: {},
  judge: null,
  generated_at: "2026-05-03T00:00:00Z",
};

const scoreLayers = {
  layer1_objective: 62.1,
  layer2_judge: null as number | null,
  layer3_similarity: 40.0,
  layer3_efficiency: 50.0,
  layer3_advisory: 45.3,
};

function mockDetail(overrides: Record<string, unknown>) {
  mockUseRunEvaluationDetail.mockReturnValue({
    isLoading: false,
    data: { evaluation: { ...baseEvaluation, ...overrides } },
  });
}

describe("EvaluationRubricAccordion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders expandable per-step score details", () => {
    mockUseRunEvaluationDetail.mockReturnValue({
      isLoading: false,
      data: {
        evaluation: {
          enabled: true,
          rubric: "default",
          rubric_id: "default",
          rubric_version: "1",
          criteria: [],
          overall_score: 50,
          weighted_score: 50,
          objective_weighted_score: 50,
          grade: "C",
          grade_capped: false,
          passed: false,
          pass_threshold: 70,
          hard_gates: null,
          hard_gate_failures: [],
          floor_violations: [],
          step_scores: [
            {
              step_name: "review_code",
              status: "failed",
              score: 0,
              reason: "review found blocking issues",
            },
            {
              step_name: "generate_api",
              status: "success",
              score: 100,
              duration_ms: 1250,
            },
          ],
          score_layers: null,
          hybrid_weights: {},
          judge: null,
          generated_at: "2026-05-03T00:00:00Z",
        },
      },
    });

    render(<EvaluationRubricAccordion filename="run.json" />);

    expect(screen.getByText("step scores")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /review_code/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /review_code/i }));

    expect(screen.getByText(/review found blocking issues/)).toBeInTheDocument();
  });

  it("shows a warn pill and reason when the judge was skipped", () => {
    mockDetail({
      judge_skipped: true,
      judge_skip_reason: "RuntimeError: No LLM backend configured for judge",
      score_layers: { ...scoreLayers, layer2_judge: null },
    });

    render(<EvaluationRubricAccordion filename="run.json" />);

    expect(screen.getAllByText(/judge skipped/i).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/No LLM backend configured for judge/),
    ).toBeInTheDocument();
  });

  it("shows no judge-skipped warning when the judge layer scored", () => {
    mockDetail({
      judge_skipped: false,
      judge_skip_reason: null,
      score_layers: { ...scoreLayers, layer2_judge: 78.5 },
    });

    render(<EvaluationRubricAccordion filename="run.json" />);

    expect(screen.queryByText(/judge skipped/i)).toBeNull();
    expect(screen.getByText(/judge 78.5/)).toBeInTheDocument();
  });

  it("derives the skipped state for legacy payloads without the flag", () => {
    // Older stored evaluations have no judge_skipped field — a null judge
    // layer is the only signal.
    mockDetail({ score_layers: { ...scoreLayers, layer2_judge: null } });

    render(<EvaluationRubricAccordion filename="run.json" />);

    expect(screen.getAllByText(/judge skipped/i).length).toBeGreaterThan(0);
    // No stored reason — the fallback explanation must still render.
    expect(
      screen.getByText(/objective\+advisory only/),
    ).toBeInTheDocument();
  });

  it("treats payloads with no score layers at all as judge-skipped", () => {
    // Pre-hybrid payloads have score_layers: null — the judge definitively
    // never contributed to those either.
    mockDetail({});

    render(<EvaluationRubricAccordion filename="run.json" />);

    expect(screen.getAllByText(/judge skipped/i).length).toBeGreaterThan(0);
  });

  it("shows a notice when the overlap term never engaged", () => {
    mockDetail({
      judge_skipped: false,
      expected_text_present: false,
      score_layers: { ...scoreLayers, layer2_judge: 78.5 },
    });

    render(<EvaluationRubricAccordion filename="run.json" />);

    expect(screen.queryByText(/judge skipped/i)).toBeNull();
    expect(screen.getByText(/overlap term inactive/)).toBeInTheDocument();
  });
});
