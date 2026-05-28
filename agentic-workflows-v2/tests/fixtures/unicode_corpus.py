"""Malicious and normal Unicode samples for testing UnicodeSanitizer."""

# Strings with dangerous invisible characters
DANGEROUS_UNICODE: list[tuple[str, int]] = [
    # (text_with_hidden_chars, expected_removals_minimum)
    ("hello\u200bworld", 1),  # zero-width space
    ("test\u200c\u200dstring", 2),  # ZWNJ + ZWJ
    ("normal\ufefftext", 1),  # BOM
    ("\u202ahidden\u202c", 2),  # LRE + PDF directional
    ("a\u2066b\u2069c", 2),  # LRI + PDI directional isolates
    ("invisible\u2060joiner", 1),  # word joiner
    ("\u2062math\u2063separation", 2),  # invisible times + separator
]

# Strings that should pass through unchanged (or near-unchanged)
SAFE_UNICODE: list[str] = [
    "Hello, world!",
    "日本語テスト",  # Japanese
    "Ñoño español",  # Spanish
    "Ελληνικά",  # Greek
    "数学公式 x² + y² = z²",  # Math
    "emoji: 🎉🚀💻",
]

# NFKC normalization edge cases
NORMALIZATION_CASES: list[tuple[str, str]] = [
    ("\uff21\uff22\uff23", "ABC"),  # Fullwidth → ASCII
    ("ﬁ", "fi"),  # Ligature → separate chars
    ("①", "1"),  # Circled digit → digit
]
