"""
Remediation engine — fix suggestions, auto-fix commands, recommendation rules.

Maps evaluation check results to prioritized, actionable suggestions.
Runs after all layers are scored.

Spec reference: eval-system-implementation-spec.md §12.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class EvalCheckResult:
    """Result of a single evaluation check (D1-D8, P1-P7, V1-V4).

    Every check produces one of these, carrying both the score and
    remediation guidance alongside it.
    """

    id: str  # "D1", "P4", etc.
    name: str  # "Tools — Script Deployment"
    score: Optional[float]  # 0-100 or None
    max_score: float = 100.0
    details: str = ""  # Human-readable status line
    remediation: str = ""  # What to fix (empty if score=100)
    auto_fixable: bool = False  # Can eval auto-generate a fix command?
    fix_command: Optional[str] = None  # Shell command to fix the issue
    sub_checks: List[dict] = field(default_factory=list)  # Individual results

    def to_dict(self) -> dict:
        """Serialize for JSON storage in evaluations table."""
        return {
            "score": self.score,
            "details": self.details,
            "remediation": self.remediation,
            "auto_fixable": self.auto_fixable,
            "fix_command": self.fix_command,
        }


@dataclass
class Recommendation:
    """A prioritized, actionable suggestion from the recommendation engine."""

    priority: int  # 1=critical, 2=important, 3=nice-to-have
    category: str  # "deployment", "process", "improvement"
    message: str  # Human-readable suggestion
    trigger: str  # Which metric triggered this ("D2", "P4", etc.)
    auto_task: Optional[str] = None  # db_queries.sh quick command, or None


@dataclass
class RecommendationRule:
    """A rule that maps a score condition to a Recommendation."""

    condition: Callable[[Dict[str, Optional[float]]], bool]
    priority: int
    category: str
    message: str
    trigger: str
    auto_task: Optional[str] = None


# ── Rule definitions (from spec §12) ──────────────────────────────

RULES: List[RecommendationRule] = [
    # Priority 1 — Critical
    RecommendationRule(
        condition=lambda s: (s.get("D2") or 100) < 50,
        priority=1,
        category="deployment",
        message=(
            "Database integrity is critically low. "
            "Run health check and restore from backup if needed."
        ),
        trigger="D2",
        auto_task=(
            'bash db_queries.sh quick '
            '"[eval-fix] Restore database integrity" P3-IMPLEMENT bug'
        ),
    ),
    RecommendationRule(
        condition=lambda s: s.get("D7") == 0,
        priority=1,
        category="deployment",
        message=(
            "Unfilled placeholders detected in operational files. "
            "Deployment is incomplete."
        ),
        trigger="D7",
        auto_task=(
            'bash db_queries.sh quick '
            '"[eval-fix] Replace stray %%PLACEHOLDER%% in operational files" '
            "P3-IMPLEMENT bug"
        ),
    ),
    # Priority 2 — Important
    RecommendationRule(
        condition=lambda s: (s.get("P4") or 100) < 60,
        priority=2,
        category="process",
        message=(
            "Research discipline is low. "
            "Consider formalizing research step in task workflow."
        ),
        trigger="P4",
    ),
    RecommendationRule(
        condition=lambda s: (s.get("D6") or 100) < 70,
        priority=2,
        category="deployment",
        message=(
            "Context files are token-heavy. "
            "Review CLAUDE.md for trimming opportunities."
        ),
        trigger="D6",
        auto_task=(
            'bash db_queries.sh quick '
            '"[eval-fix] Reduce context file token count" '
            "P3-IMPLEMENT improvement"
        ),
    ),
    RecommendationRule(
        condition=lambda s: (s.get("D3") or 100) < 75,
        priority=2,
        category="deployment",
        message=(
            "Infrastructure deployment is incomplete. "
            "Check hooks, agents, and rules configuration."
        ),
        trigger="D3",
    ),
    # Priority 3 — Nice to have
    RecommendationRule(
        condition=lambda s: s.get("V2") is not None and s["V2"] < 50,
        priority=3,
        category="improvement",
        message=(
            "Lesson capture rate is low. "
            "Use: bash db_queries.sh log-lesson after corrections."
        ),
        trigger="V2",
    ),
    RecommendationRule(
        condition=lambda s: s.get("P6") is None,
        priority=3,
        category="process",
        message=(
            "No assumptions recorded. Consider logging key assumptions "
            "with: bash db_queries.sh assume"
        ),
        trigger="P6",
    ),
]


def get_recommendations(
    scores: Dict[str, Optional[float]],
) -> List[Recommendation]:
    """Match scores against rules, return sorted recommendations.

    Args:
        scores: Mapping of check ID ("D1", "P4", etc.) to score 0-100
                or None.

    Returns:
        List of Recommendation objects, sorted by priority (1 first).
    """
    recs: List[Recommendation] = []
    for rule in RULES:
        try:
            if rule.condition(scores):
                recs.append(
                    Recommendation(
                        priority=rule.priority,
                        category=rule.category,
                        message=rule.message,
                        trigger=rule.trigger,
                        auto_task=rule.auto_task,
                    )
                )
        except (KeyError, TypeError):
            continue
    recs.sort(key=lambda r: r.priority)
    return recs
