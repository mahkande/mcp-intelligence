
import asyncio
import os
import sys
import json
import builtins
import time
import logging
from pathlib import Path
from typing import Any, List, Optional, Type
from enum import Enum

from pydantic import BaseModel, Field
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Enable nested event loops
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

# --- SYS.PATH SETUP FOR ABSOLUTE IMPORTS ---
# Add 'src' to sys.path: ../../ from current file
src_path = Path(__file__).resolve().parent.parent.parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Also ensure the broader project root is not missing if needed
# (But ../../ is usually the 'src' folder in this structure: src/mcp_code_intelligence/mcp_impl)

# --- STDOUT PROTECTION ---
try:
    import mcp_code_intelligence.cli.output as output_module
    from rich.console import Console
    output_module.console = Console(file=sys.stderr)
except ImportError:
    pass

# --- PROTOCOL INTEGRITY SECTION ---
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from loguru import logger
logger.remove()

class InterceptHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())

# Log to stderr (captured by VS Code/Copilot)
logger.add(sys.stderr, level="INFO", format="{time} {level} {message}")

# Log to file (easier for user to inspect)
log_file_path = Path.cwd() / "mcp_server.log"
logger.add(str(log_file_path), level="DEBUG", rotation="1 MB", retention="5 days")

logging.basicConfig(handlers=[InterceptHandler()], level=logging.INFO, force=True)

_orig_print = builtins.print
def mcp_print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _orig_print(*args, **kwargs)
builtins.print = mcp_print

# --- PYDANTIC MODELS FOR TOOLS ---

class ListDirectoryArgs(BaseModel):
    relative_path: Optional[str] = Field(None, description="Path relative to project root to list. Defaults to root.")
    pattern: Optional[str] = Field(None, description="Optional glob pattern to filter files (e.g. '*.py').")

class ReadFileArgs(BaseModel):
    relative_path: str = Field(..., description="Path relative to project root.")

class WriteFileArgs(BaseModel):
    relative_path: str = Field(..., description="Path relative to project root.")
    content: str = Field(..., description="The content to write.")

class SearchCodeArgs(BaseModel):
    query: str = Field(..., description="Natural language search query")
    limit: Optional[int] = Field(10, description="Max results (1-50)")
    similarity_threshold: Optional[float] = Field(0.3, description="Min similarity score (0.0-1.0)")

class SearchSimilarArgs(BaseModel):
    file_path: str = Field(..., description="Path to the reference file")
    function_name: Optional[str] = Field(None, description="Optional function name to focus on")
    limit: Optional[int] = Field(10, description="Max results (1-50)")
    similarity_threshold: Optional[float] = Field(0.3, description="Min similarity score (0.0-1.0)")

class SearchContextArgs(BaseModel):
    description: str = Field(..., description="Description of the task or context (e.g. 'implementing user login')")
    limit: Optional[int] = Field(10, description="Max results (1-50)")

class GetProjectStatusArgs(BaseModel):
    pass

class IndexProjectArgs(BaseModel):
    force: Optional[bool] = Field(False, description="Force a complete re-index (skip hash check)")
    workers: Optional[int] = Field(None, description="Number of worker threads (default: auto)")

class AnalyzeProjectArgs(BaseModel):
    threshold_preset: Optional[str] = Field("standard", description="'standard', 'strict', or 'lenient'")
    output_format: Optional[str] = Field("summary", description="'summary' or 'detailed'")

class AnalyzeFileArgs(BaseModel):
    file_path: str = Field(..., description="Relative path to the file to analyze (e.g., 'src/main.py')")

class FindSymbolArgs(BaseModel):
    name: str = Field(..., description="Name of the symbol to find (e.g., 'MyClass', 'my_function')")
    symbol_type: Optional[str] = Field(None, description="Optional filter: 'function', 'class', 'method', or 'variable'")

class GetRelationshipsArgs(BaseModel):
    name: str = Field(..., description="The symbol name (e.g. 'MyClass' or 'my_function')")

class AnalyzeImpactArgs(BaseModel):
    symbol_name: str = Field(..., description="Name of the symbol to analyze")
    max_depth: Optional[int] = Field(5, description="Maximum depth of relationship tracing (default 5, max 10)")

class VisualizeCircularDependenciesArgs(BaseModel):
    pass

class GetProjectHealthPulseArgs(BaseModel):
    pass

class GetComplexityHotspotsArgs(BaseModel):
    limit: Optional[int] = Field(5, description="Number of top risky files to return (default 5, max 50)")

class FindSmellsArgs(BaseModel):
    smell_type: Optional[str] = Field("all", description="Filter by smell (e.g., 'too_many_parameters') or 'all'")
    severity: Optional[str] = Field("warning", description="'error', 'warning', or 'info'")

class InterpretAnalysisArgs(BaseModel):
    analysis_json: str = Field(..., description="JSON string containing analysis data")
    focus: Optional[str] = Field("summary", description="Focus area (summary, security, performance, maintainability)")
    verbosity: Optional[str] = Field("normal", description="Detail level (concise, normal, detailed)")

class FindDuplicatesArgs(BaseModel):
    threshold: Optional[float] = Field(None, description="Similarity threshold (0.0 - 1.0)")

class SilenceHealthIssueArgs(BaseModel):
    issue_id: str = Field(..., description="The ID of the issue to silence")

class ProposeLogicArgs(BaseModel):
    intent: str = Field(..., description="Description of what you want to implement")
    code_draft: Optional[str] = Field(None, description="Optional code snippet you plan to write")

class DebugPingArgs(BaseModel):
    pass


# --- GLOBAL DEFAULTS & UTILS ---
SESSION: Optional[Any] = None

def get_project_root() -> Path:
    project_root = None
    env_project_root = os.getenv("MCP_PROJECT_ROOT") or os.getenv("PROJECT_ROOT")
    if env_project_root:
        project_root = Path(env_project_root).resolve()
    else:
        project_root = Path.cwd().resolve()
    return project_root

async def get_session():
    global SESSION
    if SESSION and getattr(SESSION, "is_initialized", False):
        return SESSION

    logger.info("Starting get_session() - Instantiating service")
    project_root = get_project_root()
    logger.info(f"Using project root: {project_root}")
    
    try:
        # 1. Lazy load to avoid circular imports at module level
        # 2. Use direct path to bypass __init__.py potentially causing cycles
        from mcp_code_intelligence.mcp_impl.services.session import SessionService
        
        if not SESSION:
            logger.info("Creating new SessionService instance...")
            env_value = os.getenv("MCP_ENABLE_FILE_WATCHING", "true").lower()
            enable_file_watching = env_value in ("true", "1", "yes", "on")
            SESSION = SessionService(project_root, enable_file_watching)
            logger.info("SessionService created.")

        if not SESSION.is_initialized:
            logger.info("Initializing session components...")
            await SESSION.initialize()
            logger.info("Session initialized successfully")
            
    except ImportError as e:
        logger.error(f"❌ Critical Import Error in get_session: {e}", exc_info=True)
        raise RuntimeError(f"Failed to import SessionService. Check python path and circular dependencies: {e}")
    except Exception as e:
        logger.error(f"❌ Failed to initialize session: {e}", exc_info=True)
        raise RuntimeError(f"Session initialization failed: {e}")

    return SESSION

# --- IMPLEMENTATION FUNCTIONS (Logic moved from decorated functions) ---

# --- SCHEMA SANITIZER (VS Code Compatibility) ---
def get_clean_schema(model: Type[BaseModel]):
    """Generate JSON schema and remove keys forbidden by VS Code."""
    schema = model.model_json_schema()
    
    def remove_forbidden(d):
        if isinstance(d, dict):
            # Keys that cause 'unsupported schema keyword' warnings in VS Code
            for key in ["default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"]:
                d.pop(key, None)
            for v in d.values():
                remove_forbidden(v)
        elif isinstance(d, list):
            for i in d:
                remove_forbidden(i)
                
    remove_forbidden(schema)
    return schema

# --- SAFETY FILTERS ---
EXCLUDED_FILES = {
    "commandEmbeddings.json", "embeddings.json", ".git", "node_modules",
    "__pycache__", ".venv", "venv", ".tox", "dist", "build"
}
MAX_FILE_SIZE_MB = 5

def should_skip_file(file_path: Path) -> bool:
    try:
        if file_path.name in EXCLUDED_FILES:
            return True
        for part in file_path.parts:
            if part in EXCLUDED_FILES:
                return True
        if file_path.exists() and file_path.is_file():
            size_mb = file_path.stat().st_size / (1024 * 1024)
            if size_mb > MAX_FILE_SIZE_MB:
                logger.debug(f"Skipping large file ({size_mb:.1f}MB): {file_path}")
                return True
        return False
    except Exception:
        return False

def format_search_result(result, index: int) -> List[str]:
    lines = [f"\n## Result {index}"]
    lines.append(f"**File:** {result.file_path}")
    lines.append(f"**Lines:** {result.start_line}-{result.end_line}")
    lines.append(f"**Score:** {result.score:.4f}")
    if result.chunk_type:
        lines.append(f"**Type:** {result.chunk_type}")
    
    code_block = result.content
    if len(code_block) > 2000:
        code_block = code_block[:2000] + "\n... (truncated)"
    
    lines.append(f"\n```python\n{code_block}\n```")
    return lines


async def list_directory_impl(relative_path: Optional[str] = None, pattern: Optional[str] = None) -> str:
    logger.info(f"list_directory_impl called with path='{relative_path}' pattern='{pattern}'")
    relative_path = relative_path or ""
    
    try:
        session = await get_session()
        logger.info(f"Session obtained. Root: {session.project_root}")
    except Exception as e:
        logger.error(f"get_session failed in list_directory: {e}")
        return f"Error initializing session: {e}"
    
    if pattern:
        logger.info(f"📂 [Filesystem] Listing files with pattern: {pattern}")
        files = list(session.project_root.glob(pattern))
        if not files:
            return f"No files matching pattern: {pattern}"
        items = [str(f.relative_to(session.project_root)) for f in sorted(files)]
        return "\n".join(items)
    
    try:
        dir_path = (session.project_root / relative_path).resolve()
        logger.info(f"Resolved dir_path: {dir_path}")
        
        # Security check
        if not str(dir_path).startswith(str(session.project_root.resolve())):
            logger.warning(f"Access denied: {dir_path} outside {session.project_root}")
            raise ValueError(f"Access denied: {relative_path} is outside project root")
        
        if not dir_path.exists():
            logger.warning(f"Directory does not exist: {dir_path}")
            return f"Directory not found: {relative_path}"
        if not dir_path.is_dir():
             logger.warning(f"Path is not a directory: {dir_path}")
             return f"Path is not a directory: {relative_path}"
        
        logger.info(f"📂 [Filesystem] Listing directory: {relative_path or '.'}")
        items = []
        for item in sorted(dir_path.iterdir()):
            prefix = "[DIR] " if item.is_dir() else "[FILE]"
            items.append(f"{prefix} {item.name}")
            
        logger.info(f"Found {len(items)} items")
        return "\n".join(items) if items else "(empty directory)"
    except Exception as e:
        logger.error(f"Error in list_directory logic: {e}", exc_info=True)
        raise

async def read_file_impl(relative_path: str) -> str:
    session = await get_session()
    path = (session.project_root / relative_path).resolve()
    if not str(path).startswith(str(session.project_root.resolve())):
        raise ValueError(f"Access denied: {relative_path} is outside project root")
    
    if not path.exists():
        return f"File not found: {relative_path}"
    
    if should_skip_file(path):
        size_mb = path.stat().st_size / (1024 * 1024)
        logger.warning(f"🚫 [Filesystem] Skipped large file: {relative_path} ({size_mb:.2f} MB)")
        return f"⚠️ Skipped large/excluded file: {relative_path} ({size_mb:.2f} MB > {MAX_FILE_SIZE_MB} MB)"
    
    content = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
    logger.info(f"📖 [Filesystem] Read file: {relative_path} ({len(content)} chars)")
    return content

async def write_file_impl(relative_path: str, content: str) -> str:
    session = await get_session()
    path = (session.project_root / relative_path).resolve()
    if not str(path).startswith(str(session.project_root.resolve())):
        raise ValueError(f"Access denied: {relative_path} is outside project root")
    
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, content, encoding="utf-8")
    logger.success(f"💾 [Filesystem] Wrote file: {relative_path}")
    return f"Successfully wrote to {relative_path}"

async def search_code_impl(query: str, limit: int = 10, similarity_threshold: float = 0.3) -> str:
    # Ensure safe defaults if None passed (though Pydantic handles this, extra safety is good)
    l = limit if limit is not None else 10
    s = similarity_threshold if similarity_threshold is not None else 0.3
    l = max(1, min(50, l))
    s = max(0.0, min(1.0, s))
    
    logger.info(f"LOG: [Step 1] RECEIVED: search_code query='{query}' limit={l} threshold={s}")
    session = await get_session()
    if not session.search_engine:
        return "⏳ Search engine not ready. If the server just started, please wait 10s for models to load. Otherwise, run `index_project`."

    try:
        results = await session.search_engine.search(query=query, limit=l, similarity_threshold=s)
        logger.info(f"🔍 [Search] '{query}' query produced {len(results)} results")
        if not results:
            return f"No results found for query: '{query}'"
            
        filtered_results = [r for r in results if not should_skip_file(Path(r.file_path))]
        if not filtered_results:
             return f"Found {len(results)} results but all were filtered (large/excluded files)."

        response_lines = [f"Found {len(filtered_results)} results for query: '{query}'\n"]
        for i, result in enumerate(filtered_results, 1):
            response_lines.extend(format_search_result(result, i))
        return "\n".join(response_lines)
    except Exception as e:
        logger.error(f"Search failed: {e}", exc_info=True)
        return f"❌ Search Failed\n\nError: {str(e)}"

async def search_similar_impl(file_path: str, function_name: Optional[str] = None, limit: int = 10, similarity_threshold: float = 0.3) -> str:
    limit = limit or 10
    similarity_threshold = similarity_threshold or 0.3
    session = await get_session()
    try:
        resolved_path = (session.project_root / file_path).resolve()
        if should_skip_file(resolved_path):
             return f"⚠️ Skipped similar search for large/excluded file: {file_path}"
    except Exception:
        return f"Invalid path: {file_path}"

    if not session.search_engine:
        return "⏳ Search engine not ready. Please wait for model loading or run `index_project`."

    try:
        results = await session.search_engine.search_similar(
            file_path=resolved_path,
            function_name=function_name,
            limit=limit,
            similarity_threshold=similarity_threshold,
        )
        logger.info(f"👯 [Similar] Found {len(results)} snippets similar to {file_path}")
        if not results:
            return f"No similar code found for {file_path}"

        response_lines = [f"Found {len(results)} similar code snippets for {file_path}\n"]
        for i, result in enumerate(results, 1):
            response_lines.extend(format_search_result(result, i))
        return "\n".join(response_lines)
    except Exception as e:
        logger.error(f"Similar search failed: {e}")
        return f"Similar search failed: {str(e)}"

async def search_context_impl(description: str, limit: int = 10) -> str:
    limit = limit or 10
    session = await get_session()
    if not session.search_engine:
        return "⏳ Search engine not ready. Please wait for model loading or run `index_project`."
    try:
        results = await session.search_engine.search_by_context(context_description=description, limit=limit)
        if not results:
            return f"No contextually relevant code found for: {description}"
        filtered = [r for r in results if not should_skip_file(Path(r.file_path))]
        if not filtered:
             return f"Found {len(results)} results but all were filtered."
        response_lines = [f"Found {len(filtered)} contextually relevant code snippets for: {description}\n"]
        for i, result in enumerate(filtered, 1):
            response_lines.extend(format_search_result(result, i))
        return "\n".join(response_lines)
    except Exception as e:
        logger.error(f"Context search failed: {e}", exc_info=True)
        return f"❌ Context Search Failed\n\nError: {str(e)}"

async def get_project_status_impl() -> str:
    session = await get_session()
    try:
        config = session.project_manager.load_config()
        status_info = {}
        if session.search_engine:
            stats = await session.database.get_stats()
            status_info = {
                "project_root": str(config.project_root),
                "index_path": str(config.index_path),
                "total_chunks": stats.total_chunks,
                "total_files": stats.total_files,
                "index_size": f"{stats.index_size_mb:.2f} MB" if hasattr(stats, "index_size_mb") else "Unknown",
            }
        else:
            status_info = {"status": "Not indexed or initialized"}
        response = "# Project Status\n\n"
        response += f"**Project Root:** {config.project_root}\n"
        if "total_chunks" in status_info:
            response += f"**Total Chunks:** {status_info['total_chunks']}\n"
            response += f"**Total Files:** {status_info['total_files']}\n"
            response += f"**Index Size:** {status_info['index_size']}\n"
        else:
            response += f"**Status:** {status_info.get('status')}\n"
        return response
    except Exception as e:
        logger.error(f"Project status failed: {e}", exc_info=True)
        return f"❌ Project Status Failed\n\nError: {str(e)}"

async def _background_indexer(session, force: bool, workers: Optional[int]):
    try:
        from mcp_code_intelligence.cli.commands.index_runner import run_indexing
        logger.info(f"🏗️  [Indexing] Background task started for {session.project_root}")
        await session.cleanup()
        start_time = time.time()
        await run_indexing(project_root=session.project_root, force_reindex=force, show_progress=False, workers=workers, quiet=True)
        duration = time.time() - start_time
        await session.initialize()
        logger.success(f"✅ [Indexing] Completed successfully in {duration:.1f}s")
    except Exception as e:
        logger.error(f"❌ [Indexing] Background task failed: {e}", exc_info=True)
        try:
            await session.initialize()
        except:
            pass

async def index_project_impl(force: bool = False, workers: Optional[int] = None) -> str:
    session = await get_session()
    try:
        asyncio.create_task(_background_indexer(session, force, workers))
        return (
            f"🚀 **Indexing Started in Background**\n\n"
            f"The indexing process has been queued. Using background task to avoid timeouts.\n"
            f"Use `get_project_status` to check progress."
        )
    except Exception as e:
        logger.error(f"Failed to start indexing task: {e}", exc_info=True)
        return f"❌ Failed to start indexing\n\nError: {str(e)}"

async def analyze_project_impl(threshold_preset: str = "standard", output_format: str = "summary") -> str:
    session = await get_session()
    try:
        from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files
        from mcp_code_intelligence.analysis import ProjectMetrics, CognitiveComplexityCollector, CyclomaticComplexityCollector
        from mcp_code_intelligence.parsers.registry import get_parser_registry

        parser_registry = get_parser_registry()
        files = _find_analyzable_files(session.project_root, None, None, parser_registry, None)
        if not files: return "No analyzable files found."

        metrics = ProjectMetrics(project_root=str(session.project_root))
        collectors = [CognitiveComplexityCollector(), CyclomaticComplexityCollector()]
        analyzed_count = 0
        for f in files:
            if should_skip_file(f): continue
            try:
                fm = await _analyze_file(f, parser_registry, collectors)
                if fm:
                    metrics.files[str(f)] = fm
                    analyzed_count += 1
            except Exception:
                continue
        metrics.compute_aggregates()
        return f"# Project Analysis Summary\n\n- **Files Analyzed:** {analyzed_count}/{len(files)}\n- **Avg Complexity:** {metrics.avg_file_complexity:.2f}\n- **Hotspots:** {len(metrics.hotspots)}\n"
    except Exception as e:
        logger.error(f"Project analysis failed: {e}", exc_info=True)
        return f"❌ Analysis Failed\n\nError: {str(e)}"

async def analyze_file_impl(file_path: str) -> str:
    session = await get_session()
    resolved_path = (session.project_root / file_path).resolve()
    if should_skip_file(resolved_path):
        size_mb = resolved_path.stat().st_size / (1024 * 1024) if resolved_path.exists() else 0
        return f"⚠️ Skipped large/excluded file: {file_path} ({size_mb:.1f}MB)"
    if not resolved_path.exists():
        return f"❌ File not found: {file_path}"
    try:
        from mcp_code_intelligence.cli.commands.analyze import _analyze_file
        from mcp_code_intelligence.analysis import (
            CognitiveComplexityCollector, CyclomaticComplexityCollector, MethodCountCollector,
            NestingDepthCollector, ParameterCountCollector, SmellDetector
        )
        from mcp_code_intelligence.parsers.registry import get_parser_registry
        parser_registry = get_parser_registry()
        collectors = [CognitiveComplexityCollector(), CyclomaticComplexityCollector(), NestingDepthCollector(), ParameterCountCollector(), MethodCountCollector()]
        
        file_metrics = await _analyze_file(resolved_path, parser_registry, collectors)
        if not file_metrics:
            return f"❌ Could not analyze file: {file_path}"
            
        smell_detector = SmellDetector()
        smells = smell_detector.detect_all(file_metrics, str(resolved_path))
        lines = [f"# Analysis for {file_path}\n"]
        lines.append(f"**Valid:** {file_metrics.is_valid}")
        lines.append(f"**Language:** {getattr(file_metrics, 'language', 'unknown')}")
        lines.append(f"**LOC:** {getattr(file_metrics, 'total_lines', 0)}")
        lines.append(f"**Complexity:** {getattr(file_metrics, 'total_complexity', 0)}")
        if smells:
            lines.append(f"\n## Code Smells ({len(smells)})")
            for smell in smells:
                lines.append(f"- [{smell.severity.name}] {smell.message} (Line {smell.line})")
        else:
            lines.append("\n✅ No code smells detected.")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"File analysis failed for {file_path}: {e}", exc_info=True)
        return f"❌ Analysis Failed\n\nFile: {file_path}\nError: {str(e)}"

async def find_symbol_impl(name: str, symbol_type: Optional[str] = None) -> str:
    session = await get_session()
    if not session.search_engine:
        # Check if initialization failed
        if hasattr(session, '_heavy_init_error') and session._heavy_init_error:
            return f"❌ System initialization failed: {session._heavy_init_error}\n\nPlease run: mcp-code-intelligence setup --force"
        # Check if still loading
        if hasattr(session, '_heavy_init_complete') and not session._heavy_init_complete:
            return "⏳ System is still loading (embedding model takes 10-30s). Please wait and try again."
        # Generic fallback
        return "❌ Search engine not initialized. Run: mcp-code-intelligence index"
    try:
        logger.info(f"Finding symbol: {name} (type: {symbol_type or 'any'})")
        results = await session.search_engine.find_symbol(name, symbol_type)
        if not results:
            return f"❌ Symbol '{name}' not found."
        lines = [f"Found {len(results)} definitions for '{name}':\n"]
        for i, result in enumerate(results, 1):
             lines.extend([f"## Definition {i}", f"File: {result.file_path}", f"Lines: {result.start_line}-{result.end_line}", f"Type: {result.chunk_type}", f"\n```python\n{result.content}\n```\n"])
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Symbol search failed: {e}", exc_info=True)
        return f"❌ Symbol Search Failed\n\nError: {str(e)}"

async def get_relationships_impl(name: str) -> str:
    session = await get_session()
    if not session.search_engine:
        return "⏳ Search engine not ready. If the server just started, please wait 10s. Otherwise, run `index_project`."
    try:
        data = await session.search_engine.get_symbol_relationships(name)
        if "error" in data: return f"❌ Error: {data['error']}"
        
        # Check if the symbol was actually rejected/not found
        def_info = data.get("definition", {})
        if not def_info or def_info.get("file") == "Unknown":
             return f"❌ Symbol '{name}' not found in the index. The project might need re-indexing (run `index_project`)."

        lines = [f"# Relationships for '{name}'\n"]
        lines.extend(["## Definition", f"- **File:** {def_info.get('file', 'Unknown')}", f"- **Lines:** {def_info.get('lines', 'Unknown')}", f"- **Type:** {def_info.get('type', 'Unknown')}\n", "## Callers"])
        callers = data.get("callers", [])
        lines.extend([f"- `{c.get('name')}` ({c.get('file')})" for c in callers] if callers else ["- No external callers found."])
        lines.extend(["\n## Callees"])
        callees = data.get("callees", [])
        lines.extend([f"- `{c.get('name')}` ({c.get('file')})" for c in callees] if callees else ["- No internal calls found."])
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Get relationships failed: {e}", exc_info=True)
        return f"❌ Get relationships failed: {str(e)}"

async def analyze_impact_impl(symbol_name: str, max_depth: int = 5) -> str:
    md = max(1, min(10, max_depth))
    session = await get_session()
    try:
        logger.info(f"💥 [Impact] Analyzing ripple effect for symbol: '{symbol_name}' (Depth: {md})")
        from mcp_code_intelligence.core.relationships import analyze_impact
        result = analyze_impact(session.project_root, symbol_name, md)
        if "error" in result: return f"❌ Error: {result['error']}"
        response = [f"# Impact Analysis for '{symbol_name}'\n", f"**Origin:** {result.get('origin', 'Unknown')}", f"**Complexity Score:** {result.get('complexity_score', 0)}", "\n## Immediate Impact"]
        immediate = [f for f in result.get("immediate_impact", []) if not should_skip_file(Path(f))]
        response.extend([f"- {f}" for f in immediate] if immediate else ["- None"])
        response.append("\n## Deep Impact")
        deep = [f for f in result.get("deep_impact", []) if not should_skip_file(Path(f))]
        response.extend([f"- {f}" for f in deep] if deep else ["- None"])
        return "\n".join(response)
    except Exception as e:
        logger.error(f"Impact analysis failed: {e}", exc_info=True)
        return f"❌ Impact analysis failed: {str(e)}"

async def visualize_circular_dependencies_impl() -> str:
    session = await get_session()
    try:
        from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files
        from mcp_code_intelligence.analysis import ProjectMetrics, CognitiveComplexityCollector, CyclomaticComplexityCollector, MethodCountCollector, NestingDepthCollector, ParameterCountCollector, EfferentCouplingCollector
        from mcp_code_intelligence.analysis.interpretation import EnhancedJSONExporter, AnalysisInterpreter
        from mcp_code_intelligence.parsers.registry import get_parser_registry
        
        parser_registry = get_parser_registry()
        files = _find_analyzable_files(session.project_root, None, None, parser_registry, None)
        if not files: return "No analyzable files found."
        
        collectors = [CognitiveComplexityCollector(), CyclomaticComplexityCollector(), NestingDepthCollector(), ParameterCountCollector(), MethodCountCollector(), EfferentCouplingCollector()]
        metrics = ProjectMetrics(project_root=str(session.project_root))
        
        for f in files:
            if should_skip_file(f): continue
            try:
                fm = await _analyze_file(f, parser_registry, collectors)
                if fm and fm.chunks: metrics.files[str(f)] = fm
            except Exception: continue
            
        metrics.compute_aggregates()
        exporter = EnhancedJSONExporter(session.project_root)
        export = exporter.export_with_context(metrics)
        interpreter = AnalysisInterpreter()
        return interpreter.interpret(export, focus="cycles")
    except Exception as e:
        logger.error(f"Circular Check failed: {e}", exc_info=True)
        return f"❌ Circular Check failed: {str(e)}"

async def get_project_health_pulse_impl() -> str:
    try:
        session = await get_session()
        logger.info("Health Pulse: Session initialized")
        from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files
        from mcp_code_intelligence.analysis import ProjectMetrics, CognitiveComplexityCollector, CyclomaticComplexityCollector, MethodCountCollector, NestingDepthCollector, ParameterCountCollector, EfferentCouplingCollector
        from mcp_code_intelligence.core.health import HealthPulseAnalyzer
        from mcp_code_intelligence.parsers.registry import get_parser_registry
        
        files = _find_analyzable_files(session.project_root, None, None, get_parser_registry(), None)
        if not files: return "No analyzable files found in the project."
        
        collectors = [CognitiveComplexityCollector(), CyclomaticComplexityCollector(), NestingDepthCollector(), ParameterCountCollector(), MethodCountCollector(), EfferentCouplingCollector()]
        metrics = ProjectMetrics(project_root=str(session.project_root))
        
        for f in files:
            try:
                fm = await _analyze_file(f, get_parser_registry(), collectors)
                if fm and fm.chunks: metrics.files[str(f)] = fm
            except Exception: continue
            
        metrics.compute_aggregates()
        analyzer = HealthPulseAnalyzer(session.project_root)
        health_summary = analyzer.generate_health_summary(metrics)
        return health_summary + "\n\n> [!IMPORTANT]\n> **AI Architect Directive:** If Health Score < 80, prioritize refactoring."
    except Exception as e:
        logger.error(f"Health Pulse failed: {e}", exc_info=True)
        return f"❌ Health Pulse Analysis Failed\n\nError: {str(e)}"

async def get_complexity_hotspots_impl(limit: int = 5) -> str:
    l = max(1, min(50, limit))
    session = await get_session()
    try:
        from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files
        from mcp_code_intelligence.analysis import ProjectMetrics, CognitiveComplexityCollector, CyclomaticComplexityCollector
        from mcp_code_intelligence.analysis.hotspot_analyzer import HotspotAnalyzer
        from mcp_code_intelligence.analysis.interpretation import EnhancedJSONExporter, AnalysisInterpreter
        from mcp_code_intelligence.parsers.registry import get_parser_registry
        
        files = await asyncio.to_thread(_find_analyzable_files, session.project_root, None, None, get_parser_registry(), None)
        if not files: return "No analyzable files found."
        
        hotspot_analyzer = HotspotAnalyzer(session.project_root)
        churn_metrics = {}
        try:
            if hotspot_analyzer.git_manager:
                churn_metrics = await asyncio.wait_for(asyncio.to_thread(hotspot_analyzer.git_manager.get_churn_metrics, 30), timeout=10.0)
        except Exception: pass
        
        file_priorities = []
        for f in files:
            try:
                rel_path = str(f.relative_to(session.project_root)).replace("\\", "/")
                churn = churn_metrics.get(rel_path, {}).get("commit_count", 0)
                file_priorities.append((f, churn))
            except Exception: file_priorities.append((f, 0))
        file_priorities.sort(key=lambda x: x[1], reverse=True)
        
        files_to_analyze = [p[0] for p in file_priorities[:100]] # capped scan
        metrics = ProjectMetrics(project_root=str(session.project_root))
        collectors = [CognitiveComplexityCollector(), CyclomaticComplexityCollector()]
        
        for f in files_to_analyze:
             if should_skip_file(f): continue
             try:
                 fm = await _analyze_file(f, get_parser_registry(), collectors)
                 if fm and fm.total_lines > 0: metrics.files[str(f)] = fm
             except Exception: continue
             
        metrics.compute_aggregates()
        try:
             metrics = await asyncio.wait_for(asyncio.to_thread(hotspot_analyzer.analyze, metrics), timeout=15.0)
        except Exception: pass
        
        exporter = EnhancedJSONExporter(session.project_root)
        export = exporter.export_with_context(metrics)
        interpreter = AnalysisInterpreter()
        return interpreter.interpret(export, focus="hotspots")
    except Exception as e:
        logger.error(f"Hotspot detection failed: {e}", exc_info=True)
        return f"❌ Hotspot Detection Failed: {str(e)}"

async def find_smells_impl(smell_type: str = "all", severity: str = "warning") -> str:
    session = await get_session()
    try:
        from mcp_code_intelligence.cli.commands.analyze import _analyze_file, _find_analyzable_files
        from mcp_code_intelligence.analysis import ProjectMetrics, CognitiveComplexityCollector, CyclomaticComplexityCollector, MethodCountCollector, NestingDepthCollector, ParameterCountCollector, SmellDetector, SmellSeverity
        from mcp_code_intelligence.parsers.registry import get_parser_registry
        
        files = _find_analyzable_files(session.project_root, None, None, get_parser_registry(), None)
        if not files: return "No analyzable files found."
        
        metrics = ProjectMetrics(project_root=str(session.project_root))
        collectors = [CognitiveComplexityCollector(), CyclomaticComplexityCollector(), NestingDepthCollector(), ParameterCountCollector(), MethodCountCollector()]
        for f in files:
            if should_skip_file(f): continue
            try:
                fm = await _analyze_file(f, get_parser_registry(), collectors)
                if fm: metrics.files[str(f)] = fm
            except Exception: continue
            
        detector = SmellDetector()
        all_smells = []
        for path, fm in metrics.files.items():
            all_smells.extend(detector.detect_all(fm, path))
            
        filtered = all_smells
        if smell_type and smell_type != "all":
            filtered = [s for s in filtered if s.name == smell_type]
        if severity:
            try:
                sev_enum = SmellSeverity(severity.lower())
                filtered = [s for s in filtered if s.severity == sev_enum]
            except ValueError: pass # ignore invalid severity
        
        if not filtered: return "No code smells found matching the criteria."
        
        lines = [f"# Code Smells Found: {len(filtered)}\n"]
        for s in filtered[:50]: # cap
            lines.append(f"- **{s.name}** at `{s.location}`: {s.description}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Smell detection failed: {e}", exc_info=True)
        return f"❌ Smell detection failed: {str(e)}"

async def interpret_analysis_impl(analysis_json: str, focus: str = "summary", verbosity: str = "normal") -> str:
    session = await get_session()
    try:
        from mcp_code_intelligence.analysis.interpretation import AnalysisInterpreter, LLMContextExport
        data = json.loads(analysis_json)
        export = LLMContextExport(**data)
        interpreter = AnalysisInterpreter()
        return interpreter.interpret(export, focus=focus, verbosity=verbosity)
    except Exception as e:
        logger.error(f"Interpretation failed: {e}", exc_info=True)
        return f"❌ Interpretation failed: {str(e)}"

async def find_duplicates_impl(threshold: Optional[float] = None) -> str:
    # Manual validation isn't strictly necessary with Pydantic but good for logic consistency
    if threshold is not None:
        threshold = max(0.0, min(1.0, threshold))
    session = await get_session()
    if not session.search_engine:
        return "❌ Search engine not initialized. Please run `index_project` first."
    try:
        from mcp_code_intelligence.mcp_impl.duplicates_tool import handle_find_duplicates
        args = {"threshold": threshold} if threshold is not None else {}
        res = await handle_find_duplicates(session.search_engine, args)
        if hasattr(res, 'content') and isinstance(res.content, list):
             return "\n".join([c.text for c in res.content if c.type == 'text'])
        return str(res)
    except Exception as e:
        logger.error(f"Find duplicates failed: {e}", exc_info=True)
        return f"❌ Find duplicates failed: {str(e)}"

async def silence_health_issue_impl(issue_id: str) -> str:
    session = await get_session()
    if not session.guardian: return "❌ Guardian not initialized"
    try:
        success = await session.guardian.silence_issue(issue_id)
        return f"✅ Issue '{issue_id}' has been silenced." if success else f"ℹ️ Issue '{issue_id}' was already silenced or not found."
    except Exception as e:
        logger.error(f"Silence issue failed: {e}", exc_info=True)
        return f"❌ Silence issue failed: {str(e)}"

async def propose_logic_impl(intent: str, code_draft: Optional[str] = None) -> str:
    session = await get_session()
    if not session._enable_logic_check: return "ℹ️ Logic Check feature is currently disabled."
    if not session.guardian: return "❌ Guardian not initialized."
    try:
        analysis = await session.guardian.check_intent_duplication(intent, code_draft)
        if not analysis["duplicate_found"]: return "✅ No similar logic found. Proceed."
        lines = ["### 🛑 STOP! LOGIC DUPLICATION DETECTED\n> [!CAUTION]\n> **Highly similar logic already exists.**\n"]
        for i, match in enumerate(analysis["matches"], 1):
             lines.append(f"#### 🔍 Match {i} (Confidence: {match['score']:.2f})\n- **File:** `{match['file_path']}`\n- **Symbol:** `{match['function_name'] or 'Global'}`")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Propose logic failed: {e}")
        return f"Propose logic failed: {str(e)}"

async def debug_ping_impl() -> str:
    import sys
    return f"🏓 Pong! PID: {os.getpid()} Python: {sys.executable} Server: mcp.server.Server (Manual/Refactored)"

# --- SERVER INSTANCE & ROUTING ---

server = Server("mcp-code-intelligence")

@server.list_tools()
async def list_tools() -> list[Tool]:
    """Register tools with explicit, sanitized schemas."""
    logger.info("🛠️ [Server] list_tools called - registering 22 tools...")
    try:
        tools = [
            Tool(name="list_directory", description="List files and directories.", inputSchema=get_clean_schema(ListDirectoryArgs)),
            Tool(name="read_file", description="Read file content.", inputSchema=get_clean_schema(ReadFileArgs)),
            Tool(name="write_file", description="Write content to a file.", inputSchema=get_clean_schema(WriteFileArgs)),
            Tool(name="search_code", description="Natural language search.", inputSchema=get_clean_schema(SearchCodeArgs)),
            Tool(name="search_similar", description="Find similar code.", inputSchema=get_clean_schema(SearchSimilarArgs)),
            Tool(name="search_context", description="Search by context.", inputSchema=get_clean_schema(SearchContextArgs)),
            Tool(name="get_project_status", description="Get project status.", inputSchema=get_clean_schema(GetProjectStatusArgs)),
            Tool(name="index_project", description="Re-index project.", inputSchema=get_clean_schema(IndexProjectArgs)),
            Tool(name="analyze_project", description="Analyze entire project.", inputSchema=get_clean_schema(AnalyzeProjectArgs)),
            Tool(name="analyze_file", description="Analyze a file.", inputSchema=get_clean_schema(AnalyzeFileArgs)),
            Tool(name="find_symbol", description="Find a symbol definition.", inputSchema=get_clean_schema(FindSymbolArgs)),
            Tool(name="get_relationships", description="Analyze symbol relationships.", inputSchema=get_clean_schema(GetRelationshipsArgs)),
            Tool(name="analyze_impact", description="Analyze impact of changes.", inputSchema=get_clean_schema(AnalyzeImpactArgs)),
            Tool(name="visualize_circular_dependencies", description="Visualize circular dependencies.", inputSchema=get_clean_schema(VisualizeCircularDependenciesArgs)),
            Tool(name="get_project_health_pulse", description="Get health overview.", inputSchema=get_clean_schema(GetProjectHealthPulseArgs)),
            Tool(name="get_complexity_hotspots", description="Identify complexity info.", inputSchema=get_clean_schema(GetComplexityHotspotsArgs)),
            Tool(name="find_smells", description="Find code smells.", inputSchema=get_clean_schema(FindSmellsArgs)),
            Tool(name="interpret_analysis", description="Interpret analysis JSON.", inputSchema=get_clean_schema(InterpretAnalysisArgs)),
            Tool(name="find_duplicates", description="Find duplicates.", inputSchema=get_clean_schema(FindDuplicatesArgs)),
            Tool(name="silence_health_issue", description="Silence a health issue.", inputSchema=get_clean_schema(SilenceHealthIssueArgs)),
            Tool(name="propose_logic", description="Check for duplicate logic.", inputSchema=get_clean_schema(ProposeLogicArgs)),
            Tool(name="debug_ping", description="Ping the server.", inputSchema=get_clean_schema(DebugPingArgs)),
        ]
        logger.info(f"✅ [Server] Successfully registered {len(tools)} tools.")
        return tools
    except Exception as e:
        logger.error(f"❌ [Server] Failed to register tools: {e}", exc_info=True)
        # Verify if we should re-raise or return empty list (re-raising is better to know it failed)
        raise e

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route tool calls to implementation functions, validating args with Pydantic."""
    # Debug log to see exactly what VS Code sends
    logger.info(f"📞 [Tool Call] Name: {name} | Args: {arguments}")
    
    try:
        # Pydantic validation: args = Model(**arguments)
        if name == "list_directory":
            # Gracefully handle missing arguments if VS Code sends empty dict
            args = ListDirectoryArgs(**(arguments or {}))
            result = await list_directory_impl(args.relative_path, args.pattern)
        elif name == "read_file":
            args = ReadFileArgs(**arguments)
            result = await read_file_impl(args.relative_path)
        elif name == "write_file":
            args = WriteFileArgs(**arguments)
            result = await write_file_impl(args.relative_path, args.content)
        elif name == "search_code":
            args = SearchCodeArgs(**arguments)
            result = await search_code_impl(args.query, args.limit, args.similarity_threshold)
        elif name == "search_similar":
            args = SearchSimilarArgs(**arguments)
            result = await search_similar_impl(args.file_path, args.function_name, args.limit, args.similarity_threshold)
        elif name == "search_context":
            args = SearchContextArgs(**arguments)
            result = await search_context_impl(args.description, args.limit)
        elif name == "get_project_status":
            # No args model needed for logic, but verified empty schema
            result = await get_project_status_impl()
        elif name == "index_project":
            args = IndexProjectArgs(**arguments)
            result = await index_project_impl(args.force, args.workers)
        elif name == "analyze_project":
            args = AnalyzeProjectArgs(**arguments)
            result = await analyze_project_impl(args.threshold_preset, args.output_format)
        elif name == "analyze_file":
            args = AnalyzeFileArgs(**arguments)
            result = await analyze_file_impl(args.file_path)
        elif name == "find_symbol":
            args = FindSymbolArgs(**arguments)
            result = await find_symbol_impl(args.name, args.symbol_type)
        elif name == "get_relationships":
            args = GetRelationshipsArgs(**arguments)
            result = await get_relationships_impl(args.name)
        elif name == "analyze_impact":
            args = AnalyzeImpactArgs(**arguments)
            result = await analyze_impact_impl(args.symbol_name, args.max_depth)
        elif name == "visualize_circular_dependencies":
            result = await visualize_circular_dependencies_impl()
        elif name == "get_project_health_pulse":
            result = await get_project_health_pulse_impl()
        elif name == "get_complexity_hotspots":
            args = GetComplexityHotspotsArgs(**arguments)
            result = await get_complexity_hotspots_impl(args.limit)
        elif name == "find_smells":
            args = FindSmellsArgs(**arguments)
            result = await find_smells_impl(args.smell_type, args.severity)
        elif name == "interpret_analysis":
            args = InterpretAnalysisArgs(**arguments)
            result = await interpret_analysis_impl(args.analysis_json, args.focus, args.verbosity)
        elif name == "find_duplicates":
            args = FindDuplicatesArgs(**arguments)
            result = await find_duplicates_impl(args.threshold)
        elif name == "silence_health_issue":
            args = SilenceHealthIssueArgs(**arguments)
            result = await silence_health_issue_impl(args.issue_id)
        elif name == "propose_logic":
            args = ProposeLogicArgs(**arguments)
            result = await propose_logic_impl(args.intent, args.code_draft)
        elif name == "debug_ping":
            result = await debug_ping_impl()
        else:
            raise ValueError(f"Unknown tool: {name}")

        return [TextContent(type="text", text=str(result))]

    except Exception as e:
        logger.error(f"Error calling tool {name}: {e}", exc_info=True)
        # Return error as content so the LLM sees it
        return [TextContent(type="text", text=f"Error executing {name}: {str(e)}")]

async def serve() -> None:
    options = server.create_initialization_options()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, options, raise_exceptions=True)

def run_mcp_server(project_root: Path | None = None):
    """Run the MCP server with an optional project root."""
    if project_root:
        os.environ["MCP_PROJECT_ROOT"] = str(project_root)
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass

def main():
    asyncio.run(serve())

if __name__ == "__main__":
    main()
