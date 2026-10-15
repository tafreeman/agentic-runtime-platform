"""Model-call and response-parsing pipeline tests for :class:`TestAgent`.

Complements ``tests/test_new_agents.py``, which covers ``TestAgent``'s
configuration, ``_format_task_message`` happy paths, ``_count_tests`` and
``_generate_summary``. The seam this module pins down is the part of the
agent that turns a *model response* into a ``TestGenerationOutput``:

* ``_call_model`` -- both the backend-less canned-response branch and the
  real-client delegation branch (neither was exercised anywhere).
* ``_is_task_complete`` -- the per-language "response contains tests"
  predicate that gates ``BaseAgent._execute_loop``.
* ``_parse_output`` -- test aggregation and the ``coverage_estimate``
  heuristic, including its floor and its 95 cap.
* ``_parse_test_files`` -- filename resolution fallbacks and the malformed
  code-block paths.

These are pure heuristics with no provider dependency, so they can regress
silently: a parser that stops recognising a fenced block still returns a
well-formed ``TestGenerationOutput``, just an empty one. The tests below
assert on behaviour rather than on line execution, and the backend-less
branch is checked for *internal consistency* -- the canned response must
satisfy the agent's own completion predicate, otherwise a keyless
``run()`` burns every iteration and raises.
"""

import pytest
from pydantic import ValidationError

from agentic_v2.agents.base import AgentConfig
from agentic_v2.agents.test_agent import (
    LANGUAGE_CONFIG,
    TestAgent,
    TestGenerationInput,
    TestType,
)
from agentic_v2.agents.test_agent import TestFile as GeneratedTestFile
from agentic_v2.models import LLMClientWrapper, MockBackend, ModelTier, get_smart_router

# The backend-less branch of ``_call_model`` is the subject of several tests
# here; an ambient AGENTIC_NO_LLM=1 installs a placeholder backend and routes
# around it. Mirrors ``tests/test_agents.py``.
pytestmark = pytest.mark.usefixtures("backendless_baseline")

PYTHON_CONFIG = LANGUAGE_CONFIG["python"]


@pytest.fixture
def agent() -> TestAgent:
    """A default-configured, backend-less ``TestAgent``."""
    return TestAgent()


@pytest.fixture
def python_task() -> TestGenerationInput:
    """A minimal Python test-generation request."""
    return TestGenerationInput(code="def add(a, b): return a + b", language="python")


# ============================================================================
# TestGenerationInput.convert_test_types
# ============================================================================


class TestTestTypeCoercion:
    """The ``test_types`` before-validator."""

    def test_empty_defaults_to_unit(self):
        """An explicitly empty list falls back to unit tests."""
        assert TestGenerationInput(code="x", test_types=[]).test_types == [
            TestType.UNIT
        ]

    def test_strings_are_coerced(self):
        """Raw strings from YAML/JSON become enum members."""
        task = TestGenerationInput(code="x", test_types=["integration", "e2e"])

        assert task.test_types == [TestType.INTEGRATION, TestType.E2E]

    def test_enum_members_pass_through(self):
        """Already-typed members are left alone."""
        task = TestGenerationInput(code="x", test_types=[TestType.SECURITY])

        assert task.test_types == [TestType.SECURITY]

    def test_mixed_strings_and_enums(self):
        """A mixed list is normalised to enum members."""
        task = TestGenerationInput(code="x", test_types=["unit", TestType.PERFORMANCE])

        assert task.test_types == [TestType.UNIT, TestType.PERFORMANCE]

    def test_unknown_string_is_rejected(self):
        """An unrecognised test type fails validation rather than silently
        degrading to unit."""
        with pytest.raises(ValidationError):
            TestGenerationInput(code="x", test_types=["chaos"])


# ============================================================================
# _call_model
# ============================================================================


class TestCallModelWithoutBackend:
    """The canned response returned when no LLM backend is configured."""

    async def test_returns_content_key(self, agent):
        """Backend-less call yields a dict with a populated ``content`` key."""
        assert agent.llm_client.backend is None

        result = await agent._call_model([{"role": "user", "content": "hi"}])

        assert set(result) == {"content"}
        assert result["content"].strip()

    async def test_canned_response_satisfies_completion_predicate(
        self, agent, python_task
    ):
        """The stub must look 'complete' to the agent's own predicate.

        ``BaseAgent._execute_loop`` only returns once ``_is_task_complete``
        accepts the content. If the canned response ever stops matching,
        a keyless run silently degrades into a max-iterations RuntimeError
        instead of returning output -- so this is a real contract between
        two methods, not a restatement of the stub's text.
        """
        response = await agent._call_model([])

        assert await agent._is_task_complete(python_task, response["content"])

    async def test_canned_response_parses_into_output(self, agent, python_task):
        """End-to-end: the stub parses into a non-empty, coherent output."""
        response = await agent._call_model([])

        output = await agent._parse_output(python_task, response["content"])

        assert output.test_files, "canned response produced no test files"
        assert output.total_tests == sum(f.test_count for f in output.test_files)
        assert output.total_tests > 0
        assert output.raw_response == response["content"]

    async def test_run_completes_without_backend(self, python_task):
        """A keyless ``run()`` completes rather than exhausting iterations."""
        result = await TestAgent().run(python_task)

        assert result.total_tests > 0
        assert result.test_summary


class TestCallModelWithBackend:
    """Delegation to the real client when a backend is configured."""

    @pytest.fixture
    def backend(self) -> MockBackend:
        backend = MockBackend()
        backend.default_response = (
            "```test_calc.py\ndef test_add():\n    assert add(1, 2) == 3\n```"
        )
        return backend

    @pytest.fixture
    def client(self, backend) -> LLMClientWrapper:
        client = LLMClientWrapper(router=get_smart_router(), enable_cache=False)
        client.set_backend(backend)
        return client

    async def test_uses_client_response_not_stub(self, client):
        """With a backend present the canned branch must not be taken."""
        agent = TestAgent(llm_client=client)

        result = await agent._call_model([{"role": "user", "content": "gen"}])

        assert "test_calc.py" in result["content"]
        assert "test_example_function" not in result["content"]

    async def test_requests_low_temperature(self, client, monkeypatch):
        """Test generation pins temperature at 0.2 for determinism.

        Asserted at the client boundary. (``MockBackend.call_history`` now
        records ``max_tokens``/``temperature`` too, but the client boundary
        is the seam this test owns.)
        """
        agent = TestAgent(llm_client=client)
        seen: dict[str, object] = {}

        async def fake_complete_chat(*args, **kwargs):
            seen.update(kwargs)
            return {"content": "ok"}, "model-x", 1

        monkeypatch.setattr(client, "complete_chat", fake_complete_chat)

        await agent._call_model([{"role": "user", "content": "gen"}])

        assert seen["temperature"] == pytest.approx(0.2)

    async def test_reaches_the_configured_backend(self, client, backend):
        """The client actually dispatches to the backend, not the stub."""
        agent = TestAgent(llm_client=client)

        await agent._call_model([{"role": "user", "content": "gen"}])

        chat_calls = [c for c in backend.call_history if c["method"] == "complete_chat"]
        assert chat_calls, "client never reached the backend"

    async def test_falls_back_to_message_key(self, client, monkeypatch):
        """A client returning ``message`` instead of ``content`` still works."""
        agent = TestAgent(llm_client=client)

        async def fake_complete_chat(*args, **kwargs):
            return {"message": "from-message-key"}, "model-x", 7

        monkeypatch.setattr(client, "complete_chat", fake_complete_chat)

        result = await agent._call_model([])

        assert result["content"] == "from-message-key"

    async def test_missing_both_keys_yields_empty_string(self, client, monkeypatch):
        """An unrecognised response shape degrades to '' rather than KeyError."""
        agent = TestAgent(llm_client=client)

        async def fake_complete_chat(*args, **kwargs):
            return {"unexpected": "shape"}, "model-x", 0

        monkeypatch.setattr(client, "complete_chat", fake_complete_chat)

        result = await agent._call_model([])

        assert result["content"] == ""

    async def test_uses_configured_tier(self, client, monkeypatch):
        """The agent's configured tier is what gets routed on."""
        agent = TestAgent(
            config=AgentConfig(name="tiered", default_tier=ModelTier.TIER_3),
            llm_client=client,
        )
        seen: dict[str, object] = {}

        async def fake_complete_chat(*args, **kwargs):
            seen.update(kwargs)
            return {"content": "ok"}, "model-x", 1

        monkeypatch.setattr(client, "complete_chat", fake_complete_chat)

        await agent._call_model([])

        assert seen["tier"] == ModelTier.TIER_3


# ============================================================================
# _is_task_complete
# ============================================================================


class TestIsTaskComplete:
    """The 'response actually contains tests' gate."""

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param("```\ndef test_x(): pass\n```", id="python"),
            pytest.param("```\nit('works', () => {});\n```", id="jest-it"),
            pytest.param("```\nfunc TestThing(t *testing.T) {}\n```", id="go"),
            pytest.param("```\n#[test]\nfn works() {}\n```", id="rust"),
        ],
    )
    async def test_accepts_each_language_marker(self, agent, python_task, response):
        """Any one of the four language markers inside a fence is enough."""
        assert await agent._is_task_complete(python_task, response)

    @pytest.mark.parametrize(
        "response",
        [
            pytest.param("def test_x(): pass", id="tests-without-fence"),
            pytest.param("```\nprint('no tests here')\n```", id="fence-without-tests"),
            pytest.param("", id="empty"),
            pytest.param("I cannot help with that.", id="refusal"),
        ],
    )
    async def test_rejects_incomplete_responses(self, agent, python_task, response):
        """Both halves of the predicate are required."""
        assert not await agent._is_task_complete(python_task, response)


# ============================================================================
# _parse_output
# ============================================================================


class TestParseOutputSuccessFlag:
    """Regression: ``_parse_output`` must populate the required ``success``.

    ``TaskOutput.success`` is declared without a default, so a
    ``TestGenerationOutput(...)`` that omits it raises ``ValidationError``
    -- which it did for every input, making ``TestAgent.run()`` unusable.
    Nothing caught it because the existing suite only exercised the private
    parsing helpers, never ``_parse_output`` or ``run()``.
    """

    async def test_populates_success_on_a_parsed_response(self, agent, python_task):
        """A response with test files parses and reports success."""
        response = "```test_x.py\ndef test_one(): pass\n```"

        output = await agent._parse_output(python_task, response)

        assert output.success is True

    async def test_unparseable_response_reports_failure(self, agent, python_task):
        """No recoverable test file means the generation did not succeed."""
        output = await agent._parse_output(python_task, "sorry, I cannot do that")

        assert output.success is False

    async def test_run_returns_rather_than_raising(self, python_task):
        """The end-to-end contract: ``run()`` yields output, not an exception."""
        result = await TestAgent().run(python_task)

        assert result.success is True


class TestParseOutput:
    """Aggregation and the coverage-estimate heuristic."""

    async def test_sums_tests_across_files(self, agent, python_task):
        """``total_tests`` aggregates every parsed file."""
        response = (
            "```test_a.py\ndef test_one(): pass\ndef test_two(): pass\n```\n"
            "```test_b.py\ndef test_three(): pass\n```"
        )

        output = await agent._parse_output(python_task, response)

        assert len(output.test_files) == 2
        assert output.total_tests == 3

    async def test_empty_response_is_not_an_error(self, agent, python_task):
        """No fences parses to an empty, well-formed output."""
        output = await agent._parse_output(python_task, "no code blocks at all")

        assert output.test_files == []
        assert output.total_tests == 0
        assert output.test_summary == "No test files generated."

    async def test_coverage_estimate_floor(self, agent, python_task):
        """Zero tests still reports the heuristic's 40 floor."""
        output = await agent._parse_output(python_task, "nothing here")

        assert output.coverage_estimate == 40

    async def test_coverage_estimate_scales_with_test_count(self, agent, python_task):
        """Each test adds 3 points below the cap (40 + 3n)."""
        body = "\n".join(f"def test_n{i}(): pass" for i in range(4))
        response = f"```test_x.py\n{body}\n```"

        output = await agent._parse_output(python_task, response)

        assert output.total_tests == 4
        assert output.coverage_estimate == 52

    async def test_coverage_estimate_is_capped_at_95(self, agent, python_task):
        """The estimate never claims more than 95% however many tests exist."""
        body = "\n".join(f"def test_n{i}(): pass" for i in range(40))
        response = f"```test_x.py\n{body}\n```"

        output = await agent._parse_output(python_task, response)

        assert output.total_tests == 40
        assert output.coverage_estimate == 95

    async def test_preserves_raw_response(self, agent, python_task):
        """The unparsed response is retained for debugging."""
        response = "```test_x.py\ndef test_one(): pass\n```"

        output = await agent._parse_output(python_task, response)

        assert output.raw_response == response

    async def test_unknown_language_falls_back_to_python(self, agent):
        """An unmapped language is parsed with the Python config."""
        task = TestGenerationInput(code="x", language="cobol")
        response = "```test_legacy.py\ndef test_one(): pass\n```"

        output = await agent._parse_output(task, response)

        assert output.total_tests == 1


# ============================================================================
# _parse_test_files
# ============================================================================


class TestParseTestFiles:
    """Filename resolution and malformed-block handling."""

    def test_explicit_filename_is_preserved(self, agent):
        """A fence info string naming a file is used verbatim."""
        response = "```test_calc.py\ndef test_add(): pass\n```"

        files = agent._parse_test_files(response, "python", PYTHON_CONFIG)

        assert [f.filename for f in files] == ["test_calc.py"]

    def test_bare_language_fence_gets_generated_name(self, agent):
        """A plain ```python fence falls back to the generated filename."""
        response = "```python\ndef test_add(): pass\n```"

        files = agent._parse_test_files(response, "python", PYTHON_CONFIG)

        assert [f.filename for f in files] == ["test_generated.py"]

    def test_unrecognised_fence_gets_generated_name(self, agent):
        """An unknown info string also falls back rather than being dropped."""
        response = "```shell\ndef test_add(): pass\n```"

        files = agent._parse_test_files(response, "python", PYTHON_CONFIG)

        assert [f.filename for f in files] == ["test_generated.py"]

    def test_single_line_block_is_skipped(self, agent):
        """A fence with no body is skipped instead of raising."""
        response = "```python```\n```test_real.py\ndef test_x(): pass\n```"

        files = agent._parse_test_files(response, "python", PYTHON_CONFIG)

        assert [f.filename for f in files] == ["test_real.py"]

    def test_prose_between_blocks_is_ignored(self, agent):
        """Only fenced regions are treated as files."""
        response = (
            "Here is the first file:\n"
            "```test_a.py\ndef test_one(): pass\n```\n"
            "and some commentary in between\n"
            "```test_b.py\ndef test_two(): pass\n```\n"
            "trailing prose"
        )

        files = agent._parse_test_files(response, "python", PYTHON_CONFIG)

        assert [f.filename for f in files] == ["test_a.py", "test_b.py"]

    def test_content_is_stripped(self, agent):
        """Leading/trailing whitespace is trimmed off file content."""
        response = "```test_a.py\n\ndef test_one(): pass\n\n```"

        files = agent._parse_test_files(response, "python", PYTHON_CONFIG)

        assert files[0].content == "def test_one(): pass"

    def test_typescript_counts_use_the_jest_pattern(self, agent):
        """Non-Python configs count with their own regex."""
        ts_config = LANGUAGE_CONFIG["typescript"]
        response = "```test_calc.test.ts\nit('a', () => {});\ntest('b', () => {});\n```"

        files = agent._parse_test_files(response, "typescript", ts_config)

        assert [f.filename for f in files] == ["test_calc.test.ts"]
        assert files[0].test_count == 2

    def test_empty_test_prefix_swallows_the_language_fence(self, agent):
        """Characterisation test for a known quirk -- see the report.

        ``typescript``/``javascript`` set ``test_prefix = ""``, and every
        string satisfies ``str.startswith("")``. The first branch of the
        filename resolution therefore always wins for those languages, so a
        bare ```typescript fence is taken to *be* the filename and the
        ``generated.test.ts`` fallback below it is unreachable. Pinned here
        so the behaviour cannot change silently; the sensible fix (test the
        fallback branches before the prefix branch, or require a non-empty
        prefix) is a maintainer decision because it changes output filenames.
        """
        ts_config = LANGUAGE_CONFIG["typescript"]
        response = "```typescript\nit('a', () => {});\n```"

        files = agent._parse_test_files(response, "typescript", ts_config)

        assert [f.filename for f in files] == ["typescript"]

    def test_no_fences_yields_no_files(self, agent):
        """Unfenced prose parses to an empty list."""
        assert agent._parse_test_files("just prose", "python", PYTHON_CONFIG) == []


# ============================================================================
# _infer_test_type / _count_tests
# ============================================================================


class TestInferTestType:
    """Heuristic test-type classification."""

    @pytest.mark.parametrize(
        ("filename", "content", "expected"),
        [
            pytest.param("test_perf.py", "", TestType.PERFORMANCE, id="perf-filename"),
            pytest.param(
                "test_x.py",
                "performance benchmark",
                TestType.PERFORMANCE,
                id="perf-body",
            ),
            pytest.param(
                "test_security.py", "", TestType.SECURITY, id="security-filename"
            ),
            pytest.param(
                "test_x.py", "vulnerability scan", TestType.SECURITY, id="security-body"
            ),
            pytest.param("test_plain.py", "assert True", TestType.UNIT, id="unit"),
        ],
    )
    def test_classification(self, agent, filename, content, expected):
        assert agent._infer_test_type(filename, content) == expected

    def test_integration_precedes_security(self, agent):
        """Classification is first-match-wins in declaration order."""
        result = agent._infer_test_type("test_integration.py", "vulnerability")

        assert result == TestType.INTEGRATION


class TestCountTests:
    """Per-language test counting."""

    @pytest.mark.parametrize(
        ("language", "content", "expected"),
        [
            pytest.param("go", "func TestA(t *T){}\nfunc TestB(t *T){}", 2, id="go"),
            pytest.param("rust", "#[test]\nfn a(){}\n#[test]\nfn b(){}", 2, id="rust"),
            pytest.param("javascript", "it('a',()=>{});", 1, id="javascript"),
            pytest.param("PYTHON", "def test_a(): pass", 1, id="case-insensitive"),
            pytest.param("cobol", "def test_a(): pass", 1, id="unknown-uses-python"),
            pytest.param("python", "def helper(): pass", 0, id="no-tests"),
        ],
    )
    def test_counts(self, agent, language, content, expected):
        assert agent._count_tests(content, language) == expected


# ============================================================================
# _format_task_message / _generate_summary
# ============================================================================


class TestFormatTaskMessage:
    """Prompt assembly branches not covered by the happy-path tests."""

    def test_files_are_combined_when_code_is_empty(self, agent):
        """``files`` is used only when ``code`` is absent."""
        task = TestGenerationInput(
            files={"a.py": "def a(): pass", "b.py": "def b(): pass"},
            language="python",
        )

        message = agent._format_task_message(task)

        assert "a.py" in message and "b.py" in message

    def test_code_wins_over_files(self, agent):
        """When both are supplied, ``code`` takes precedence."""
        task = TestGenerationInput(
            code="def only_this(): pass",
            files={"ignored.py": "def ignored(): pass"},
        )

        message = agent._format_task_message(task)

        assert "only_this" in message
        assert "ignored.py" not in message

    @pytest.mark.parametrize(
        ("test_type", "expected"),
        [
            pytest.param(TestType.E2E, "End-to-end", id="e2e"),
            pytest.param(TestType.PERFORMANCE, "Performance", id="performance"),
            pytest.param(TestType.SECURITY, "Security", id="security"),
        ],
    )
    def test_each_test_type_is_described(self, agent, test_type, expected):
        """Every enum member contributes a prompt line."""
        task = TestGenerationInput(code="x", test_types=[test_type])

        assert expected in agent._format_task_message(task)

    def test_mocking_strategy_is_appended(self, agent):
        """An explicit mocking strategy reaches the prompt."""
        task = TestGenerationInput(code="x", mocking_strategy="patch the HTTP layer")

        message = agent._format_task_message(task)

        assert "## Mocking Strategy" in message
        assert "patch the HTTP layer" in message

    def test_mocking_section_omitted_when_unset(self, agent, python_task):
        """No strategy means no empty section."""
        assert "## Mocking Strategy" not in agent._format_task_message(python_task)

    def test_framework_override_replaces_default(self, agent):
        """An explicit framework overrides the language default."""
        task = TestGenerationInput(code="x", language="python", framework="unittest")

        message = agent._format_task_message(task)

        assert "**unittest**" in message

    def test_coverage_target_is_rendered(self, agent):
        """The requested coverage target appears in the requirements."""
        task = TestGenerationInput(code="x", coverage_target=95)

        assert ">95% code coverage" in agent._format_task_message(task)


class TestGenerateSummary:
    """Summary rendering."""

    def test_empty_file_list(self, agent, python_task):
        assert agent._generate_summary([], python_task) == "No test files generated."

    def test_counts_are_grouped_by_type(self, agent, python_task):
        """Files sharing a type have their counts summed."""
        files = [
            GeneratedTestFile(filename="a.py", test_type=TestType.UNIT, test_count=2),
            GeneratedTestFile(filename="b.py", test_type=TestType.UNIT, test_count=3),
        ]

        summary = agent._generate_summary(files, python_task)

        assert "Unit tests: 5" in summary
        assert "a.py (2 tests)" in summary
        assert "b.py (3 tests)" in summary
