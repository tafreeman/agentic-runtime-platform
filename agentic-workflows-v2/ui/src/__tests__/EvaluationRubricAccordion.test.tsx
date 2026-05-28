import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import EvaluationRubricAccordion from "../components/evaluations/EvaluationRubricAccordion";

const mockUseRunEvaluationDetail = vi.fn();

vi.mock("../hooks/useRuns", () => ({
  useRunEvaluationDetail: (...args: unknown[]) =>
    mockUseRunEvaluationDetail(...args),
}));

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
});
