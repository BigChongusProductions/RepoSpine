"""
Evaluation scoring primitives — pure math, no database access.

All functions are deterministic and side-effect-free.
Spec reference: eval-system-implementation-spec.md §4.
"""
import math
from typing import Dict, Optional


def score_with_confidence(
    raw_score: float, sample_size: int, min_samples: int = 3
) -> Optional[float]:
    """Blend raw score toward neutral (50) when sample size is low.

    With 0 samples, returns None (excluded from composite, weight
    redistributed).  With >= min_samples, returns the raw score unchanged.

    Examples (min_samples=3):
        0 samples → None
        1 sample  → 66.7  (raw=100)
        2 samples → 83.3  (raw=100)
        3 samples → 100.0 (raw=100)
    """
    if sample_size == 0:
        return None
    confidence = min(1.0, sample_size / min_samples)
    blended = (raw_score * confidence) + (50 * (1 - confidence))
    return max(0.0, min(100.0, blended))


def estimate_tokens(text: str) -> int:
    """Estimate token count for a text string.

    Tries tiktoken if available; falls back to words * 1.3.
    The fallback is within ~10% of tiktoken for English markdown.
    """
    try:
        import tiktoken

        enc = tiktoken.encoding_for_model("claude-3-opus-20240229")
        return len(enc.encode(text))
    except ImportError:
        return int(len(text.split()) * 1.3)


def sigmoid_penalty(actual: float, target: float) -> float:
    """Score 0-100 with gentle penalty up to 1.5x target, steep above.

    At or below target → 100.  Above target the score drops on a sigmoid
    curve centered at 1.5x the target.

    Args:
        actual: The measured value (e.g. word count).
        target: The ideal maximum value.

    Returns:
        Score between 0 and 100.
    """
    if target <= 0 or actual <= target:
        return 100.0
    ratio = actual / target
    return max(0.0, 100.0 / (1 + math.exp(3 * (ratio - 1.5))))


def weighted_composite(
    scores: Dict[str, Optional[float]], weights: Dict[str, float]
) -> Optional[float]:
    """Compute weighted average, redistributing weight from None scores.

    Scores that are None are excluded and their weight is redistributed
    proportionally among active (non-None) scores.  If all scores are None,
    returns None.

    Args:
        scores: Mapping of metric ID to score (0-100) or None.
        weights: Mapping of metric ID to weight (should sum to ~1.0).

    Returns:
        Composite score 0-100, or None if no active scores.
    """
    active = {k: w for k, w in weights.items() if scores.get(k) is not None}
    total_weight = sum(active.values())
    if total_weight == 0:
        return None
    normalized = {k: w / total_weight for k, w in active.items()}
    result = sum(scores[k] * normalized[k] for k in normalized)
    return max(0.0, min(100.0, result))
