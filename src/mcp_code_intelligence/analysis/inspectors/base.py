"""Base class for project health inspectors."""

from abc import ABC, abstractmethod
from typing import Any, List
from mcp_code_intelligence.core.models import CodeChunk

class BaseInspector(ABC):
    """Abstract base class for all code inspectors."""

    @abstractmethod
    async def inspect(self, chunks: List[CodeChunk]) -> List[dict]:
        """Inspect the given chunks and return a list of discovered issues.
        
        Args:
            chunks: List of code chunks to analyze.
            
        Returns:
            List of issue dictionaries. Each issue should have a unique ID.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the inspector (e.g., 'DuplicateDetector')."""
        pass
