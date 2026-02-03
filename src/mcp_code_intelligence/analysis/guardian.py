"""Guardian system for monitoring project health and managing notifications."""

import json
import os
from pathlib import Path
from typing import Any, List, Dict, Optional
from datetime import datetime

from loguru import logger
from mcp_code_intelligence.analysis.inspectors.empty_body import EmptyBodyInspector
from mcp_code_intelligence.analysis.inspectors.todo import TodoInspector
from mcp_code_intelligence.analysis.duplicates import DuplicateDetector
from mcp_code_intelligence.core.database import VectorDatabase

class GuardianManager:
    """Manages project health checks and ensures users aren't spammed with fixed issues."""

    def __init__(self, database: VectorDatabase, project_root: Path):
        self.database = database
        self.project_root = project_root
        self.state_file = project_root / ".mcp-code-intelligence" / "guardian_state.json"
        self.inspectors = [
            EmptyBodyInspector(),
            TodoInspector(),
        ]
        # We'll use the existing DuplicateDetector as well
        self.duplicate_detector = DuplicateDetector(database)

    def _load_state(self) -> Dict[str, Any]:
        """Load the previous state of the guardian."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load guardian state: {e}")
        
        return {
            "last_analysis": None,
            "reported_issues": {},  # issue_id: {first_seen, last_seen, silenced}
            "silenced_ids": [],     # Global list of silenced issue IDs
            "health_score": 100
        }

    def _save_state(self, state: Dict[str, Any]):
        """Save the current state to disk."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save guardian state: {e}")

    async def get_health_notice(self) -> Optional[str]:
        """Perform a quick health check and return a notice if thresholds are breached.
        
        This manages state so that once a user fixes an issue, it's removed from 'reported'.
        """
        all_chunks = await self.database.get_all_chunks()
        if not all_chunks:
            return None

        # 1. Run All Inspectors
        current_issues = []
        for inspector in self.inspectors:
            current_issues.extend(await inspector.inspect(all_chunks))
        
        # Add duplicate analysis (Level 3 - Exact hashes only for quick notice)
        duplicates = await self.duplicate_detector.detect_all(min_length=150)
        exact_dups = duplicates.get("exact", [])
        for group in exact_dups:
                current_issues.append({
                "id": f"Duplicate:{group['hash']}",
                "title": f"Duplicate Code: {group['count']} instances",
                "severity": "error" if group['count'] > 2 else "warning",
                "description": f"Code block repeated in {group['count']} locations.",
                "type": "duplicate"
            })

        # 2. Manage State & Cleanup Fixed Issues
        state = self._load_state()
        new_reported_issues = {}
        now = datetime.now().isoformat()
        
        was_fixed_count = 0
        new_critical_issues = []
        silenced_ids = set(state.get("silenced_ids", []))

        # Current set of issue IDs
        current_issue_ids = {issue["id"] for issue in current_issues}
        
        # Cleanup fixed issues: If a previously reported issue is NOT in current_issues, it's fixed!
        old_reported = state.get("reported_issues", {})
        for issue_id, info in old_reported.items():
            if issue_id in current_issue_ids:
                # Still there, keep it
                new_reported_issues[issue_id] = info
                new_reported_issues[issue_id]["last_seen"] = now
            else:
                # ISSUE FIXED!
                was_fixed_count += 1
                # If it was silenced, we might want to keep it in silenced_ids just in case it returns,
                # but for simplicity we'll keep silenced_ids as a persistent blacklist.
                logger.info(f"Guardian: Issue solved and cleared: {issue_id}")

        # Check for new issues that might trigger a notice
        for issue in current_issues:
            issue_id = issue["id"]
            
            # Skip if manually silenced by user in the past
            if issue_id in silenced_ids:
                continue

            if issue_id not in old_reported:
                # BRAND NEW ISSUE
                new_reported_issues[issue_id] = {
                    "first_seen": now,
                    "last_seen": now,
                    "title": issue["title"],
                    "severity": issue["severity"]
                }
                if issue["severity"] in ("error", "warning"):
                    new_critical_issues.append(issue)

        # Update and Save
        state["last_analysis"] = now
        state["reported_issues"] = new_reported_issues
        
        # 3. Decision: Should we show a notice?
        # Only show notice if: 
        # A) There are NEW critical issues
        # B) OR there's a significant total count of issues (e.g. > 10)
        
        notice_markdown = None
        
        if new_critical_issues:
            # Format the "Guardian Notice"
            notice_markdown = self._format_notice(new_critical_issues, was_fixed_count)
        elif was_fixed_count > 0 and not current_issue_ids: # Everything finally fixed!
             notice_markdown = "> [!TIP]\n> 🛡️ **Guardian Update:** All issues have been resolved! You are working with a clean codebase. Great job! 🎉"

        self._save_state(state)
        return notice_markdown

    def _format_notice(self, new_issues: List[dict], fixed_count: int) -> str:
        """Format the premium Markdown notice for the chat UI."""
        
        # Determine main title and icon
        has_error = any(i["severity"] == "error" for i in new_issues)
        icon = "🚨" if has_error else "🛡️"
        callout = "CAUTION" if has_error else "WARNING"
        
        lines = [
            f"### {icon} **Guardian Notice: Project Health Status Changed**\n",
            f"> [!{callout}]",
            f"> **Detected:** New technical debt discovered after your recent changes.\n"
        ]
        
        # Limit to show max 3 specific new issues to avoid spam
        for issue in new_issues[:3]:
            lines.append(f"> • **{issue['title']}**: {issue.get('description', '')}")
            if "location" in issue:
                lines.append(f">   `{issue['location']}`")
        
        if len(new_issues) > 3:
            lines.append(f"> • ...and {len(new_issues) - 3} more new items.")

        if fixed_count > 0:
            lines.append(f"\n> [!TIP]\n> **Excellent!** Previously reported **{fixed_count}** issues have been resolved. Thank you for cleaning up! ✅")

        lines.append(
            "\nDetailed analysis available via `analyze_project` or `find_duplicates` tools. You can silence issues by ID."
        )
        
        return "\n".join(lines)

    async def silence_issue(self, issue_id: str) -> bool:
        """Manually silence an issue so it never appears in notices again."""
        state = self._load_state()
        silenced_ids = state.get("silenced_ids", [])
        
        if issue_id not in silenced_ids:
            silenced_ids.append(issue_id)
            state["silenced_ids"] = silenced_ids
            self._save_state(state)
            logger.info(f"Guardian: Issue manually silenced by user: {issue_id}")
            return True
        
        return False

    async def check_intent_duplication(self, intent: str, code_snippet: Optional[str] = None) -> Dict[str, Any]:
        """Check if a proposed logic or intent already exists in the codebase."""
        search_query = intent
        if code_snippet:
            # Combine intent and code for better semantic search
            search_query = f"{intent}\n\n{code_snippet}"
        
        # Search with high threshold to find near-perfect logical matches
        results = await self.database.search(
            query=search_query,
            limit=3,
            similarity_threshold=0.85 # High but allows for some variation in implementation
        )
        
        matches = []
        for res in results:
            # High confidence threshold for "Logic Already Exists" warning
            if res.similarity_score >= 0.92:
                matches.append({
                    "file_path": str(res.file_path),
                    "location": res.location,
                    "function_name": res.function_name,
                    "score": res.similarity_score,
                    "content": res.content
                })
        
        return {
            "duplicate_found": len(matches) > 0,
            "matches": matches
        }
