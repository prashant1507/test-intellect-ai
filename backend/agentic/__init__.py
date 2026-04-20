from __future__ import annotations

import asyncio
from typing import Any

from .graph import build_graph, run_pipeline


async def run_agentic_pipeline_async(**kwargs: Any) -> dict:
    return await asyncio.to_thread(lambda: run_pipeline(**kwargs))


__all__ = ["build_graph", "run_pipeline", "run_agentic_pipeline_async"]
