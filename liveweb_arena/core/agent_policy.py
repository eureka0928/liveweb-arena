"""JSON-only agent policy for browser action parsing and repair"""

import json
import re
from typing import List, Optional, Tuple

from .models import BrowserAction, BrowserObservation, CompositeTask, TrajectoryStep


# Valid action types
VALID_ACTION_TYPES = {
    "goto", "click", "type", "press", "scroll", "wait", "stop",
    "click_role", "type_role", "view_more"
}

# System prompt template - built dynamically with plugin hints
SYSTEM_PROMPT_BASE = """You are a web automation agent that interacts with real websites to complete tasks.

You have access to a browser and can navigate to any website to gather information.

{available_tools}

{task_description}

## Action Protocol

First, wrap your reasoning in <think>...</think> tags, then respond with a JSON object:

```
<think>
Your reasoning about what to do next...
</think>
{{
  "action": {{
    "type": "<action_type>",
    "params": {{...}}
  }}
}}
```

## Available Actions

1. **goto** - Navigate to a URL
   ```json
   {{"action": {{"type": "goto", "params": {{"url": "https://example.com"}}}}}}
   ```

2. **click** - Click an element by CSS selector
   ```json
   {{"action": {{"type": "click", "params": {{"selector": "button.submit"}}}}}}
   ```

3. **type** - Type text into an input field
   ```json
   {{"action": {{"type": "type", "params": {{"selector": "input#search", "text": "query", "press_enter": true}}}}}}
   ```

4. **press** - Press a keyboard key
   ```json
   {{"action": {{"type": "press", "params": {{"key": "Enter"}}}}}}
   ```

5. **scroll** - Scroll the page (for loading dynamic content)
   ```json
   {{"action": {{"type": "scroll", "params": {{"direction": "down", "amount": 300}}}}}}
   ```

6. **view_more** - View more truncated content (when page content is cut off)
   ```json
   {{"action": {{"type": "view_more", "params": {{"direction": "down"}}}}}}
   ```
   Use this when you see "... (content below, use view_more direction=down to see)" to view hidden content.

7. **wait** - Wait for a duration
   ```json
   {{"action": {{"type": "wait", "params": {{"seconds": 2}}}}}}
   ```

8. **click_role** - Click by accessibility role (more stable)
   ```json
   {{"action": {{"type": "click_role", "params": {{"role": "button", "name": "Search"}}}}}}
   ```

9. **type_role** - Type into element by accessibility role
   ```json
   {{"action": {{"type": "type_role", "params": {{"role": "textbox", "name": "Search", "text": "query", "press_enter": true}}}}}}
   ```

10. **stop** - Complete the task and submit answers
   ```json
   {{
     "action": {{
       "type": "stop",
       "params": {{
         "format": "json",
         "final": {{
           "answers": {{"answer1": "value1", "answer2": "value2"}}
         }}
       }}
     }}
   }}
   ```

## Tips

- First analyze the task and decide which website to visit
- Use the "goto" action to navigate to the appropriate URL
- Homepage/list data may be inaccurate (no +/- signs, delayed). Always visit detail pages for precise values
- When done with all tasks, use the "stop" action with your answers

## IMPORTANT

- Output ONLY a single JSON object
- Do NOT include markdown code blocks
- Do NOT include any text before or after the JSON
"""

# Step prompt template
STEP_PROMPT_TEMPLATE = """## Current Page State

URL: {url}
Title: {title}

### Accessibility Tree
```
{accessibility_tree}
```

### Recent Actions
{recent_actions}

**Step {current_step}/{max_steps}** ({remaining_steps} steps remaining){last_step_warning}

What is your next action? Remember: output ONLY a JSON object, no markdown or extra text.
"""

LAST_STEP_WARNING = """

**THIS IS YOUR LAST STEP!** You MUST use the "stop" action now and provide your best answers based on the information you have gathered. Do not attempt any other action."""


class AgentPolicy:
    """
    JSON-only policy for browser action generation and parsing.

    Responsibilities:
    - Build system and step prompts
    - Parse LLM response to BrowserAction
    - Repair malformed JSON (two-stage)
    """

    def __init__(self, max_recent_steps: int = 5):
        """
        Initialize policy.

        Args:
            max_recent_steps: Number of recent steps to include in prompt
        """
        self._max_recent_steps = max_recent_steps
        self._json_repair_count = 0

    @property
    def json_repair_count(self) -> int:
        """Get count of JSON repairs performed"""
        return self._json_repair_count

    def reset_repair_count(self):
        """Reset JSON repair counter"""
        self._json_repair_count = 0

    def build_system_prompt(self, task: CompositeTask) -> str:
        """Build system prompt with task intent and plugin hints"""
        # Build available tools section from plugin hints
        if task.plugin_hints:
            tools_section = "## Available Information Sources\n\n"
            for plugin_name, usage_hint in task.plugin_hints.items():
                tools_section += usage_hint + "\n\n"
        else:
            tools_section = ""

        return SYSTEM_PROMPT_BASE.format(
            available_tools=tools_section,
            task_description=task.combined_intent,
        )

    def build_step_prompt(
        self,
        obs: BrowserObservation,
        trajectory: List[TrajectoryStep],
        current_step: int = 1,
        max_steps: int = 30,
    ) -> str:
        """Build step prompt with current observation and recent history"""
        # Format recent steps with raw response (preserves model's thinking/reasoning)
        recent = trajectory[-self._max_recent_steps:] if trajectory else []
        if recent:
            action_lines = []
            for step in recent:
                # Include raw response so model sees its own output
                if step.raw_response:
                    # Truncate if too long
                    response_preview = step.raw_response[:500] if len(step.raw_response) > 500 else step.raw_response
                    action_lines.append(f"Step {step.step_num} response: {response_preview}")
                action_lines.append(f"Step {step.step_num} result: {step.action_result}")
            recent_actions = "\n".join(action_lines) if action_lines else "(no actions yet)"
        else:
            recent_actions = "(no actions yet)"

        remaining_steps = max_steps - current_step
        last_step_warning = LAST_STEP_WARNING if remaining_steps == 0 else ""

        return STEP_PROMPT_TEMPLATE.format(
            url=obs.url,
            title=obs.title,
            accessibility_tree=obs.accessibility_tree,
            recent_actions=recent_actions,
            current_step=current_step,
            max_steps=max_steps,
            remaining_steps=remaining_steps,
            last_step_warning=last_step_warning,
        )

    def parse_response(self, raw: str) -> Optional[BrowserAction]:
        """
        Parse LLM response to extract action.

        Returns:
            BrowserAction or None on failure
        """
        # Try direct parse first
        parsed = self._try_parse_json(raw)

        # If direct parse fails, try heuristic extraction
        if parsed is None:
            self._json_repair_count += 1
            parsed = self._extract_json_object(raw)

        if parsed is None:
            return None

        # Extract action
        action_data = parsed.get("action", {})

        if not action_data:
            return None

        action_type = action_data.get("type", "")
        params = action_data.get("params", {})

        # Validate action type
        if action_type not in VALID_ACTION_TYPES:
            # Try to recover - maybe they used a similar name
            action_type_lower = action_type.lower()
            for valid_type in VALID_ACTION_TYPES:
                if valid_type in action_type_lower or action_type_lower in valid_type:
                    action_type = valid_type
                    break
            else:
                return None

        return BrowserAction(action_type=action_type, params=params)

    def _try_parse_json(self, text: str) -> Optional[dict]:
        """Try to parse text as JSON directly"""
        try:
            result = json.loads(text.strip())
            # Ensure we got a dict, not just any JSON value (int, string, list, etc.)
            if isinstance(result, dict):
                return result
            return None
        except json.JSONDecodeError:
            return None

    def _find_json_candidates(self, text: str) -> Tuple[List[str], Optional[str]]:
        """
        Find all potential JSON objects in text by matching braces.

        Returns:
            Tuple of (complete_candidates, truncated_json)
            - complete_candidates: List of complete {...} strings
            - truncated_json: Partial JSON if text ends with unclosed braces, else None
        """
        candidates = []
        depth = 0
        start = None

        for i, char in enumerate(text):
            if char == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    candidates.append(text[start:i + 1])
                    start = None

        # Check for truncated JSON (unclosed braces at end)
        truncated = None
        if start is not None and depth > 0:
            truncated = text[start:] + "}" * depth

        return candidates, truncated

    def _try_parse_as_dict(self, text: str) -> Optional[dict]:
        """Try to parse text as JSON dict, return None if not a dict."""
        try:
            result = json.loads(text)
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None

    def _extract_json_object(self, text: str) -> Optional[dict]:
        """
        Extract JSON object from text with multiple fallback strategies.

        Strategies (in order):
        1. Extract from markdown code block (```json ... ```)
        2. Find complete JSON objects by brace matching
        3. Repair truncated JSON by closing missing braces
        """
        # Strategy 1: Markdown code block
        code_block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if code_block_match:
            result = self._try_parse_as_dict(code_block_match.group(1))
            if result:
                return result

        # Strategy 2 & 3: Find candidates and try truncated repair
        candidates, truncated = self._find_json_candidates(text)

        # Try truncated repair first (more likely to be the intended JSON)
        if truncated:
            result = self._try_parse_as_dict(truncated)
            if result:
                return result

        # Try complete candidates from largest to smallest
        for candidate in sorted(candidates, key=len, reverse=True):
            result = self._try_parse_as_dict(candidate)
            if result:
                return result

        return None
