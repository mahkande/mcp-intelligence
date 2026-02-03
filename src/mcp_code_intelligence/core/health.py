from pathlib import Path
from typing import Any
import logging

from mcp_code_intelligence.analysis.metrics import ProjectMetrics
from mcp_code_intelligence.analysis.hotspot_analyzer import HotspotAnalyzer
from mcp_code_intelligence.analysis.collectors.coupling import (
    ImportGraph,
    CircularDependencyDetector,
    build_import_graph_from_dict
)

logger = logging.getLogger(__name__)

class HealthPulseAnalyzer:
    """Consolidates project metrics into a high-level health summary."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.hotspot_analyzer = HotspotAnalyzer(project_root)

    def generate_health_summary(self, project_metrics: ProjectMetrics) -> str:
        """Analyze project and return a Markdown dashboard summary."""
        # 1. Enrich with Hotspots
        project_metrics = self.hotspot_analyzer.analyze(project_metrics)
        
        # 2. Detect Circular Dependencies
        # Note: We need to build the graph first. 
        # For simplicity, we use the paths from project_metrics.
        import_graph_raw = {path: f.coupling.imports for path, f in project_metrics.files.items()}
        graph = build_import_graph_from_dict(import_graph_raw)
        
        # We need to populate line numbers if we want the rich view, 
        # but for a summary, just the count is enough.
        # Actually, let's use the rich version we implemented in JSONExporter logic
        import_graph_obj = ImportGraph()
        for path, f in project_metrics.files.items():
            import_graph_obj.add_node(path)
            edges_data = getattr(f.coupling, "import_edges", [])
            for e in edges_data:
                import_graph_obj.add_edge(path, e["module"], e["line"])
        
        detector = CircularDependencyDetector(import_graph_obj)
        cycles = detector.detect_cycles()
        
        # 3. Calculate Score
        # Başlangıç 100.
        # Her kritik hotspot (Risk > 100) (-10)
        # Her warning hotspot (Risk > 50) (-5)
        # Her dairesel bağımlılık döngüsü (-5, maks -30)
        
        score = 100
        critical_hotspots = []
        warning_hotspots = []
        
        for file_metrics in project_metrics.files.values():
            if file_metrics.risk_score > 100:
                score -= 10
                critical_hotspots.append(file_metrics)
            elif file_metrics.risk_score > 50:
                score -= 5
                warning_hotspots.append(file_metrics)
        
        cycle_deduction = len(cycles) * 5
        if cycle_deduction > 30:
            cycle_deduction = 30
        score -= cycle_deduction
        
        # Ensure score is between 0 and 100
        score = max(0, min(100, score))
        
        # 4. Format Output
        status_emoji = "🟢" if score >= 80 else "🟡" if score >= 50 else "🔴"
        
        lines = [
            f"# 📊 Project Health Pulse: {status_emoji} {score}/100",
            "",
            "## 🏥 Durum Paneli (Dashboard)",
            f"| Metric | Value | Status |",
            f"| :--- | :--- | :--- |",
            f"| **Overall Health** | {score}/100 | {'SAFE' if score >= 80 else 'UNSAFE'} |",
            f"| **Active Hotspots** | {len(critical_hotspots) + len(warning_hotspots)} | {'⚠️ ALERT' if critical_hotspots else 'OK'} |",
            f"| **Circular Deps** | {len(cycles)} | {'🚨 ERROR' if cycles else 'OK'} |",
            f"| **Avg Complexity** | {project_metrics.avg_file_complexity:.2f} | - |",
            "",
            "## 🚨 En Riskli 3 Hotspot",
        ]
        
        # Sort and take top 3
        top_hotspots = sorted(
            list(project_metrics.files.values()), 
            key=lambda x: x.risk_score, 
            reverse=True
        )[:3]
        
        if top_hotspots:
            lines.append("| Heatmap | File | Risk | Status |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for h in top_hotspots:
                hmap = "🔥🔥🔥" if h.risk_score > 100 else "🔥🔥" if h.risk_score > 70 else "🔥" if h.risk_score > 40 else "🟢"
                status = "CRITICAL" if h.risk_score > 100 else "WARNING" if h.risk_score > 50 else "STABLE"
                lines.append(f"| {hmap} | `{Path(h.file_path).name}` | {h.risk_score:.1f} | {status} |")
        else:
            lines.append("_Great! No high-risk hotspots found._")
            
        lines.append("")
        lines.append("## 🔄 Dependency Summary")
        if cycles:
            lines.append(f"⚠️ **{len(cycles)}** circular dependencies detected. This affects modularity.")
        else:
            lines.append("✅ No circular dependencies found. Architecture is clean.")
            
        # 4. Actionable Recommendations
        lines.append("\n## 💡 Next Steps")
        
        # Determine the most risky file for recommendations
        most_risky = None
        if critical_hotspots:
            most_risky = sorted(critical_hotspots, key=lambda x: x.risk_score, reverse=True)[0]
        elif warning_hotspots:
            most_risky = sorted(warning_hotspots, key=lambda x: x.risk_score, reverse=True)[0]

        # Check for low-scoring files for general recommendations
        low_scoring_files = [f for f in project_metrics.files.values() if f.risk_score > 0 and f.risk_score <= 50]

        if most_risky:
            lines.append(f"👉 **URGENT:** Reduce complexity in `{Path(most_risky.file_path).name}`. This is currently the most fragile part of the project.")
        elif cycles:
            lines.append(f"👉 **PRIORITY:** Stabilize architecture by breaking circular dependencies.")
        elif low_scoring_files:
            lines.append(f"👉 **SUGGESTION:** Refactor low-scoring files to improve overall code quality.")
        else:
            lines.append(f"👉 **STATUS:** System is healthy. You can continue developing new features.")
            
        return "\n".join(lines)
