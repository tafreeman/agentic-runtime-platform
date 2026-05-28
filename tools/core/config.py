"""Configuration primitives for the tools ecosystem.

Provides dataclass-based configuration objects for LLM model selection,
filesystem paths, and temperature settings.  Values are loaded from
environment variables at import time, falling back to sensible defaults.

Environment variables:
    GEN_MODEL: Override the generator model (default ``gpt-4o-mini``).
    REV_MODEL: Override the reviewer model (default ``gpt-4o-mini``).
    REF_MODEL: Override the refiner model (default ``gpt-4o-mini``).

Example::

    from tools.core.config import default_config
    print(default_config.models.generator_model)
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class ModelConfig:
    """LLM model identifiers and sampling temperatures for each pipeline role.

    Attributes:
        generator_model: Model used for initial code / text generation.
        reviewer_model: Model used for reviewing generated output.
        refiner_model: Model used for refining output after review.
        generator_temp: Sampling temperature for the generator (0.0--2.0).
        reviewer_temp: Sampling temperature for the reviewer.
        refiner_temp: Sampling temperature for the refiner.
    """

    generator_model: str = "gpt-4o-mini"
    reviewer_model: str = "gpt-4o-mini"
    refiner_model: str = "gpt-4o-mini"
    generator_temp: float = 0.7
    reviewer_temp: float = 0.0
    refiner_temp: float = 0.5


@dataclass
class PathConfig:
    """Filesystem paths for templates, instructions, and rubrics.

    Attributes:
        templates_dir: Directory containing prompt template files.
        instructions_dir: Directory containing instruction files.
        rubric_path: Path to the quality-standards rubric JSON.
    """

    templates_dir: str = "prompts/"
    instructions_dir: str = "instructions/"
    rubric_path: str = "tools/rubrics/quality_standards.json"


class Config:
    """Centralized configuration aggregating model and path settings.

    Reads ``GEN_MODEL``, ``REV_MODEL``, and ``REF_MODEL`` from the
    environment at construction time, falling back to ``gpt-4o-mini``.

    Attributes:
        models: An instance of :class:`ModelConfig`.
        paths: An instance of :class:`PathConfig`.
    """

    def __init__(self):
        self.models = ModelConfig(
            generator_model=os.getenv("GEN_MODEL", "gpt-4o-mini"),
            reviewer_model=os.getenv("REV_MODEL", "gpt-4o-mini"),
            refiner_model=os.getenv("REF_MODEL", "gpt-4o-mini"),
        )
        self.paths = PathConfig()


# Global config instance
default_config = Config()
