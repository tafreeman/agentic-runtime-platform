"""Agent specialized for LLM-driven code generation.

Provides :class:`CoderAgent`, a :class:`~agentic_v2.agents.base.BaseAgent`
subclass that generates code from natural-language descriptions.  Features
include language-specific system prompts (Python, TypeScript, JavaScript,
Rust, Go), markdown code-block extraction, multi-file generation, and
iterative refinement via conversational context.
"""

from __future__ import annotations

import re
from typing import Any

from ..contracts import CodeGenerationInput, CodeGenerationOutput
from ..models import ModelTier
from .base import AgentConfig, BaseAgent
from .capabilities import CodeGenerationMixin, SelfReflectionMixin

# Language-specific system prompts
LANGUAGE_PROMPTS = {
    "python": """You are an expert Python developer. Follow PEP 8 style guidelines.
Use type hints for function parameters and return values.
Write docstrings for public functions and classes.
Prefer list comprehensions and generators where appropriate.""",
    "typescript": """You are an expert TypeScript developer. Use strict typing.
Prefer interfaces over type aliases for object shapes.
Use async/await for asynchronous code.
Follow ESLint recommended rules.""",
    "javascript": """You are an expert JavaScript developer.
Use modern ES6+ syntax (const, let, arrow functions, etc.).
Use async/await for asynchronous code.
Follow ESLint recommended rules.""",
    "rust": """You are an expert Rust developer.
Follow the Rust API guidelines.
Use proper error handling with Result and Option.
Prefer owned types in public APIs.""",
    "go": """You are an expert Go developer.
Follow Effective Go guidelines.
Use proper error handling (no panic for recoverable errors).
Keep packages focused and interfaces small.""",
}

DEFAULT_SYSTEM_PROMPT = """You are an expert software developer.
Write clean, well-documented, and efficient code.
Follow best practices for the target language.
Include appropriate error handling."""


class CoderAgent(
    BaseAgent[CodeGenerationInput, CodeGenerationOutput],
    CodeGenerationMixin,
    SelfReflectionMixin,
):
    """Agent that generates source code from natural-language descriptions.

    Extends :class:`~agentic_v2.agents.base.BaseAgent` with
    :class:`~agentic_v2.agents.capabilities.CodeGenerationMixin` and
    implements:

    - **Language-specific prompting**: Selects a system prompt tailored to
      the target language from ``LANGUAGE_PROMPTS``.
    - **Code-block extraction**: Parses markdown fenced code blocks from
      model responses, with an indentation-based fallback.
    - **Multi-file generation**: :meth:`generate_multiple_files` produces
      code for a structured file tree in a single session.
    - **Iterative refinement**: :meth:`refine` continues the conversation
      with feedback to improve previously generated code.

    Args:
        config: Agent configuration. Defaults to a Tier-2 coder config
            with 5 max iterations.
        **kwargs: Passed through to :class:`BaseAgent.__init__`.
    """

    def __init__(self, config: AgentConfig | None = None, **kwargs):
        # Default config for coder
        if config is None:
            config = AgentConfig(
                name="coder",
                description="Code generation agent",
                default_tier=ModelTier.TIER_2,
                max_iterations=5,
            )

        super().__init__(config=config, **kwargs)

        # Track generated files
        self._generated_files: dict[str, str] = {}

    async def _on_initialize(self) -> None:
        """Initialize with language-specific prompt."""
        # Will be set per-task based on language
        pass

    def _format_task_message(self, task: CodeGenerationInput) -> str:
        """Format code generation task."""
        # Set language-specific system prompt
        lang = task.language.lower()
        system_prompt = LANGUAGE_PROMPTS.get(lang, DEFAULT_SYSTEM_PROMPT)

        # Add to memory if not already there
        if not any(m.role == "system" for m in self._memory.messages):
            self._memory.add_system(system_prompt)

        # Build task message
        parts = [f"Generate {lang} code for the following:\n\n{task.description}"]

        if task.file_path:
            parts.append(f"\nTarget file: {task.file_path}")

        if task.existing_code:
            parts.append(f"\nExisting code to modify:\n```\n{task.existing_code}\n```")

        if task.dependencies:
            parts.append("\nRequired dependencies:")
            for dep in task.dependencies:
                parts.append(f"- {dep}")

        if task.style_guide:
            parts.append(f"\nStyle guide: {task.style_guide}")

        if task.examples:
            parts.append("\nExamples:")
            for i, ex in enumerate(task.examples, 1):
                parts.append(f"\nExample {i}:\n{ex}")

        parts.append("\n\nProvide the code in a markdown code block.")

        return "\n".join(parts)

    async def _is_task_complete(self, task: CodeGenerationInput, response: str) -> bool:
        """Check if response contains valid code."""
        # Look for code blocks
        code_blocks = self._extract_code_blocks(response, task.language)
        return len(code_blocks) > 0

    async def _parse_output(
        self, task: CodeGenerationInput, response: str
    ) -> CodeGenerationOutput:
        """Parse response into CodeGenerationOutput."""
        code_blocks = self._extract_code_blocks(response, task.language)

        if not code_blocks:
            # Try to extract any code-like content
            code = self._extract_code_fallback(response)
        else:
            code = code_blocks[0]

        # Extract explanation (text before first code block)
        explanation = self._extract_explanation(response)

        return CodeGenerationOutput(
            success=bool(code),
            code=code,
            language=task.language,
            explanation=explanation,
            confidence=0.9 if code else 0.3,
        )

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Call LLM for code generation using the SmartRouter.

        Uses the LLMClientWrapper to intelligently route to available
        models with automatic fallback and retries.
        """
        # Check if we have a configured backend
        if self.llm_client.backend is None:
            # Fall back to mock response for testing
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    break

            return {"content": """Here's the code you requested:

```python
def example():
    \"\"\"Example function.\"\"\"
    pass
```

This is a placeholder implementation."""}

        # Use the real LLM client with smart routing
        try:
            result_dict, _, _ = await self.llm_client.complete_chat(
                tier=self.config.default_tier,
                messages=messages,
                max_tokens=self.config.max_iterations * 1000,
                temperature=0.7,
                tools=tools,
            )
            return result_dict
        except Exception as e:
            # Log error and return informative message
            return {
                "content": f"Error calling LLM: {e}",
                "tool_calls": None,
            }

    def _extract_code_blocks(self, text: str, language: str | None = None) -> list[str]:
        """Extract code blocks from markdown."""
        # Pattern for ```language\ncode\n```
        if language:
            pattern = rf"```(?:{language}|{language.lower()})?\s*\n(.*?)```"
        else:
            pattern = r"```(?:\w+)?\s*\n(.*?)```"

        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        return [m.strip() for m in matches]

    def _extract_code_fallback(self, text: str) -> str:
        """Extract code-like content when no code blocks found."""
        # Look for indented blocks
        lines = text.split("\n")
        code_lines = []
        in_code = False

        for line in lines:
            if line.startswith("    ") or line.startswith("\t"):
                in_code = True
                code_lines.append(line)
            elif in_code and line.strip() == "":
                code_lines.append(line)
            else:
                in_code = False

        return "\n".join(code_lines).strip()

    def _extract_explanation(self, text: str) -> str:
        """Extract explanation text before code blocks."""
        # Find first code block
        match = re.search(r"```", text)
        if match:
            explanation = text[: match.start()].strip()
            # Clean up
            explanation = re.sub(
                r"^Here\'s?\s*(the\s+)?", "", explanation, flags=re.IGNORECASE
            )
            return explanation.strip()
        return ""

    # -------------------------------------------------------------------------
    # CodeGenerationMixin implementation
    # -------------------------------------------------------------------------

    async def generate_code(
        self, description: str, language: str = "python", context: str | None = None
    ) -> str:
        """Generate code from description."""
        task = CodeGenerationInput(
            description=description,
            language=language,
            existing_code=context,  # Use existing_code for context
        )

        result = await self.run(task)
        return result.code

    # -------------------------------------------------------------------------
    # SelfReflectionMixin implementation
    # -------------------------------------------------------------------------

    async def reflect(
        self, output: str, criteria: str = "correctness"
    ) -> dict[str, Any]:
        """Critique generated code and suggest revisions.

        Uses the LLM to review the agent's own output against the
        specified criteria dimension.
        """
        reflection_prompt = (
            f"Review the following code for {criteria} issues. "
            f"Return a JSON object with 'needs_revision' (bool), "
            f"'issues' (list of strings), and optionally "
            f"'revised_output' (str).\n\n"
            f"```\n{output}\n```"
        )
        self._memory.add_user(reflection_prompt)
        response = await self._get_model_response()
        content = response.get("content", "")
        self._memory.add_assistant(content)

        try:
            from .json_extraction import extract_json

            return extract_json(content)
        except Exception:
            return {
                "needs_revision": False,
                "issues": [],
                "revised_output": output,
            }

    # -------------------------------------------------------------------------
    # Advanced features
    # -------------------------------------------------------------------------

    async def refine(self, feedback: str) -> CodeGenerationOutput:
        """Refine the last generated code based on feedback.

        Continues the conversation with refinement request.
        """
        if not self._last_result:
            raise ValueError("No previous result to refine")

        # Add feedback to conversation
        self._memory.add_user(
            f"Please refine the code based on this feedback:\n{feedback}"
        )

        # Get refined response
        response = await self._get_model_response()
        content = response.get("content", "")
        self._memory.add_assistant(content)

        # Parse as new output
        # Reuse the language from last result
        code_blocks = self._extract_code_blocks(content)
        code = code_blocks[0] if code_blocks else ""

        result = CodeGenerationOutput(
            success=bool(code),
            code=code,
            language=self._last_result.language,
            explanation=self._extract_explanation(content),
            confidence=0.85 if code else 0.3,
        )

        self._last_result = result
        return result

    async def generate_multiple_files(
        self, task: CodeGenerationInput, file_structure: dict[str, str]
    ) -> dict[str, str]:
        """Generate code for multiple files.

        Args:
            task: Base task description
            file_structure: Dict of filename -> description

        Returns:
            Dict of filename -> generated code
        """
        results = {}

        for filename, description in file_structure.items():
            # Create task for this file
            file_task = CodeGenerationInput(
                description=f"{task.description}\n\nFile: {filename}\n{description}",
                language=task.language,
                context=task.context,
                constraints=task.constraints,
            )

            result = await self.run(file_task)
            results[filename] = result.code
            self._generated_files[filename] = result.code

        return results
