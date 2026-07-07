"""API route modules for the Agentic server.

Submodules:
    :mod:`~agentic_v2.server.routes.health` -- ``GET /api/health`` liveness probe.
    :mod:`~agentic_v2.server.routes.agents` -- ``GET /api/agents`` agent discovery.
    :mod:`~agentic_v2.server.routes.workflows` -- Workflow execution, DAG
        visualization, and capabilities.
    :mod:`~agentic_v2.server.routes.evaluation_routes` -- Evaluation dataset
        listing and input preview.
    :mod:`~agentic_v2.server.routes.runs` -- Run history: list, summary, detail,
        and SSE event streaming for active runs.
    :mod:`~agentic_v2.server.routes.catalog` -- Persona, tool, and observer
        catalogs for the workflow editor pickers.
    :mod:`~agentic_v2.server.routes.settings_routes` -- Provider endpoint and
        model tier settings backed by the UI settings store.
"""

from __future__ import annotations
