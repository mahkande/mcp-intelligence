"""MetricsService: Collects and manages code metrics for chunks and files."""
from typing import Dict, Any, Optional
import time
import ast
from loguru import logger


class CodeMetrics:
    """Data class for storing collected code metrics."""

    def __init__(
        self,
        complexity: int = 0,
        line_count: int = 0,
        token_count: int = 0,
        density: float = 0.0,
        nesting_depth: int = 0,
    ):
        self.complexity = complexity
        self.line_count = line_count
        self.token_count = token_count
        self.density = density
        self.nesting_depth = nesting_depth

    def to_metadata(self) -> Dict[str, Any]:
        """Convert metrics to metadata dictionary for chunk storage."""
        return {
            "complexity": self.complexity,
            "line_count": self.line_count,
            "token_count": self.token_count,
            "density": self.density,
            "nesting_depth": self.nesting_depth,
        }


class MetricsService:
    """Collects code metrics (complexity, line count, token count, etc.) for code chunks."""

    def __init__(self):
        self.metrics = {}
        self.timers = {}

    def start_timer(self, key: str):
        """Start a named timer."""
        self.timers[key] = {"start": time.time()}

    def stop_timer(self, key: str) -> Optional[float]:
        """Stop a named timer and return duration in seconds."""
        if key in self.timers and "start" in self.timers[key]:
            self.timers[key]["end"] = time.time()
            duration = self.timers[key]["end"] - self.timers[key]["start"]
            self.timers[key]["duration"] = duration
            return duration
        return None

    def record(self, key: str, value: Any):
        """Record a metric value."""
        self.metrics[key] = value

    def get_metrics(self) -> Dict[str, Any]:
        """Get all recorded metrics."""
        return self.metrics

    async def get_project_metrics(self, database: Any, project_root: str) -> Any:
        """Fetch all chunks from database and aggregate into ProjectMetrics.
        
        Args:
            database: VectorDatabase instance
            project_root: Project root path string
            
        Returns:
            ProjectMetrics object populated with FileMetrics and ChunkMetrics.
        """
        from mcp_code_intelligence.analysis.metrics import ProjectMetrics, FileMetrics, ChunkMetrics
        
        # Fetch all chunks
        chunks = await database.get_all_chunks()
        
        project_metrics = ProjectMetrics(project_root=project_root)
        
        # Group chunks by file path
        files_map = {}
        for chunk in chunks:
            file_path = str(chunk.file_path)
            if file_path not in files_map:
                files_map[file_path] = FileMetrics(file_path=file_path)
            
            # Map chunk metadata to ChunkMetrics
            cm = ChunkMetrics(
                cognitive_complexity=int(getattr(chunk, "cognitive_complexity", 0)),
                cyclomatic_complexity=int(getattr(chunk, "cyclomatic_complexity", getattr(chunk, "complexity_score", 0))),
                max_nesting_depth=int(getattr(chunk, "max_nesting_depth", 0)),
                parameter_count=int(getattr(chunk, "parameter_count", 0)),
                lines_of_code=chunk.end_line - chunk.start_line + 1
            )
            files_map[file_path].chunks.append(cm)
            
        # Compute aggregates for each file and add to project
        for file_path, fm in files_map.items():
            fm.compute_aggregates()
            project_metrics.files[file_path] = fm
            
        project_metrics.compute_aggregates()
        return project_metrics

    def collect(
        self, chunk: Any, source_code: bytes, language: str = "unknown"
    ) -> Optional[CodeMetrics]:
        """Collect all metrics for a code chunk.

        Args:
            chunk: CodeChunk object with start_line, end_line, and content
            source_code: Full source code in bytes
            language: Programming language identifier

        Returns:
            CodeMetrics object or None if metrics collection failed
        """
        try:
            # Decode source code
            try:
                source_str = source_code.decode("utf-8")
            except UnicodeDecodeError:
                source_str = source_code.decode("utf-8", errors="ignore")

            # Extract chunk content
            chunk_content = self._extract_chunk_content(source_str, chunk)

            # Calculate metrics
            complexity = self._calculate_complexity(chunk_content, language)
            line_count = self._get_line_count(chunk_content)
            token_count = self._get_token_count(chunk_content)
            nesting_depth = self._calculate_nesting_depth(chunk_content, language)
            density = self._calculate_density(
                complexity, line_count, token_count, nesting_depth
            )

            return CodeMetrics(
                complexity=complexity,
                line_count=line_count,
                token_count=token_count,
                density=density,
                nesting_depth=nesting_depth,
            )

        except Exception as e:
            logger.debug(f"Failed to collect metrics for chunk: {e}")
            return None

    def _extract_chunk_content(self, source_str: str, chunk: Any) -> str:
        """Extract chunk content from source code.

        Args:
            source_str: Full source code as string
            chunk: CodeChunk with start_line and end_line

        Returns:
            Chunk content as string
        """
        if hasattr(chunk, "content") and chunk.content:
            return chunk.content

        # Extract from source lines if available
        if hasattr(chunk, "start_line") and hasattr(chunk, "end_line"):
            try:
                lines = source_str.split("\n")
                start = max(0, chunk.start_line - 1)
                end = min(len(lines), chunk.end_line)
                return "\n".join(lines[start:end])
            except Exception:
                pass

        return ""

    def _calculate_complexity(self, chunk_content: str, language: str) -> int:
        """Calculate cyclomatic complexity of code chunk.

        For Python: count if/elif/else/for/while/except/and/or keywords
        For other languages: basic keyword counting
        """
        if not chunk_content:
            return 0

        complexity = 1  # Base complexity

        if language == "python":
            # Count control flow keywords
            keywords = [
                "if ",
                "elif ",
                "else:",
                "for ",
                "while ",
                "except ",
                " and ",
                " or ",
                "try:",
                "finally:",
            ]
            for keyword in keywords:
                complexity += chunk_content.count(keyword)

            # Count lambda expressions
            complexity += chunk_content.count("lambda")

            # Penalize nested structures
            indent_levels = set()
            for line in chunk_content.split("\n"):
                if line.strip():
                    indent = len(line) - len(line.lstrip())
                    indent_levels.add(indent)
            complexity += max(0, len(indent_levels) - 1)

        else:
            # Generic language handling
            keywords = [
                "if",
                "else",
                "switch",
                "case",
                "for",
                "while",
                "do",
                "catch",
                "try",
                "finally",
                "&&",
                "||",
            ]
            for keyword in keywords:
                complexity += chunk_content.count(keyword)

        return max(1, complexity)

    def _get_line_count(self, chunk_content: str) -> int:
        """Get number of lines in chunk (excluding empty lines and comments)."""
        if not chunk_content:
            return 0

        lines = chunk_content.split("\n")
        non_empty_lines = [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]
        return len(non_empty_lines)

    def _get_token_count(self, chunk_content: str) -> int:
        """Approximate token count by splitting on whitespace and operators."""
        if not chunk_content:
            return 0

        # Simple tokenization: split on whitespace and operators
        import re

        # Split on whitespace and common operators
        tokens = re.split(r"[\s\(\)\[\]{};,:<>=+\-*/!&|?.]", chunk_content)
        return len([t for t in tokens if t])

    def _calculate_nesting_depth(self, chunk_content: str, language: str) -> int:
        """Calculate maximum nesting depth in code."""
        if not chunk_content:
            return 0

        if language == "python":
            # Count indentation levels
            max_depth = 0
            for line in chunk_content.split("\n"):
                if line.strip():
                    indent = len(line) - len(line.lstrip())
                    depth = indent // 4  # Assume 4-space indentation
                    max_depth = max(max_depth, depth)
            return max_depth
        else:
            # Count curly brace nesting for C-like languages
            max_depth = 0
            current_depth = 0
            for char in chunk_content:
                if char == "{":
                    current_depth += 1
                    max_depth = max(max_depth, current_depth)
                elif char == "}":
                    current_depth = max(0, current_depth - 1)
            return max_depth

    def _calculate_density(
        self,
        complexity: int,
        line_count: int,
        token_count: int,
        nesting_depth: int,
    ) -> float:
        """Calculate code density metric (complexity per unit of code).

        Density = (complexity + nesting_depth) / (line_count + token_count + 1)
        Higher density indicates more complex code relative to its size.
        """
        if line_count == 0 or token_count == 0:
            return 0.0

        denominator = line_count + token_count
        numerator = complexity + nesting_depth
        density = numerator / denominator if denominator > 0 else 0.0
        return round(density, 3)
