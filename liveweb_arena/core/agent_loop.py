"""Agent loop for browser-based task execution"""

from typing import Any, Callable, List, Optional, Tuple

from .browser import BrowserSession
from .models import BrowserAction, CompositeTask, TrajectoryStep
from .agent_policy import AgentPolicy
from ..utils.llm_client import LLMClient
from ..utils.logger import log


# Type for navigation callback: async (url: str) -> None
NavigationCallback = Callable[[str], Any]


class AgentLoop:
    """
    Main agent loop that drives browser interaction via LLM.

    The loop maintains trajectory state internally for partial recovery on timeout.
    """

    def __init__(
        self,
        session: BrowserSession,
        llm_client: LLMClient,
        policy: AgentPolicy,
        max_steps: int = 30,
        on_navigation: Optional[NavigationCallback] = None,
    ):
        self._session = session
        self._llm_client = llm_client
        self._policy = policy
        self._max_steps = max_steps
        self._on_navigation = on_navigation

        # Internal state for partial recovery
        self._trajectory: List[TrajectoryStep] = []
        self._total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._final_answer = None

    def get_trajectory(self) -> List[TrajectoryStep]:
        """Get current trajectory (for partial recovery on timeout)"""
        return self._trajectory.copy()

    def get_usage(self) -> Optional[dict]:
        """Get current usage stats"""
        return self._total_usage.copy() if any(self._total_usage.values()) else None

    def get_final_answer(self) -> Any:
        """Get final answer if available"""
        return self._final_answer

    async def run(
        self,
        task: CompositeTask,
        model: str,
        temperature: float = 0.7,
        seed: Optional[int] = None,
    ) -> Tuple[List[TrajectoryStep], Any, Optional[dict]]:
        """
        Run the agent loop until completion or max_steps.

        Args:
            task: Composite task to complete
            model: LLM model name
            temperature: LLM temperature
            seed: LLM seed for reproducibility

        Returns:
            Tuple of (trajectory, final_answer, usage)
            - trajectory: List of TrajectoryStep
            - final_answer: The final answer dict from stop action, or None
            - usage: Aggregated LLM usage dict
        """
        # Reset internal state
        self._trajectory = []
        self._total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._final_answer = None
        self._max_steps_reached = False
        self._policy.reset_repair_count()

        system_prompt = self._policy.build_system_prompt(task)
        log("Agent", f"Starting loop, max_steps={self._max_steps}")

        obs = await self._session.goto("about:blank")
        consecutive_errors = 0

        for step_num in range(self._max_steps):
            log("Agent", f"Step {step_num + 1}/{self._max_steps}, url={obs.url[:50]}")

            # Pre-save observation so it's not lost if LLM call times out
            current_obs = obs
            user_prompt = self._policy.build_step_prompt(current_obs, self._trajectory)

            try:
                raw_response, usage = await self._llm_client.chat(
                    system=system_prompt,
                    user=user_prompt,
                    model=model,
                    temperature=temperature,
                    seed=seed,
                )
                if usage:
                    for key in self._total_usage:
                        self._total_usage[key] += usage.get(key, 0)
                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                log("Agent", f"LLM error ({consecutive_errors}/3): {type(e).__name__}", force=True)

                self._trajectory.append(TrajectoryStep(
                    step_num=step_num,
                    observation=current_obs,
                    thought=f"LLM error: {e}",
                    action=BrowserAction(action_type="wait", params={"seconds": 2}),
                    action_result="LLM call failed",
                ))

                if consecutive_errors >= 3:
                    break

                obs = await self._session.execute_action(
                    BrowserAction(action_type="wait", params={"seconds": 2})
                )
                continue

            thought, action = self._policy.parse_response(raw_response)

            if action is None:
                action = BrowserAction(action_type="wait", params={"seconds": 0.5})
                action_result = "Parse failed"

            if action.action_type == "stop":
                final_params = action.params.get("final", {})
                self._final_answer = final_params if final_params else action.params
                log("Agent", f"Completed: {self._final_answer}")

                self._trajectory.append(TrajectoryStep(
                    step_num=step_num,
                    observation=current_obs,
                    thought=thought,
                    action=action,
                    action_result="Task completed",
                ))
                break
            else:
                log("Agent", f"Action: {action.action_type}")
                try:
                    old_url = obs.url if obs else None
                    obs = await self._session.execute_action(action)
                    action_result = "Success"

                    # Fire navigation callback if URL changed
                    if self._on_navigation and obs.url != old_url:
                        try:
                            await self._on_navigation(obs.url)
                        except Exception as e:
                            log("Agent", f"Navigation callback error: {e}")
                except Exception as e:
                    action_result = f"Failed: {e}"

            self._trajectory.append(TrajectoryStep(
                step_num=step_num,
                observation=current_obs,
                thought=thought,
                action=action,
                action_result=action_result,
            ))
        else:
            # Loop completed without break - max_steps reached
            if self._final_answer is None:
                self._max_steps_reached = True
                log("Agent", f"Max steps ({self._max_steps}) reached without completion", force=True)

        log("Agent", f"Finished with {len(self._trajectory)} steps")
        return self._trajectory, self._final_answer, self.get_usage()

    def is_max_steps_reached(self) -> bool:
        """Check if max steps was reached without completion"""
        return self._max_steps_reached
