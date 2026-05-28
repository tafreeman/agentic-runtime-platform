"""JSON-file-backed database for storing prompts, rubrics, and evaluations."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "db")
PROMPTS_FILE = os.path.join(DB_DIR, "prompts.json")
RUBRICS_FILE = os.path.join(DB_DIR, "rubrics.json")
EVALUATIONS_FILE = os.path.join(DB_DIR, "evaluations.json")


class PromptDatabase:
    """Persistent store for prompts, evaluation rubrics, and run evaluations."""

    def __init__(self):
        """Initialise the database, creating JSON backing files if needed."""
        self._ensure_db_exists()
        self.prompts = self._load_json(PROMPTS_FILE)
        self.rubrics = self._load_json(RUBRICS_FILE)
        self.evaluations = self._load_json(EVALUATIONS_FILE)

    def _ensure_db_exists(self):
        os.makedirs(DB_DIR, exist_ok=True)
        for file_path in [PROMPTS_FILE, RUBRICS_FILE, EVALUATIONS_FILE]:
            if not os.path.exists(file_path):
                with open(file_path, "w") as f:
                    json.dump([], f)

    def _load_json(self, file_path: str) -> list[dict]:
        try:
            with open(file_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_json(self, file_path: str, data: list[dict]):
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2)

    def save(self):
        """Persist all in-memory collections to their JSON backing files."""
        self._save_json(RUBRICS_FILE, self.rubrics)
        self._save_json(EVALUATIONS_FILE, self.evaluations)

    # --- Prompts ---

    def add_prompt(self, name: str, content: str, metadata: dict | None = None) -> str:
        """Add a new prompt or a new version of an existing prompt."""
        prompt_id = str(uuid.uuid4())

        # Check if prompt with same name exists to group versions?
        # For simplicity, let's treat name as unique identifier for a "Prompt Family"
        # But here we might just store flat list of versions or structured.
        # Let's go with a flat list of prompt versions for now, linked by name or a group_id if needed.
        # Actually, the schema I designed earlier had prompts containing versions.

        existing_prompt = next((p for p in self.prompts if p["name"] == name), None)

        if existing_prompt:
            version_num = len(existing_prompt["versions"]) + 1
            new_version = {
                "version": str(version_num) + ".0",
                "content": content,
                "metadata": metadata or {},
                "created_at": datetime.now().isoformat(),
            }
            existing_prompt["versions"].append(new_version)
            prompt_id = existing_prompt["id"]  # Return the main prompt ID
        else:
            prompt_id = str(uuid.uuid4())
            new_prompt = {
                "id": prompt_id,
                "name": name,
                "versions": [
                    {
                        "version": "1.0",
                        "content": content,
                        "metadata": metadata or {},
                        "created_at": datetime.now().isoformat(),
                    }
                ],
            }
            self.prompts.append(new_prompt)

        self.save()
        return prompt_id

    def get_prompt(self, prompt_id: str) -> dict | None:
        """Return the prompt record matching *prompt_id*, or ``None``."""
        return next((p for p in self.prompts if p["id"] == prompt_id), None)

    def get_prompt_by_name(self, name: str) -> dict | None:
        """Return the prompt record matching *name*, or ``None``."""
        return next((p for p in self.prompts if p["name"] == name), None)

    # --- Rubrics ---

    def add_rubric(self, rubric_data: dict) -> str:
        """Persist *rubric_data* and return its ID (auto-generated if absent)."""
        if "id" not in rubric_data:
            rubric_data["id"] = str(uuid.uuid4())
        self.rubrics.append(rubric_data)
        self.save()
        return rubric_data["id"]

    def get_rubric(self, rubric_id: str) -> dict | None:
        """Return the rubric matching *rubric_id*, or ``None``."""
        return next((r for r in self.rubrics if r["id"] == rubric_id), None)

    # --- Evaluations ---

    def add_evaluation(self, evaluation_data: dict) -> str:
        """Persist *evaluation_data* and return its ID (auto-generated if absent)."""
        if "id" not in evaluation_data:
            evaluation_data["id"] = str(uuid.uuid4())
        if "timestamp" not in evaluation_data:
            evaluation_data["timestamp"] = datetime.now().isoformat()

        self.evaluations.append(evaluation_data)
        self.save()
        return evaluation_data["id"]

    def get_evaluations_for_prompt(self, prompt_id: str) -> list[dict]:
        """Return all evaluation records associated with *prompt_id*."""
        return [e for e in self.evaluations if e.get("prompt_id") == prompt_id]

    def get_evaluations_by_model(self, model_name: str) -> list[dict]:
        """Return all evaluation records produced by *model_name*."""
        return [e for e in self.evaluations if e.get("model") == model_name]


if __name__ == "__main__":
    # Simple test
    db = PromptDatabase()
    logger.info(
        f"Loaded {len(db.prompts)} prompts, {len(db.rubrics)} rubrics, {len(db.evaluations)} evaluations."
    )
