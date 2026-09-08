"""Memory Context Builder for ForgeAI."""

import logging
from typing import Any

from forgeai.memory.models import MemoryContext
from forgeai.memory.store import MemoryStore

logger = logging.getLogger(__name__)


from forgeai.config.settings import settings

class MemoryContextBuilder:
    """Builds a structured memory context safely."""

    def __init__(self, memory_store: MemoryStore | None):
        self.memory_store = memory_store

    def build_context(self, repository_identifier: str, task_id: str | None = None) -> MemoryContext | None:
        """Query memory store and build context for the LLM."""
        if not settings.memory_enabled or not self.memory_store:
            return None

        try:
            # Graceful degradation here as well if store operations fail.
            # Store handles its own internal exceptions and returns [] but 
            # we wrap in try-except to guarantee isolation.
            history = self.memory_store.get_history(repository_identifier, limit=5)
            entries = self.memory_store.get_entries(repository_identifier, limit=20)
            
            # Optionally fetch events if we want to include them
            # For simplicity, we just include the high-level execution records and entries
            # If a task_id is specified, we could filter specifically.
            
            context = MemoryContext()
            
            if history:
                context.historical_executions = history
                
            for entry in entries:
                if entry.category.value == "FAILURE":
                    context.relevant_failures.append(entry)
                elif entry.category.value == "ENGINEERING_FACT":
                    context.engineering_facts.append(entry)
                
            return context
        except Exception as e:
            logger.warning(f"Graceful degradation: MemoryContextBuilder failed: {e}")
            return None
