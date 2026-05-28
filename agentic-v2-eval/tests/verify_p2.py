"""Verification test for P2 tasks (Merge Scorers + Decouple Pattern Scorer)."""

import json

from agentic_v2_eval import (
    COHERENCE,
    PatternEvaluator,
    QualityEvaluator,
    StandardEvaluator,
)


# Mock Client
class MockLLMClient:
    def generate_text(self, model_name, prompt, **kwargs):
        # Return valid JSON for Pattern and Standard
        if "Pattern:" in prompt or "PATTERN" in prompt:
            return json.dumps(
                {
                    "universal_scores": {
                        "PIF": 5,
                        "POI": 5,
                        "PC": 5,
                        "CA": 5,
                        "SRC": 5,
                        "IR": 5,
                        "PR": 1.0,
                    },
                    "pattern_scores": {"R1": 5, "R2": 5, "R3": 5},
                    "confidence": 1.0,
                    "failures": [],
                }
            )
        if "PROMPT UNDER REVIEW" in prompt:
            return json.dumps(
                {
                    "scores": {
                        "clarity": 9,
                        "effectiveness": 8,
                        "structure": 8,
                        "specificity": 7,
                        "completeness": 9,
                    },
                    "confidence": 0.9,
                    "improvements": ["Needs more cowbell"],
                }
            )
        if "Coherence" in prompt:  # Quality eval (PromptFlow style)
            return "5"

        return "{}"


def test_imports_and_decoupling():
    # Test strict decoupling by inspecting modules

    import agentic_v2_eval.evaluators.pattern as p_mod

    # Check if 'tools' is in p_mod's imports
    assert "tools" not in str(
        p_mod.__dict__
    ), "tools module leaked into pattern evaluator"
    print("[PASS] Decoupling Verified: pattern.py has no dependency on 'tools'")


def test_pattern_evaluator():
    client = MockLLMClient()
    scorer = PatternEvaluator(client)
    res = scorer.score_pattern("test", "You are...", "Output...", "react")
    assert res.overall_universal > 0
    print("[PASS] PatternEvaluator Verified")


def test_standard_evaluator():
    client = MockLLMClient()
    scorer = StandardEvaluator(client)
    res = scorer.score_prompt("test", "My prompt")
    assert res.grade in ["A", "B", "C"]
    assert res.overall_score > 0
    print("[PASS] StandardEvaluator Verified")


def test_quality_evaluator():
    client = MockLLMClient()
    scorer = QualityEvaluator(client)
    score = scorer.evaluate(COHERENCE, {"input": "hi"}, "hello")
    assert score == 1.0
    print("[PASS] QualityEvaluator Verified")


if __name__ == "__main__":
    test_imports_and_decoupling()
    test_pattern_evaluator()
    test_standard_evaluator()
    test_quality_evaluator()
