"""System prompt strings for investigation stages."""

from app.llm.prompts.planner import PLANNER_SYSTEM
from app.llm.prompts.synthesizer import SYNTHESIZER_SYSTEM
from app.llm.prompts.tools import TOOL_LOOP_SYSTEM

__all__ = ["PLANNER_SYSTEM", "SYNTHESIZER_SYSTEM", "TOOL_LOOP_SYSTEM"]
