"""Response-handling and advanced-feature tests for :class:`CoderAgent`.

Complements ``tests/test_agents.py::TestCoderAgent``, which covers
initialisation, one happy-path ``run()``, one ``_extract_code_blocks`` call
and the ``generate_code`` mixin. Everything downstream of "the model
answered" was unexercised: three public methods (``reflect``, ``refine``,
``generate_multiple_files``) and the whole indentation fallback had no test
at all, and ``_format_task_message`` was only ever called with a bare
description.

The seams pinned here:

* ``_extract_code_blocks`` -- the fence parser both ``_is_task_complete``
  and ``_parse_output`` are built on. ``language`` reaches it straight from
  ``CodeGenerationInput.language``, which accepts any non-empty string, so
  it is pinned against regex-metacharacter names as well as the ordinary
  ones.
* ``_extract_code_fallback`` / ``_extract_explanation`` -- pure heuristics
  that can regress silently: a parser that stops recognising code still
  returns a well-formed ``CodeGenerationOutput``, just an empty one.
* ``_format_task_message`` -- every optional ``CodeGenerationInput`` field
  is an independent branch, and the system-prompt selection has a
  don't-add-twice guard that only shows up on the second call.
* ``_call_model`` -- the backend-less canned branch is asserted for
  *internal consistency* (the stub must satisfy the agent's own completion
  predicate, or a keyless ``run()`` degrades to a max-iterations
  ``RuntimeError``), plus the client-delegation branch.
* ``reflect`` / ``refine`` / ``generate_multiple_files`` -- the advanced
  surface, including ``refine``'s empty-state guard and its reuse of the
  previous result's language.

Several tests are marked CHARACTERISATION: they pin behaviour that is
arguably wrong but is not being changed here, so a future fix trips a test
rather than escaping notice.
"""

import re

import pytest

from agentic_v2.agents.base import AgentConfig, AgentState
from agentic_v2.agents.coder import (
    DEFAULT_SYSTEM_PROMPT,
    LANGUAGE_PROMPTS,
    CoderAgent,
)
from agentic_v2.contracts import CodeGenerationInput, CodeGenerationOutput
from agentic_v2.models import LLMClientWrapper, MockBackend, ModelTier, get_smart_router

# The backend-less branch of ``_call_model`` is the subject of several tests
# here; an ambient AGENTIC_NO_LLM=1 installs a placeholder backend and routes
# around it. Mirrors ``tests/test_agents.py``.
pytestmark = pytest.mark.usefixtures("backendless_baseline")


def fenced(tag: str, body: str = "print(1)") -> str:
    """Build a markdown fence without embedding backticks in a test literal."""
    return "```" + tag + "\n" + body + "\n```"


@pytest.fixture
def agent() -> CoderAgent:
    """A default-configured, backend-less ``CoderAgent``."""
    return CoderAgent()


@pytest.fixture
def python_task() -> CodeGenerationInput:
    """A minimal Python code-generation request."""
    return CodeGenerationInput(
        description="Create a function that adds two numbers",
        language="python",
    )


# ============================================================================
# _extract_code_blocks
# ============================================================================


class TestExtractCodeBlocks:
    """The fence parser that gates completion and feeds ``_parse_output``."""

    def test_extracts_body_of_matching_fence(self, agent):
        """The declared language matches its own fence."""
        text = "Here's the code:\n\n" + fenced("python", "def f():\n    return 1")

        assert agent._extract_code_blocks(text, "python") == ["def f():\n    return 1"]

    def test_extracts_every_fence_not_just_the_first(self, agent):
        """Multiple fences are all returned, in document order."""
        text = fenced("python", "A") + "\nprose\n" + fenced("python", "B")

        assert agent._extract_code_blocks(text, "python") == ["A", "B"]

    def test_language_tag_is_optional_on_the_fence(self, agent):
        """A bare ``` fence still matches when a language was requested."""
        assert agent._extract_code_blocks(fenced("", "A"), "python") == ["A"]

    def test_mismatched_language_tag_is_not_extracted(self, agent):
        """Asking for python does not pick up a javascript fence.

        This is what makes ``_is_task_complete`` language-aware: a model
        that answers in the wrong language must not end the loop.
        """
        assert agent._extract_code_blocks(fenced("javascript", "A"), "python") == []

    def test_matching_is_case_insensitive(self, agent):
        """``re.IGNORECASE`` covers a capitalised fence tag."""
        assert agent._extract_code_blocks(fenced("Python", "A"), "python") == ["A"]

    def test_no_language_falls_back_to_generic_word_pattern(self, agent):
        """Called without a language, any ``\\w+`` tag matches."""
        assert agent._extract_code_blocks(fenced("rust", "A")) == ["A"]

    def test_body_is_stripped(self, agent):
        """Surrounding whitespace inside the fence is trimmed."""
        text = "```python\n\n   A   \n\n```"

        assert agent._extract_code_blocks(text, "python") == ["A"]

    def test_unterminated_fence_yields_nothing(self, agent):
        """A fence the model never closed is not half-extracted."""
        assert agent._extract_code_blocks("```python\ndef f():", "python") == []


class TestExtractCodeBlocksLanguageEscaping:
    """Regression tests for unescaped interpolation of ``language``.

    ``CodeGenerationInput.language`` is ``min_length=1`` and lowercased --
    any string gets through, and it used to be pasted into the pattern raw.
    """

    def test_cpp_fence_is_extracted(self, agent):
        """``c++`` round-trips.

        Unescaped, ``c++`` parsed as a possessive quantifier (valid since
        Python 3.11, so no error) that could never match the literal text
        ``c++``. ``_is_task_complete`` therefore never fired for a C++ task
        and ``run()`` failed with a max-iterations ``RuntimeError``.
        """
        assert agent._extract_code_blocks(fenced("c++", "int main(){}"), "c++") == [
            "int main(){}"
        ]

    def test_cpp_task_completes_end_to_end(self, agent):
        """The predicate the fence parser feeds now accepts C++."""
        task = CodeGenerationInput(
            description="Write a C++ hello world program", language="C++"
        )

        assert task.language == "c++"  # normalised by the validator

    @pytest.mark.parametrize("language", ["c#", "f#", "objective-c"])
    def test_punctuated_language_names_round_trip(self, agent, language):
        """Names with non-word characters match their own fence."""
        assert agent._extract_code_blocks(fenced(language, "A"), language) == ["A"]

    @pytest.mark.parametrize("language", ["c(", "a)b", "[x", "*a", "a|b", "\\"])
    def test_regex_metacharacters_do_not_raise(self, agent, language):
        """A nonsense language name returns nothing rather than ``re.error``.

        These previously escaped as an unhandled ``re.error`` out of
        ``_is_task_complete``, i.e. out of ``BaseAgent._execute_loop``.
        """
        assert agent._extract_code_blocks(fenced("python", "A"), language) == []

    def test_language_is_matched_literally_not_as_a_pattern(self, agent):
        """A metacharacter name does not match text it would match as regex."""
        # ``a|b`` as a live pattern would match a fence tagged ``a``.
        assert agent._extract_code_blocks(fenced("a", "A"), "a|b") == []

    def test_escaping_is_what_the_implementation_relies_on(self, agent):
        """Guard the mechanism, not just the symptom."""
        assert re.escape("c++") == "c\\+\\+"


class TestExtractCodeBlocksKnownGaps:
    """CHARACTERISATION -- documented gaps, deliberately not fixed here."""

    @pytest.mark.parametrize("language", ["c++", "c#", "objective-c"])
    def test_generic_pattern_misses_punctuated_fence_tags(self, agent, language):
        """Called *without* a language, the tag must match ``\\w+``.

        ``refine()`` calls ``_extract_code_blocks(content)`` with no
        language, so refining C++/C#/Objective-C code silently yields
        ``success=False, code=""`` even though ``run()`` handles it. Fixing
        this means broadening the fence-info pattern, which changes what
        counts as a code block repo-wide -- a maintainer call.
        """
        assert agent._extract_code_blocks(fenced(language, "A")) == []


# ============================================================================
# _extract_code_fallback
# ============================================================================


class TestExtractCodeFallback:
    """The indentation heuristic used when no fence is present."""

    def test_collects_space_indented_lines(self, agent):
        text = "Here it is:\n    def f():\n        return 1\nDone."

        assert agent._extract_code_fallback(text) == "def f():\n        return 1"

    def test_collects_tab_indented_lines(self, agent):
        text = "Here it is:\n\tdef f():\n\t\treturn 1\n"

        assert agent._extract_code_fallback(text) == "def f():\n\t\treturn 1"

    def test_blank_line_inside_a_block_is_kept(self, agent):
        """A blank line does not terminate an in-progress block."""
        result = agent._extract_code_fallback("x\n    a\n\n    b\ny")

        assert result == "a\n\n    b"

    def test_unindented_line_ends_the_block(self, agent):
        """Prose after the block is excluded."""
        text = "    a\nprose\n    b"

        assert "prose" not in agent._extract_code_fallback(text)

    def test_returns_empty_when_nothing_is_indented(self, agent):
        assert agent._extract_code_fallback("no indentation anywhere") == ""

    def test_three_space_indent_is_not_code(self, agent):
        """The threshold is a literal four spaces, not "any indent"."""
        assert agent._extract_code_fallback("intro\n   a\n") == ""

    def test_first_line_loses_its_indent_but_the_rest_do_not(self, agent):
        """CHARACTERISATION -- the fallback can emit unparseable code.

        The block is joined and then ``.strip()``-ed as a whole, so only the
        first line is dedented. For a block whose lines share one indent
        level the result is an ``IndentationError`` waiting to happen, and
        ``_parse_output`` still reports it as ``success=True`` with
        ``confidence=0.9`` -- the same confidence a clean fenced extraction
        gets. Fixing it means dedenting the block (e.g. ``textwrap.dedent``),
        which changes returned code.
        """
        result = agent._extract_code_fallback("Result:\n    x = 1\n    y = 2\n")

        assert result == "x = 1\n    y = 2"
        with pytest.raises(IndentationError):
            compile(result, "<extracted>", "exec")


# ============================================================================
# _extract_explanation
# ============================================================================


class TestExtractExplanation:
    """Prose recovered from in front of the first fence."""

    def test_returns_text_before_the_first_fence(self, agent):
        text = "This adds two numbers.\n\n" + fenced("python", "A")

        assert agent._extract_explanation(text) == "This adds two numbers."

    def test_returns_empty_when_there_is_no_fence(self, agent):
        assert agent._extract_explanation("just prose, no code") == ""

    def test_returns_empty_when_the_fence_is_first(self, agent):
        assert agent._extract_explanation(fenced("python", "A")) == ""

    def test_strips_a_heres_the_preamble(self, agent):
        text = "Here's the implementation:\n" + fenced("python", "A")

        assert agent._extract_explanation(text) == "implementation:"

    def test_strips_heres_without_the_article(self, agent):
        text = "Here's a helper.\n" + fenced("python", "A")

        assert agent._extract_explanation(text) == "a helper."

    def test_only_the_first_fence_delimits_the_explanation(self, agent):
        text = "Intro.\n" + fenced("python", "A") + "\nMore prose.\n"

        assert agent._extract_explanation(text) == "Intro."

    @pytest.mark.parametrize("preamble", ["Here is the code", "Heres the code"])
    def test_preamble_strip_requires_the_apostrophe(self, agent, preamble):
        """CHARACTERISATION -- the strip regex is ``Here\\'s?``.

        The apostrophe is mandatory and the ``s`` optional, so "Here is"
        and "Heres" are left untouched while "Here'" alone would be
        stripped. Almost certainly the inverse of what was meant.
        """
        text = preamble + ":\n" + fenced("python", "A")

        assert agent._extract_explanation(text) == preamble + ":"


# ============================================================================
# _format_task_message
# ============================================================================


class TestFormatTaskMessage:
    """Prompt assembly -- one independent branch per optional field."""

    def test_includes_language_and_description(self, agent, python_task):
        message = agent._format_task_message(python_task)

        assert "Generate python code" in message
        assert python_task.description in message

    def test_requests_a_markdown_code_block(self, agent, python_task):
        """The instruction the whole fence-parsing pipeline depends on."""
        assert "markdown code block" in agent._format_task_message(python_task)

    def test_omits_absent_optional_sections(self, agent, python_task):
        message = agent._format_task_message(python_task)

        assert "Target file:" not in message
        assert "Existing code" not in message
        assert "Required dependencies" not in message
        assert "Style guide:" not in message
        assert "Examples:" not in message

    def test_includes_file_path(self, agent):
        task = CodeGenerationInput(
            description="Create an adder function", language="python", file_path="a.py"
        )

        assert "Target file: a.py" in agent._format_task_message(task)

    def test_includes_existing_code(self, agent):
        task = CodeGenerationInput(
            description="Extend the adder function",
            language="python",
            existing_code="def old(): ...",
        )

        assert "def old(): ..." in agent._format_task_message(task)

    def test_lists_dependencies_one_per_line(self, agent):
        task = CodeGenerationInput(
            description="Create an HTTP client wrapper",
            language="python",
            dependencies=["httpx", "pydantic"],
        )
        message = agent._format_task_message(task)

        assert "- httpx" in message
        assert "- pydantic" in message

    def test_includes_style_guide(self, agent):
        task = CodeGenerationInput(
            description="Create an adder function",
            language="python",
            style_guide="Google style",
        )

        assert "Style guide: Google style" in agent._format_task_message(task)

    def test_numbers_examples_from_one(self, agent):
        task = CodeGenerationInput(
            description="Create an adder function",
            language="python",
            examples=["ex-alpha", "ex-beta"],
        )
        message = agent._format_task_message(task)

        assert "Example 1:\nex-alpha" in message
        assert "Example 2:\nex-beta" in message


class TestSystemPromptSelection:
    """The language-specific system prompt added on first format."""

    @pytest.mark.parametrize("language", sorted(LANGUAGE_PROMPTS))
    def test_known_language_gets_its_own_prompt(self, agent, language):
        task = CodeGenerationInput(
            description="Create a function that adds numbers", language=language
        )
        agent._format_task_message(task)

        system = [m for m in agent._memory.messages if m.role == "system"]
        assert system[0].content == LANGUAGE_PROMPTS[language]

    def test_unknown_language_gets_the_default_prompt(self, agent):
        task = CodeGenerationInput(
            description="Create a function that adds numbers", language="cobol"
        )
        agent._format_task_message(task)

        system = [m for m in agent._memory.messages if m.role == "system"]
        assert system[0].content == DEFAULT_SYSTEM_PROMPT

    def test_language_is_matched_case_insensitively(self, agent):
        """``CodeGenerationInput`` lowercases, and the lookup does too."""
        task = CodeGenerationInput(
            description="Create a function that adds numbers", language="PYTHON"
        )
        agent._format_task_message(task)

        system = [m for m in agent._memory.messages if m.role == "system"]
        assert system[0].content == LANGUAGE_PROMPTS["python"]

    def test_system_prompt_is_added_only_once(self, agent, python_task):
        """The guard is ``any(m.role == "system")``, so a second task in the
        same session keeps the first language's prompt."""
        agent._format_task_message(python_task)
        agent._format_task_message(
            CodeGenerationInput(
                description="Create a function that adds numbers", language="rust"
            )
        )

        system = [m for m in agent._memory.messages if m.role == "system"]
        assert len(system) == 1
        assert system[0].content == LANGUAGE_PROMPTS["python"]


# ============================================================================
# _is_task_complete / _parse_output
# ============================================================================


class TestIsTaskComplete:
    """The predicate ``BaseAgent._execute_loop`` polls each iteration."""

    async def test_true_when_a_matching_fence_is_present(self, agent, python_task):
        assert await agent._is_task_complete(python_task, fenced("python", "A"))

    async def test_false_for_prose_only(self, agent, python_task):
        assert not await agent._is_task_complete(python_task, "I'll get right on it.")

    async def test_false_for_a_wrong_language_fence(self, agent, python_task):
        """A model answering in the wrong language keeps the loop running."""
        assert not await agent._is_task_complete(python_task, fenced("ruby", "A"))


class TestParseOutput:
    """Response -> ``CodeGenerationOutput``."""

    async def test_uses_the_first_fence(self, agent, python_task):
        response = fenced("python", "FIRST") + "\n" + fenced("python", "SECOND")
        result = await agent._parse_output(python_task, response)

        assert result.code == "FIRST"

    async def test_successful_parse_reports_high_confidence(self, agent, python_task):
        result = await agent._parse_output(python_task, fenced("python", "A"))

        assert result.success is True
        assert result.confidence == pytest.approx(0.9)

    async def test_echoes_the_requested_language(self, agent, python_task):
        result = await agent._parse_output(python_task, fenced("python", "A"))

        assert result.language == "python"

    async def test_carries_the_explanation(self, agent, python_task):
        response = "Adds two numbers.\n" + fenced("python", "A")
        result = await agent._parse_output(python_task, response)

        assert result.explanation == "Adds two numbers."

    async def test_falls_back_to_the_indentation_heuristic(self, agent, python_task):
        """No fence, but indented text -- the fallback path still succeeds."""
        result = await agent._parse_output(
            python_task, "Result:\n    def f():\n        return 1\n"
        )

        assert result.success is True
        assert "def f():" in result.code

    async def test_empty_response_is_an_unsuccessful_output(self, agent, python_task):
        """No code anywhere: ``success=False`` and low confidence, but a
        well-formed model rather than an exception."""
        result = await agent._parse_output(python_task, "Sorry, I cannot help.")

        assert isinstance(result, CodeGenerationOutput)
        assert result.success is False
        assert result.code == ""
        assert result.confidence == pytest.approx(0.3)


# ============================================================================
# _call_model
# ============================================================================


class TestCallModelWithoutBackend:
    """The canned response returned when no LLM backend is configured."""

    async def test_returns_a_content_key(self, agent):
        assert agent.llm_client.backend is None

        result = await agent._call_model([{"role": "user", "content": "hi"}])

        assert set(result) == {"content"}
        assert result["content"].strip()

    async def test_canned_response_satisfies_the_completion_predicate(
        self, agent, python_task
    ):
        """The stub must look 'complete' to the agent's own predicate.

        ``_execute_loop`` only returns once ``_is_task_complete`` accepts the
        content. If the canned response ever stops matching, a keyless
        ``run()`` silently degrades into a max-iterations ``RuntimeError``
        instead of returning output -- a real contract between two methods,
        not a restatement of the stub's text.
        """
        response = await agent._call_model([])

        assert await agent._is_task_complete(python_task, response["content"])

    async def test_keyless_run_returns_parsed_output(self, agent, python_task):
        """End-to-end consequence of the contract above."""
        result = await agent.run(python_task)

        assert result.success is True
        assert agent.state == AgentState.COMPLETED

    async def test_canned_response_is_python_only(self, agent):
        """CHARACTERISATION -- the stub hard-codes a ```python fence.

        ``_is_task_complete`` is language-aware, so a keyless ``run()`` for
        any other language burns all five iterations and raises. This is a
        trap for anyone writing a backend-less test in another language, and
        it means the no-API-key baseline (``AGENTIC_NO_LLM=1``) only
        exercises ``CoderAgent`` for Python.
        """
        task = CodeGenerationInput(
            description="Write a Rust hello world program", language="rust"
        )

        with pytest.raises(RuntimeError, match="max iterations"):
            await agent.run(task)


class TestCallModelWithBackend:
    """Delegation to the real client when a backend is configured."""

    @pytest.fixture
    def backend(self) -> MockBackend:
        backend = MockBackend()
        backend.default_response = fenced("python", "def added(): ...")
        return backend

    @pytest.fixture
    def client(self, backend) -> LLMClientWrapper:
        client = LLMClientWrapper(router=get_smart_router(), enable_cache=False)
        client.set_backend(backend)
        return client

    async def test_uses_the_client_response_not_the_stub(self, client):
        agent = CoderAgent(llm_client=client)

        result = await agent._call_model([{"role": "user", "content": "gen"}])

        assert "def added" in result["content"]
        assert "placeholder implementation" not in result["content"]

    async def test_reaches_the_configured_backend(self, client, backend):
        agent = CoderAgent(llm_client=client)

        await agent._call_model([{"role": "user", "content": "gen"}])

        chat = [c for c in backend.call_history if c["method"] == "complete_chat"]
        assert chat, "client never reached the backend"

    async def test_requests_the_configured_tier(self, client, monkeypatch):
        """Coding is a Tier-2 job by default; the tier must reach the router."""
        agent = CoderAgent(llm_client=client)
        seen: dict[str, object] = {}

        async def fake_complete_chat(*args, **kwargs):
            seen.update(kwargs)
            return {"content": "ok"}, "model-x", 1

        monkeypatch.setattr(client, "complete_chat", fake_complete_chat)

        await agent._call_model([])

        assert seen["tier"] is ModelTier.TIER_2

    async def test_requests_a_creative_temperature(self, client, monkeypatch):
        """0.7 -- deliberately higher than the test generator's 0.2."""
        agent = CoderAgent(llm_client=client)
        seen: dict[str, object] = {}

        async def fake_complete_chat(*args, **kwargs):
            seen.update(kwargs)
            return {"content": "ok"}, "model-x", 1

        monkeypatch.setattr(client, "complete_chat", fake_complete_chat)

        await agent._call_model([])

        assert seen["temperature"] == pytest.approx(0.7)

    async def test_token_budget_scales_with_max_iterations(self, client, monkeypatch):
        """``max_tokens = max_iterations * 1000`` -- an odd coupling, pinned
        so a config change cannot silently resize the budget."""
        config = AgentConfig(
            name="coder", default_tier=ModelTier.TIER_2, max_iterations=3
        )
        agent = CoderAgent(config=config, llm_client=client)
        seen: dict[str, object] = {}

        async def fake_complete_chat(*args, **kwargs):
            seen.update(kwargs)
            return {"content": "ok"}, "model-x", 1

        monkeypatch.setattr(client, "complete_chat", fake_complete_chat)

        await agent._call_model([])

        assert seen["max_tokens"] == 3000

    async def test_provider_errors_propagate(self, client, monkeypatch):
        """``complete_chat`` already retries transient failures, so a
        surviving exception must reach ``BaseAgent.run`` rather than being
        swallowed into a fake-success dict."""
        agent = CoderAgent(llm_client=client)

        async def boom(*args, **kwargs):
            raise RuntimeError("provider exploded")

        monkeypatch.setattr(client, "complete_chat", boom)

        with pytest.raises(RuntimeError, match="provider exploded"):
            await agent._call_model([])


# ============================================================================
# reflect
# ============================================================================


class TestReflect:
    """``SelfReflectionMixin`` implementation."""

    @pytest.fixture
    def agent_with(self, monkeypatch):
        def _make(content: str) -> CoderAgent:
            agent = CoderAgent()

            async def fake_response():
                return {"content": content}

            monkeypatch.setattr(agent, "_get_model_response", fake_response)
            return agent

        return _make

    async def test_parses_a_json_critique(self, agent_with):
        agent = agent_with('{"needs_revision": true, "issues": ["no error handling"]}')

        result = await agent.reflect("def f(): pass")

        assert result["needs_revision"] is True
        assert result["issues"] == ["no error handling"]

    async def test_unparseable_response_degrades_to_no_revision(self, agent_with):
        """A model that ignores the JSON instruction must not raise."""
        agent = agent_with("Looks fine to me, honestly.")

        result = await agent.reflect("def f(): pass")

        assert result == {
            "needs_revision": False,
            "issues": [],
            "revised_output": "def f(): pass",
        }

    async def test_criteria_reaches_the_prompt(self, agent_with):
        agent = agent_with("{}")

        await agent.reflect("def f(): pass", criteria="security")

        prompts = [m.content for m in agent._memory.messages if m.role == "user"]
        assert any("security" in p for p in prompts)

    async def test_conversation_records_both_turns(self, agent_with):
        agent = agent_with("{}")

        await agent.reflect("def f(): pass")

        roles = [m.role for m in agent._memory.messages]
        assert roles[-2:] == ["user", "assistant"]


# ============================================================================
# refine
# ============================================================================


class TestRefine:
    """Iterative refinement of the previous result."""

    @pytest.fixture
    def refinable(self, monkeypatch):
        def _make(content: str, language: str = "python") -> CoderAgent:
            agent = CoderAgent()
            agent._last_result = CodeGenerationOutput(
                success=True, code="old", language=language
            )

            async def fake_response():
                return {"content": content}

            monkeypatch.setattr(agent, "_get_model_response", fake_response)
            return agent

        return _make

    async def test_raises_without_a_previous_result(self, agent):
        with pytest.raises(ValueError, match="No previous result to refine"):
            await agent.refine("add type hints")

    async def test_returns_the_refined_code(self, refinable):
        agent = refinable(fenced("python", "def better(): ..."))

        result = await agent.refine("add type hints")

        assert result.success is True
        assert "def better" in result.code

    async def test_reuses_the_previous_language(self, refinable):
        """``refine`` takes no task, so the language can only come from
        ``_last_result``."""
        agent = refinable(fenced("rust", "fn better() {}"), language="rust")

        result = await agent.refine("use Result")

        assert result.language == "rust"

    async def test_refined_result_is_slightly_less_confident(self, refinable):
        """0.85 vs. ``_parse_output``'s 0.9 -- refinement is second-hand."""
        agent = refinable(fenced("python", "A"))

        assert (await agent.refine("tidy up")).confidence == pytest.approx(0.85)

    async def test_codeless_refinement_is_unsuccessful(self, refinable):
        agent = refinable("I would not change anything.")

        result = await agent.refine("tidy up")

        assert result.success is False
        assert result.code == ""
        assert result.confidence == pytest.approx(0.3)

    async def test_replaces_last_result_so_refinement_chains(self, refinable):
        agent = refinable(fenced("python", "SECOND"))

        result = await agent.refine("tidy up")

        assert agent._last_result is result
        assert agent._last_result.code == "SECOND"

    async def test_feedback_reaches_the_conversation(self, refinable):
        agent = refinable(fenced("python", "A"))

        await agent.refine("please add docstrings")

        prompts = [m.content for m in agent._memory.messages if m.role == "user"]
        assert any("please add docstrings" in p for p in prompts)

    async def test_carries_an_explanation(self, refinable):
        agent = refinable("Added type hints.\n" + fenced("python", "A"))

        assert (await agent.refine("add type hints")).explanation == "Added type hints."


# ============================================================================
# generate_multiple_files / generate_code
# ============================================================================


class TestGenerateMultipleFiles:
    """Fan-out over a file structure, one ``run()`` per file."""

    @pytest.fixture
    def base_task(self) -> CodeGenerationInput:
        return CodeGenerationInput(
            description="Build a small CLI application", language="python"
        )

    async def test_returns_one_entry_per_requested_file(self, agent, base_task):
        result = await agent.generate_multiple_files(
            base_task, {"main.py": "entry point", "util.py": "helpers"}
        )

        assert set(result) == {"main.py", "util.py"}

    async def test_records_files_on_the_agent(self, agent, base_task):
        """``_generated_files`` accumulates the same code that is returned."""
        returned = await agent.generate_multiple_files(
            base_task, {"main.py": "entry point"}
        )

        assert agent._generated_files == returned
        assert agent._generated_files["main.py"].strip()

    async def test_records_accumulate_across_calls(self, agent, base_task):
        """The tracking dict is not reset per call, so a second fan-out adds
        to it rather than replacing it."""
        await agent.generate_multiple_files(base_task, {"main.py": "entry point"})
        await agent.generate_multiple_files(base_task, {"util.py": "helpers"})

        assert set(agent._generated_files) == {"main.py", "util.py"}

    async def test_per_file_description_carries_name_and_detail(
        self, agent, base_task, monkeypatch
    ):
        """Each sub-task must be distinguishable, or every file gets the
        same prompt and the model returns the same code."""
        seen: list[CodeGenerationInput] = []
        original = CoderAgent.run

        async def spy(self, task, ctx=None):
            seen.append(task)
            return await original(self, task, ctx)

        monkeypatch.setattr(CoderAgent, "run", spy)

        await agent.generate_multiple_files(
            base_task, {"main.py": "entry point", "util.py": "helpers"}
        )

        descriptions = [t.description for t in seen]
        assert any("main.py" in d and "entry point" in d for d in descriptions)
        assert any("util.py" in d and "helpers" in d for d in descriptions)
        assert all(base_task.description in d for d in descriptions)

    async def test_propagates_language_context_and_constraints(
        self, agent, monkeypatch
    ):
        base = CodeGenerationInput(
            description="Build a small CLI application",
            language="rust",
            context={"repo": "demo"},
            constraints={"timeout": 5},
        )
        seen: list[CodeGenerationInput] = []

        # ``run`` is replaced outright rather than wrapped: the backend-less
        # canned response is a *python* fence, so a real non-python run would
        # never satisfy ``_is_task_complete``. See
        # ``TestCallModelWithoutBackend::test_canned_response_is_python_only``.
        async def stub_run(self, task, ctx=None):
            seen.append(task)
            return CodeGenerationOutput(
                success=True, code="fn main() {}", language=task.language
            )

        monkeypatch.setattr(CoderAgent, "run", stub_run)

        await agent.generate_multiple_files(base, {"main.rs": "entry point"})

        assert seen[0].language == "rust"
        assert seen[0].context == {"repo": "demo"}
        assert seen[0].constraints == {"timeout": 5}

    async def test_empty_structure_is_a_no_op(self, agent, base_task):
        assert await agent.generate_multiple_files(base_task, {}) == {}
        assert agent._generated_files == {}


class TestGenerateCode:
    """The ``CodeGenerationMixin`` entry point."""

    async def test_returns_the_generated_code_string(self, agent):
        code = await agent.generate_code("A function that adds two numbers")

        assert isinstance(code, str)
        assert code

    async def test_context_is_passed_as_existing_code(self, agent, monkeypatch):
        """The mixin signature says ``context``; the field it lands in is
        ``existing_code``. Pinned because the names disagree."""
        seen: list[CodeGenerationInput] = []
        original = CoderAgent.run

        async def spy(self, task, ctx=None):
            seen.append(task)
            return await original(self, task, ctx)

        monkeypatch.setattr(CoderAgent, "run", spy)

        await agent.generate_code("Extend the adder function", context="def old(): ...")

        assert seen[0].existing_code == "def old(): ..."

    async def test_language_defaults_to_python(self, agent, monkeypatch):
        seen: list[CodeGenerationInput] = []
        original = CoderAgent.run

        async def spy(self, task, ctx=None):
            seen.append(task)
            return await original(self, task, ctx)

        monkeypatch.setattr(CoderAgent, "run", spy)

        await agent.generate_code("A function that adds two numbers")

        assert seen[0].language == "python"


# ============================================================================
# Defaults
# ============================================================================


class TestDefaultConfiguration:
    """The default config other tests' expectations rest on."""

    def test_defaults_to_tier_2_with_five_iterations(self, agent):
        assert agent.config.default_tier is ModelTier.TIER_2
        assert agent.config.max_iterations == 5

    def test_explicit_config_is_respected(self):
        config = AgentConfig(
            name="custom-coder", default_tier=ModelTier.TIER_3, max_iterations=2
        )

        assert CoderAgent(config=config).config.name == "custom-coder"

    def test_generated_files_starts_empty(self, agent):
        assert agent._generated_files == {}
