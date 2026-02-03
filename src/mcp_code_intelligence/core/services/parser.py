
"""ParserService: AST ve sembol çıkarma mantığı (indexer.py'den taşındı)."""

import ast
from typing import Any, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class StructuralContext:
    """Represents the structural context of a code node."""
    parent_class: Optional[str] = None
    parent_method: Optional[str] = None
    nesting_level: int = 0
    breadcrumb: str = ""  # "Module > Class: User > Method: save"

    def to_string(self) -> str:
        """Convert to readable context string."""
        if self.breadcrumb:
            return self.breadcrumb

        parts = []
        if self.parent_class:
            parts.append(f"Class: {self.parent_class}")
        if self.parent_method:
            parts.append(f"Method: {self.parent_method}")

        return " > ".join(parts) if parts else "Module Level"


class StructuralContextVisitor(ast.NodeVisitor):
    """AST visitor that tracks structural context while parsing."""

    def __init__(self):
        self.symbols = []
        self.context_stack: list[StructuralContext] = [StructuralContext()]

    @property
    def current_context(self) -> StructuralContext:
        """Get current structural context."""
        return self.context_stack[-1]

    def _push_context(self, context_update: dict[str, Any]) -> None:
        """Push new context onto stack."""
        parent = self.current_context
        new_context = StructuralContext(
            parent_class=context_update.get('parent_class', parent.parent_class),
            parent_method=context_update.get('parent_method', parent.parent_method),
            nesting_level=parent.nesting_level + 1,
        )
        # Build breadcrumb
        breadcrumb_parts = []
        if new_context.parent_class:
            breadcrumb_parts.append(f"Class: {new_context.parent_class}")
        if new_context.parent_method:
            breadcrumb_parts.append(f"Method: {new_context.parent_method}")
        new_context.breadcrumb = " > ".join(breadcrumb_parts) if breadcrumb_parts else "Module Level"

        self.context_stack.append(new_context)

    def _pop_context(self) -> None:
        """Pop context from stack."""
        if len(self.context_stack) > 1:
            self.context_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definition."""
        # Content extraction: fallback to None, will be filled by ParserService
        self.symbols.append({
            "type": "class",
            "name": node.name,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno or node.lineno,
            "docstring": ast.get_docstring(node),
            "parent_context": self.current_context.to_string(),
            "nesting_level": self.current_context.nesting_level,
            "content": None,
        })
        # Push context for nested elements
        self._push_context({'parent_class': node.name})
        self.generic_visit(node)
        self._pop_context()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definition."""
        parent_context = self.current_context
        self.symbols.append({
            "type": "function",
            "name": node.name,
            "lineno": node.lineno,
            "end_lineno": node.end_lineno or node.lineno,
            "docstring": ast.get_docstring(node),
            "parent_context": parent_context.to_string(),
            "parent_class": parent_context.parent_class,
            "parent_method": parent_context.parent_method,
            "nesting_level": parent_context.nesting_level,
            "parameters": [arg.arg for arg in node.args.args],
            "decorators": [ast.unparse(dec) for dec in node.decorator_list],
            "return_annotation": ast.unparse(node.returns) if node.returns else None,
            "content": None,
        })
        # Push context for nested functions
        self._push_context({
            'parent_class': parent_context.parent_class,
            'parent_method': node.name,
        })
        self.generic_visit(node)
        self._pop_context()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definition (treat like regular function)."""
        # Reuse FunctionDef visitor logic
        self.visit_FunctionDef(node)  # type: ignore


class ParserService:
    def parse_file(self, file_path: str) -> list[dict[str, Any]]:
        """Parse file and extract symbols with structural context."""
        logger.info(f"[ParserService] parse_file giriş: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()
            chunks = self._parse_source_code(source)
            logger.info(f"[ParserService] parse_file çıkış: {file_path} -> {len(chunks)} chunk bulundu")
            return chunks
        except Exception as e:
            logger.exception(f"Failed to parse file {file_path}")
            return []

    def _parse_source_code(self, source: str) -> list[dict[str, Any]]:
        """Parse source code and extract symbols with context and content."""
        try:
            tree = ast.parse(source)
            visitor = StructuralContextVisitor()
            visitor.visit(tree)
            # Content extraction for each symbol
            source_lines = source.splitlines()
            for sym in visitor.symbols:
                node_lno = sym.get("lineno")
                node_end = sym.get("end_lineno")
                if node_lno and node_end:
                    # Try ast.get_source_segment (Python 3.8+)
                    try:
                        node = None
                        # Find node by lineno in AST (best effort)
                        # Not perfect, but fallback to slicing
                        # (We don't have direct node ref here)
                        segment = None
                        if hasattr(ast, "get_source_segment"):
                            # Try to get node from AST by lineno
                            # Not available here, so fallback
                            segment = ast.get_source_segment(source, None)
                        if not segment or segment.strip() == "":
                            # Fallback: slice lines
                            segment = "\n".join(source_lines[node_lno-1:node_end])
                        sym["content"] = segment
                    except Exception as e:
                        logger.debug(f"Content extraction failed for {sym.get('name')}: {e}")
                        sym["content"] = ""
                else:
                    sym["content"] = ""
            return visitor.symbols
        except SyntaxError as e:
            logger.error(f"AST parse error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected parse error: {e}")
            return []

    def extract_context_for_line_range(
        self, file_path: str, start_line: int, end_line: int
    ) -> Optional[StructuralContext]:
        """Extract structural context for a given line range in a file.

        Args:
            file_path: Path to the file
            start_line: Starting line number
            end_line: Ending line number

        Returns:
            StructuralContext for the line range
        """
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read()

            tree = ast.parse(source)
            symbols = StructuralContextVisitor()
            symbols.visit(tree)

            # Find the most specific context that contains this line range
            matching_symbols = [
                s for s in symbols.symbols
                if s['lineno'] <= start_line and (s['end_lineno'] or s['lineno']) >= end_line
            ]

            if matching_symbols:
                # Return the deepest (most specific) match
                deepest = max(matching_symbols, key=lambda s: s['nesting_level'])
                ctx = StructuralContext(
                    parent_class=deepest.get('parent_class'),
                    parent_method=deepest.get('parent_method') if deepest['type'] == 'function' else None,
                    nesting_level=deepest.get('nesting_level', 0),
                )
                ctx.breadcrumb = deepest.get('parent_context', '')
                return ctx

            return None
        except Exception as e:
            logger.debug(f"Failed to extract context for {file_path}:{start_line}-{end_line}: {e}")
            return None
