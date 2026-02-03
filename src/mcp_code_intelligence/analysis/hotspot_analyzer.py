
from pathlib import Path
from loguru import logger
from mcp_code_intelligence.analysis.metrics import ProjectMetrics
from mcp_code_intelligence.core.git import GitManager

class HotspotAnalyzer:
    """Analyzes code hotspots by combining complexity metrics and git churn."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        try:
            self.git_manager = GitManager(project_root)
        except Exception as e:
            logger.warning(f"Git not available for hotspot analysis: {e}")
            self.git_manager = None

    def analyze(self, project_metrics: ProjectMetrics, days: int = 30) -> ProjectMetrics:
        """Enrich project metrics with git churn and calculate risk scores."""
        if not self.git_manager:
            return project_metrics

        logger.info(f"Calculating hotspots using git history from the last {days} days...")
        churn_metrics = self.git_manager.get_churn_metrics(days=days)

        for rel_path, file_metrics in project_metrics.files.items():
            # Normalize path for matching (standardizing separators)
            normalized_path = rel_path.replace("\\", "/")
            
            git_data = churn_metrics.get(normalized_path)
            if not git_data:
                # Try relative path if rel_path is absolute or different
                try:
                    p = Path(rel_path)
                    if p.is_absolute():
                        normalized_path = str(p.relative_to(self.project_root)).replace("\\", "/")
                        git_data = churn_metrics.get(normalized_path)
                except Exception:
                    pass

            if git_data:
                file_metrics.churn_count = git_data.get("commit_count", 0)
                file_metrics.author_count = git_data.get("author_count", 0)
            
            # RiskScore = (Churn * 1.5) + (Complexity * 2.0)
            # We use avg_complexity or total_complexity? 
            # The prompt says Complexity, usually it refers to Cognitive Complexity base.
            # Let's use avg_complexity as it's more representative of the file's density.
            file_metrics.risk_score = (file_metrics.churn_count * 1.5) + (file_metrics.avg_complexity * 2.0)

        # Re-compute aggregates to refresh hotspots lists
        project_metrics.compute_aggregates()
        return project_metrics
