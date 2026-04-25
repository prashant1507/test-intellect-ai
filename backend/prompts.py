from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _load() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "resources" / "llm_prompts.py"
    spec = importlib.util.spec_from_file_location("llm_prompts", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("missing resources/llm_prompts.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # noqa: S102
    return mod


M = _load()

AGENT_CANDIDATE_TEST_SUITE_GENERATION_SYSTEM_PROMPT = M.AGENT_CANDIDATE_TEST_SUITE_GENERATION_SYSTEM_PROMPT
AGENT_SCENARIOS_QUALITY_RANKING_SYSTEM_PROMPT = M.AGENT_SCENARIOS_QUALITY_RANKING_SYSTEM_PROMPT
AGENT_SUGGESTED_SCENARIOS_GENERATION_SYSTEM_PROMPT = M.AGENT_SUGGESTED_SCENARIOS_GENERATION_SYSTEM_PROMPT
AGENT_TEST_SUITE_VALIDATION_RUBRIC_SYSTEM_PROMPT = M.AGENT_TEST_SUITE_VALIDATION_RUBRIC_SYSTEM_PROMPT
API_BDD_TO_HTTP_OPERATIONS_PLANNER_SYSTEM_PROMPT = M.API_BDD_TO_HTTP_OPERATIONS_PLANNER_SYSTEM_PROMPT
BDD_TEST_CASES_BATCH_SCORING_SYSTEM_PROMPT = M.BDD_TEST_CASES_BATCH_SCORING_SYSTEM_PROMPT
BDD_TEST_CASE_GENERATION_SYSTEM_PROMPT = M.BDD_TEST_CASE_GENERATION_SYSTEM_PROMPT
BDD_TEST_GENERATION_WITH_ATTACHMENTS_SUPPLEMENT_PROMPT = M.BDD_TEST_GENERATION_WITH_ATTACHMENTS_SUPPLEMENT_PROMPT
PLAYWRIGHT_SINGLE_STEP_FAILURE_REPAIR_SYSTEM_PROMPT = M.PLAYWRIGHT_SINGLE_STEP_FAILURE_REPAIR_SYSTEM_PROMPT
PLAYWRIGHT_VISION_STEP_EVIDENCE_SYSTEM_PROMPT = M.PLAYWRIGHT_VISION_STEP_EVIDENCE_SYSTEM_PROMPT
PLAYWRIGHT_STEPS_VS_DOM_INTRO_SYSTEM_PROMPT = M.PLAYWRIGHT_STEPS_VS_DOM_INTRO_SYSTEM_PROMPT
SKELETON_TEST_CODE_GENERATION_SYSTEM_PROMPT = M.SKELETON_TEST_CODE_GENERATION_SYSTEM_PROMPT
UI_SPIKE_TEST_RUN_SUMMARY_SYSTEM_PROMPT = M.UI_SPIKE_TEST_RUN_SUMMARY_SYSTEM_PROMPT

playwright_reconcile_step_count_mismatch_prompt = M.playwright_reconcile_step_count_mismatch_prompt
playwright_map_bdd_to_locator_steps_prompt = M.playwright_map_bdd_to_locator_steps_prompt
playwright_refine_locators_against_html_rule = M.playwright_refine_locators_against_html_rule
playwright_repair_zero_locator_matches_prompt = M.playwright_repair_zero_locator_matches_prompt
