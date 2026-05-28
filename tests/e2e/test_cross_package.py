"""Cross-package integration tests for the three-package monorepo.

Verifies that the three packages (tools, agentic-workflows-v2, agentic-v2-eval)
can interoperate correctly:

1. Tools -> Runtime: LLMClient from tools can drive agentic_v2 agents
2. Runtime -> Eval: Agent output can be scored by the eval framework
3. Full pipeline: Task -> Agent (mock LLM) -> Eval scorer -> valid score

All LLM calls are mocked so no API keys are required.

Run:
    cd d:/source/agentic-workflows
    python -m pytest tests/e2e/test_cross_package.py -v
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Guard imports: skip entire module if any package is not installed
# ---------------------------------------------------------------------------

_SKIP_REASON_TOOLS = "tools package not installed (pip install -e .)"
_SKIP_REASON_RUNTIME = (
    "agentic-workflows-v2 package not installed "
    "(pip install -e agentic-workflows-v2)"
)
_SKIP_REASON_EVAL = (
    "agentic-v2-eval package not installed " "(pip install -e agentic-v2-eval)"
)

try:
    from tools.llm.llm_client import LLMClient, LLMClientError

    HAS_TOOLS = True
except ImportError:
    HAS_TOOLS = False

try:
    from agentic_v2.agents import BaseAgent, CoderAgent
    from agentic_v2.contracts import (
        CodeGenerationInput,
        CodeGenerationOutput,
        TaskInput,
        TaskOutput,
    )
    from agentic_v2.models import LLMClientWrapper, MockBackend, ModelTier

    HAS_RUNTIME = True
except ImportError:
    HAS_RUNTIME = False

try:
    from agentic_v2_eval import (
        EvaluatorRegistry,
        Scorer,
        ScoringResult,
        StandardEvaluator,
        StandardScore,
    )
    from agentic_v2_eval.interfaces import LLMClientProtocol

    HAS_EVAL = True
except ImportError:
    HAS_EVAL = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class MockLLMClientForEval:
    """Adapter that satisfies agentic_v2_eval.LLMClientProtocol.

    Returns a pre-configured JSON response so that StandardEvaluator and
    PatternEvaluator can parse it without making real API calls.
    """

    def __init__(self, canned_response: str = "") -> None:
        self._canned = canned_response
        self.calls: list[dict] = []

    def generate_text(
        self,
        model_name: str,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        **kwargs,
    ) -> str:
        self.calls.append(
            {
                "model_name": model_name,
                "prompt": prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return self._canned


# ===========================================================================
# 1. Import-level sanity checks
# ===========================================================================


@pytest.mark.e2e
class TestPackageImports:
    """Verify that all three packages can be imported side by side."""

    @pytest.mark.skipif(not HAS_TOOLS, reason=_SKIP_REASON_TOOLS)
    def test_tools_core_imports(self) -> None:
        """tools.llm.llm_client.LLMClient is importable."""
        from tools.llm.llm_client import LLMClient

        assert hasattr(LLMClient, "generate_text")
        assert callable(LLMClient.generate_text)

    @pytest.mark.skipif(not HAS_RUNTIME, reason=_SKIP_REASON_RUNTIME)
    def test_runtime_core_imports(self) -> None:
        """Core agentic_v2 symbols are importable."""
        from agentic_v2 import BaseAgent, CoderAgent, ModelTier, get_client

        assert BaseAgent is not None
        assert CoderAgent is not None
        assert ModelTier is not None
        assert callable(get_client)

    @pytest.mark.skipif(not HAS_EVAL, reason=_SKIP_REASON_EVAL)
    def test_eval_core_imports(self) -> None:
        """Core agentic_v2_eval symbols are importable."""
        from agentic_v2_eval import (
            EvaluatorRegistry,
            PatternEvaluator,
            Scorer,
            ScoringResult,
            StandardEvaluator,
        )

        assert Scorer is not None
        assert EvaluatorRegistry is not None
        assert StandardEvaluator is not None
        assert PatternEvaluator is not None
        assert ScoringResult is not None

    @pytest.mark.skipif(
        not (HAS_TOOLS and HAS_RUNTIME and HAS_EVAL),
        reason="All three packages required",
    )
    def test_all_three_packages_coexist(self) -> None:
        """All three packages can be imported in the same process."""
        from agentic_v2 import CoderAgent
        from agentic_v2_eval import Scorer

        from tools.llm.llm_client import LLMClient

        assert LLMClient is not None
        assert CoderAgent is not None
        assert Scorer is not None


# ===========================================================================
# 2. Tools -> Runtime integration
# ===========================================================================


@pytest.mark.e2e
class TestToolsToRuntimeIntegration:
    """Verify tools.llm.LLMClient can serve as a model backend in agentic_v2."""

    @pytest.mark.skipif(
        not (HAS_TOOLS and HAS_RUNTIME),
        reason="tools and agentic-workflows-v2 required",
    )
    def test_tools_llm_client_has_compatible_interface(self) -> None:
        """LLMClient.generate_text signature is compatible with eval protocol."""
        import inspect

        from tools.llm.llm_client import LLMClient

        sig = inspect.signature(LLMClient.generate_text)
        params = list(sig.parameters.keys())

        # Must accept model_name, prompt, and optional kwargs
        assert "model_name" in params
        assert "prompt" in params
        assert "temperature" in params
        assert "max_tokens" in params

    @pytest.mark.skipif(not HAS_RUNTIME, reason=_SKIP_REASON_RUNTIME)
    def test_mock_backend_drives_coder_agent(self) -> None:
        """MockBackend from agentic_v2.models works as agent LLM backend."""
        mock_backend = MockBackend(
            default_response="```python\ndef add(a, b):\n    return a + b\n```"
        )
        agent = CoderAgent()
        # Inject mock backend so no real API call happens
        agent.llm_client = LLMClientWrapper(backend=mock_backend)

        task = CodeGenerationInput(
            description="Create an add function",
            language="python",
        )

        import asyncio

        result = asyncio.run(agent.run(task))

        assert isinstance(result, CodeGenerationOutput)
        assert result.success
        # MockBackend should have recorded at least one call
        assert len(mock_backend.call_history) > 0

    @pytest.mark.skipif(not HAS_RUNTIME, reason=_SKIP_REASON_RUNTIME)
    def test_mock_backend_pattern_matching(self) -> None:
        """MockBackend pattern matching routes different prompts correctly."""
        mock_backend = MockBackend()
        mock_backend.set_response(
            "calculator",
            '```python\ndef calc(a, b, op):\n    if op == "+":\n        return a + b\n```',
        )
        mock_backend.set_response(
            "greeting",
            '```python\ndef greet(name):\n    return f"Hello, {name}!"\n```',
        )

        agent = CoderAgent()
        agent.llm_client = LLMClientWrapper(backend=mock_backend)

        task = CodeGenerationInput(
            description="Build a calculator utility",
            language="python",
        )

        import asyncio

        result = asyncio.run(agent.run(task))

        assert isinstance(result, CodeGenerationOutput)
        assert result.success


# ===========================================================================
# 3. Runtime -> Eval integration
# ===========================================================================


@pytest.mark.e2e
class TestRuntimeToEvalIntegration:
    """Verify that runtime agent output can be scored by the eval framework."""

    @pytest.mark.skipif(
        not (HAS_RUNTIME and HAS_EVAL),
        reason="agentic-workflows-v2 and agentic-v2-eval required",
    )
    def test_agent_output_scored_by_rubric(self) -> None:
        """Run CoderAgent with mock, then score the output via eval Scorer."""
        import asyncio

        # -- Step 1: Run the agent with a mock backend --
        mock_backend = MockBackend(
            default_response=(
                "```python\ndef fibonacci(n):\n"
                '    """Return the nth Fibonacci number."""\n'
                "    if n <= 1:\n        return n\n"
                "    return fibonacci(n - 1) + fibonacci(n - 2)\n```"
            )
        )
        agent = CoderAgent()
        agent.llm_client = LLMClientWrapper(backend=mock_backend)

        task = CodeGenerationInput(
            description="Write a Fibonacci function",
            language="python",
        )
        result = asyncio.run(agent.run(task))
        assert result.success

        # -- Step 2: Score using the eval Scorer with an in-memory rubric --
        rubric = {
            "name": "Code Generation Rubric",
            "version": "1.0",
            "criteria": [
                {
                    "name": "Accuracy",
                    "weight": 2.0,
                    "min_value": 0.0,
                    "max_value": 1.0,
                },
                {
                    "name": "Completeness",
                    "weight": 1.5,
                    "min_value": 0.0,
                    "max_value": 1.0,
                },
                {
                    "name": "CodeQuality",
                    "weight": 1.0,
                    "min_value": 0.0,
                    "max_value": 1.0,
                },
            ],
        }
        scorer = Scorer(rubric)

        # Derive simple heuristic metrics from the agent output
        has_code = bool(result.code) if hasattr(result, "code") else result.success
        has_docstring = "docstring" in str(result).lower() or '"""' in str(result)

        metrics = {
            "Accuracy": 1.0 if has_code else 0.0,
            "Completeness": 0.9 if result.success else 0.0,
            "CodeQuality": 0.85 if has_docstring else 0.5,
        }

        scoring_result = scorer.score(metrics)

        assert isinstance(scoring_result, ScoringResult)
        assert 0.0 <= scoring_result.weighted_score <= 1.0
        assert scoring_result.weighted_score > 0.0
        assert len(scoring_result.missing_criteria) == 0

    @pytest.mark.skipif(not HAS_EVAL, reason=_SKIP_REASON_EVAL)
    def test_scorer_with_inline_rubric(self) -> None:
        """Scorer works with a dict rubric (no file I/O)."""
        rubric = {
            "name": "Inline Test Rubric",
            "version": "1.0",
            "criteria": [
                {"name": "Relevance", "weight": 1.0},
                {"name": "Quality", "weight": 1.0},
            ],
        }
        scorer = Scorer(rubric)
        result = scorer.score({"Relevance": 0.8, "Quality": 0.7})

        assert isinstance(result, ScoringResult)
        assert result.weighted_score == pytest.approx(0.75, abs=0.01)
        assert result.missing_criteria == []

    @pytest.mark.skipif(not HAS_EVAL, reason=_SKIP_REASON_EVAL)
    def test_scorer_reports_missing_criteria(self) -> None:
        """Scorer correctly identifies missing criteria from results."""
        rubric = {
            "name": "Test Rubric",
            "criteria": [
                {"name": "A", "weight": 1.0},
                {"name": "B", "weight": 1.0},
                {"name": "C", "weight": 1.0},
            ],
        }
        scorer = Scorer(rubric)
        result = scorer.score({"A": 0.9})

        assert "B" in result.missing_criteria
        assert "C" in result.missing_criteria


# ===========================================================================
# 4. Tools -> Eval integration
# ===========================================================================


@pytest.mark.e2e
class TestToolsToEvalIntegration:
    """Verify that tools.llm.LLMClient can serve as the eval framework LLM."""

    @pytest.mark.skipif(
        not (HAS_TOOLS and HAS_EVAL),
        reason="tools and agentic-v2-eval required",
    )
    def test_tools_llm_client_satisfies_eval_protocol(self) -> None:
        """A thin wrapper around tools.LLMClient satisfies LLMClientProtocol."""
        # LLMClient is a static class, so wrap it to produce an instance
        # that satisfies the eval framework's protocol.

        class ToolsLLMAdapter:
            """Adapts the static tools.LLMClient into an instance that satisfies
            agentic_v2_eval.LLMClientProtocol."""

            def generate_text(
                self,
                model_name: str,
                prompt: str,
                temperature: float = 0.1,
                max_tokens: int = 1000,
                **kwargs,
            ) -> str:
                return LLMClient.generate_text(
                    model_name=model_name,
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

        adapter = ToolsLLMAdapter()
        # Runtime protocol check
        assert isinstance(adapter, LLMClientProtocol)

    @pytest.mark.skipif(not HAS_EVAL, reason=_SKIP_REASON_EVAL)
    def test_standard_evaluator_with_mock_llm(self) -> None:
        """StandardEvaluator produces a valid score using a mock LLM client."""
        import json

        # Prepare a canned JSON response matching StandardEvaluator expectations
        canned = json.dumps(
            {
                "scores": {
                    "clarity": 8.0,
                    "effectiveness": 7.5,
                    "structure": 9.0,
                    "specificity": 7.0,
                    "completeness": 8.5,
                },
                "improvements": ["Add more edge case coverage"],
                "confidence": 0.9,
            }
        )
        mock_client = MockLLMClientForEval(canned_response=canned)
        evaluator = StandardEvaluator(llm_client=mock_client)

        score = evaluator.score_prompt(
            prompt_name="test_prompt.md",
            prompt_content="You are a helpful assistant that writes Python code.",
            model="mock:test",
            runs=1,
        )

        assert isinstance(score, StandardScore)
        assert 0.0 <= score.overall_score <= 10.0
        assert score.overall_score > 0.0
        assert score.grade in ("A", "B", "C", "D", "F")
        assert score.successful_runs == 1
        assert len(mock_client.calls) == 1

    @pytest.mark.skipif(not HAS_EVAL, reason=_SKIP_REASON_EVAL)
    def test_evaluator_registry_has_standard_and_pattern(self) -> None:
        """EvaluatorRegistry should list both 'standard' and 'pattern'."""
        available = EvaluatorRegistry.list_available()
        assert "standard" in available
        assert "pattern" in available


# ===========================================================================
# 5. Full pipeline: Task -> Agent -> Eval -> Score
# ===========================================================================


@pytest.mark.e2e
class TestFullPipeline:
    """End-to-end test: define a task, agent processes it (mock LLM),
    output is scored by the eval framework, and the score is in valid range.
    """

    @pytest.mark.skipif(
        not (HAS_RUNTIME and HAS_EVAL),
        reason="agentic-workflows-v2 and agentic-v2-eval required",
    )
    def test_code_generation_pipeline(self) -> None:
        """Full pipeline: CodeGenerationInput -> CoderAgent -> Scorer."""
        import asyncio

        # -- 1. Define the task --
        task = CodeGenerationInput(
            description="Write a function that checks if a string is a palindrome",
            language="python",
        )

        # -- 2. Agent processes task with mocked LLM --
        mock_backend = MockBackend(
            default_response=(
                "```python\ndef is_palindrome(s: str) -> bool:\n"
                '    """Check if a string is a palindrome."""\n'
                '    cleaned = s.lower().replace(" ", "")\n'
                "    return cleaned == cleaned[::-1]\n```\n\n"
                "The function handles case insensitivity and spaces."
            )
        )
        agent = CoderAgent()
        agent.llm_client = LLMClientWrapper(backend=mock_backend)

        result = asyncio.run(agent.run(task))

        assert isinstance(result, CodeGenerationOutput)
        assert result.success

        # -- 3. Score the output with eval framework --
        rubric = {
            "name": "Code Quality Rubric",
            "version": "1.0",
            "criteria": [
                {
                    "name": "Correctness",
                    "weight": 3.0,
                    "description": "Does the code solve the stated problem?",
                },
                {
                    "name": "Readability",
                    "weight": 2.0,
                    "description": "Is the code clean and well-documented?",
                },
                {
                    "name": "Robustness",
                    "weight": 1.0,
                    "description": "Does it handle edge cases?",
                },
            ],
        }
        scorer = Scorer(rubric)

        # Derive metrics from the agent's output
        output_str = str(result)
        has_function = "def " in output_str
        has_type_hints = "->" in output_str or ": str" in output_str
        has_docstring = '"""' in output_str or "'''" in output_str

        metrics = {
            "Correctness": 0.95 if has_function else 0.3,
            "Readability": 0.9 if has_docstring else 0.5,
            "Robustness": 0.7 if has_type_hints else 0.4,
        }

        scoring_result = scorer.score(metrics)

        # -- 4. Verify score is in valid range --
        assert isinstance(scoring_result, ScoringResult)
        assert 0.0 <= scoring_result.weighted_score <= 1.0
        assert scoring_result.weighted_score > 0.5, (
            f"Expected a decent score for good code output, "
            f"got {scoring_result.weighted_score:.3f}"
        )
        assert scoring_result.missing_criteria == []
        assert "Correctness" in scoring_result.criterion_scores
        assert "Readability" in scoring_result.criterion_scores
        assert "Robustness" in scoring_result.criterion_scores

    @pytest.mark.skipif(
        not (HAS_RUNTIME and HAS_EVAL),
        reason="agentic-workflows-v2 and agentic-v2-eval required",
    )
    def test_full_pipeline_with_standard_evaluator(self) -> None:
        """Full pipeline using StandardEvaluator for LLM-judge scoring."""
        import asyncio
        import json

        # -- 1. Run agent --
        mock_backend = MockBackend(
            default_response=(
                "```python\ndef merge_sorted(a: list, b: list) -> list:\n"
                '    """Merge two sorted lists into one sorted list."""\n'
                "    result = []\n"
                "    i = j = 0\n"
                "    while i < len(a) and j < len(b):\n"
                "        if a[i] <= b[j]:\n"
                "            result.append(a[i])\n"
                "            i += 1\n"
                "        else:\n"
                "            result.append(b[j])\n"
                "            j += 1\n"
                "    result.extend(a[i:])\n"
                "    result.extend(b[j:])\n"
                "    return result\n```"
            )
        )
        agent = CoderAgent()
        agent.llm_client = LLMClientWrapper(backend=mock_backend)

        task = CodeGenerationInput(
            description="Merge two sorted lists",
            language="python",
        )
        agent_result = asyncio.run(agent.run(task))
        assert agent_result.success

        # -- 2. Score with StandardEvaluator using mock LLM judge --
        canned_judge_response = json.dumps(
            {
                "scores": {
                    "clarity": 8.5,
                    "effectiveness": 9.0,
                    "structure": 8.0,
                    "specificity": 7.5,
                    "completeness": 8.0,
                },
                "improvements": [
                    "Consider adding input validation",
                ],
                "confidence": 0.85,
            }
        )
        mock_llm = MockLLMClientForEval(canned_response=canned_judge_response)
        evaluator = StandardEvaluator(llm_client=mock_llm)

        # Use the agent's output as the prompt to evaluate
        score = evaluator.score_prompt(
            prompt_name="agent_output",
            prompt_content=str(agent_result),
            model="mock:judge",
            runs=1,
        )

        # -- 3. Verify valid score --
        assert isinstance(score, StandardScore)
        assert 0.0 <= score.overall_score <= 10.0
        assert score.overall_score > 0.0
        assert score.grade in ("A", "B", "C", "D", "F")
        assert score.passed  # 8.2 average > 7.0 threshold

    @pytest.mark.skipif(
        not (HAS_TOOLS and HAS_RUNTIME and HAS_EVAL),
        reason="All three packages required",
    )
    def test_all_three_packages_in_one_pipeline(self) -> None:
        """Smoke test: all three packages participate in a single flow.

        tools: LLMClient interface check
        runtime: CoderAgent with MockBackend
        eval: Scorer with in-memory rubric
        """
        import asyncio

        # 1. Verify tools LLMClient is available
        from tools.llm.llm_client import LLMClient as ToolsLLM

        assert hasattr(ToolsLLM, "generate_text")

        # 2. Run runtime agent
        mock_backend = MockBackend(
            default_response='```python\ndef hello():\n    return "Hello, World!"\n```'
        )
        agent = CoderAgent()
        agent.llm_client = LLMClientWrapper(backend=mock_backend)

        task = CodeGenerationInput(
            description="Create a hello world function",
            language="python",
        )
        result = asyncio.run(agent.run(task))
        assert result.success

        # 3. Score with eval scorer
        scorer = Scorer(
            {
                "name": "Smoke",
                "criteria": [{"name": "Works", "weight": 1.0}],
            }
        )
        scoring_result = scorer.score({"Works": 1.0 if result.success else 0.0})

        assert scoring_result.weighted_score == pytest.approx(1.0)
        assert scoring_result.missing_criteria == []
