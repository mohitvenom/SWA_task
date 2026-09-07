"""State machine implementation for agent sessions."""

from forgeai.agents.errors import AgentStateTransitionError
from forgeai.agents.models import AgentState


class StateMachine:
    """Manages valid state transitions for an agent session."""

    VALID_TRANSITIONS: dict[AgentState, set[AgentState]] = {
        AgentState.PENDING: {AgentState.RUNNING, AgentState.FAILED},
        AgentState.RUNNING: {AgentState.THINKING, AgentState.FAILED},
        AgentState.THINKING: {
            AgentState.TOOL_EXECUTING,
            AgentState.COMPLETED,
            AgentState.FAILED,
        },
        AgentState.TOOL_EXECUTING: {AgentState.THINKING, AgentState.FAILED},
        AgentState.COMPLETED: set(),
        AgentState.FAILED: set(),
        AgentState.CANCELLED: set(),
    }

    @classmethod
    def validate_transition(
        cls, current_state: AgentState, next_state: AgentState
    ) -> None:
        """
        Validate if transitioning from current_state to next_state is legal.

        Args:
            current_state: The current state of the session.
            next_state: The desired next state.

        Raises:
            AgentStateTransitionError: If the transition is not allowed.
        """
        allowed = cls.VALID_TRANSITIONS.get(current_state, set())
        if next_state not in allowed:
            raise AgentStateTransitionError(
                f"Invalid transition from {current_state.value} to {next_state.value}."
            )
