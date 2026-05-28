"""Code quality metrics for evaluation.

Provides functions for assessing code quality including linting,
complexity analysis, and style checking.
"""

from __future__ import annotations

import ast
import re


def code_quality_score(
    code: str,
    language: str = "python",
) -> float:
    """Calculate overall code quality score.

    Combines multiple quality signals into a single score.

    Args:
        code: Source code to evaluate.
        language: Programming language (default: "python").

    Returns:
        Quality score between 0.0 and 1.0.

    Example:
        >>> code_quality_score("def foo(x):\\n    return x + 1")
        0.85  # Approximately
    """
    if not code or not code.strip():
        return 0.0

    scores = []

    # Check basic structure
    structure_score = _check_structure(code, language)
    scores.append(structure_score)

    # Check for common issues
    issue_score = _check_common_issues(code)
    scores.append(issue_score)

    # For Python, check AST validity
    if language.lower() == "python":
        syntax_score = _check_python_syntax(code)
        scores.append(syntax_score)

    return sum(scores) / len(scores) if scores else 0.0


def lint_score(
    code: str,
    language: str = "python",
) -> tuple[float, list[str]]:
    """Calculate lint score and return issues found.

    Args:
        code: Source code to evaluate.
        language: Programming language.

    Returns:
        Tuple of (score, list of issue descriptions).
        Score is between 0.0 and 1.0.

    Example:
        >>> score, issues = lint_score("x=1")
        >>> score
        0.8
        >>> issues
        ['Missing spaces around operator']
    """
    if not code or not code.strip():
        return 0.0, ["Empty code"]

    issues: list[str] = []

    # Check whitespace issues
    if re.search(r"[^\s]=|=[^\s=]", code):
        issues.append("Missing spaces around assignment operator")

    # Check line length
    for i, line in enumerate(code.split("\n"), 1):
        if len(line) > 120:
            issues.append(f"Line {i} exceeds 120 characters")

    # Check trailing whitespace
    if re.search(r" +\n", code):
        issues.append("Trailing whitespace detected")

    # Check for TODO/FIXME
    if re.search(r"(TODO|FIXME|XXX|HACK)", code, re.IGNORECASE):
        issues.append("Contains TODO/FIXME comments")

    # Check for print statements (in Python)
    if language.lower() == "python" and re.search(r"\bprint\s*\(", code):
        issues.append("Contains print statements (consider using logging)")

    # Calculate score (start at 1.0, deduct for issues)
    deduction_per_issue = 0.1
    score = max(0.0, 1.0 - len(issues) * deduction_per_issue)

    return score, issues


def complexity_score(
    code: str,
    language: str = "python",
    max_complexity: int = 10,
) -> float:
    """Calculate complexity score based on cyclomatic complexity.

    Lower complexity = higher score.

    Args:
        code: Source code to evaluate.
        language: Programming language.
        max_complexity: Maximum acceptable complexity (default: 10).

    Returns:
        Complexity score between 0.0 and 1.0.
        1.0 means low/acceptable complexity.

    Example:
        >>> complexity_score("def foo(): return 1")
        1.0
    """
    if not code or not code.strip():
        return 0.0

    if language.lower() != "python":
        # For non-Python, use heuristic based on control flow keywords
        complexity = _estimate_complexity_heuristic(code)
    else:
        complexity = _calculate_python_complexity(code)

    # Score: 1.0 if complexity <= max_complexity, decreasing linearly
    if complexity <= max_complexity:
        return 1.0

    # Linear decay from max_complexity to 2*max_complexity
    excess = complexity - max_complexity
    return max(0.0, 1.0 - (excess / max_complexity))


def _check_structure(code: str, language: str) -> float:
    """Check code structure quality."""
    score = 1.0
    lines = code.split("\n")

    # Check for reasonable line count
    if len(lines) > 500:
        score -= 0.2

    # Check for function/class definitions (indicates organization)
    if language.lower() == "python":
        has_definitions = bool(re.search(r"^\s*(def |class )", code, re.MULTILINE))
        if has_definitions:
            score += 0.1

    # Check for docstrings
    if '"""' in code or "'''" in code:
        score += 0.1

    return min(1.0, max(0.0, score))


def _check_common_issues(code: str) -> float:
    """Check for common code issues."""
    score = 1.0

    # Check for hardcoded credentials patterns
    credential_patterns = [
        r"password\s*=\s*['\"][^'\"]+['\"]",
        r"api_key\s*=\s*['\"][^'\"]+['\"]",
        r"secret\s*=\s*['\"][^'\"]+['\"]",
    ]
    for pattern in credential_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            score -= 0.3

    # Check for magic numbers (excluding 0, 1, 2)
    magic_numbers = re.findall(r"[^0-9a-zA-Z_](\d{3,})[^0-9]", code)
    if len(magic_numbers) > 3:
        score -= 0.1

    return max(0.0, score)


def _check_python_syntax(code: str) -> float:
    """Check Python syntax validity."""
    try:
        ast.parse(code)
        return 1.0
    except SyntaxError:
        return 0.0


def _calculate_python_complexity(code: str) -> int:
    """Calculate cyclomatic complexity for Python code."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 100  # Invalid code = high complexity

    complexity = 1  # Base complexity

    for node in ast.walk(tree):
        # Each decision point adds 1 to complexity
        if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
            complexity += 1
        elif isinstance(node, ast.BoolOp):
            # and/or add complexity
            complexity += len(node.values) - 1
        elif isinstance(node, ast.comprehension):
            # List/dict/set comprehensions
            complexity += 1
            if node.ifs:
                complexity += len(node.ifs)

    return complexity


def _estimate_complexity_heuristic(code: str) -> int:
    """Estimate complexity using keyword counting heuristic."""
    keywords = [
        r"\bif\b",
        r"\belse\b",
        r"\belif\b",
        r"\bfor\b",
        r"\bwhile\b",
        r"\btry\b",
        r"\bcatch\b",
        r"\bexcept\b",
        r"\bswitch\b",
        r"\bcase\b",
        r"\?\s*.*\s*:",  # ternary
    ]

    complexity = 1
    for kw in keywords:
        complexity += len(re.findall(kw, code))

    return complexity
