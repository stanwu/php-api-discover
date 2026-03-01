"""
Framework-aware scoring engine.

Takes a list of ScoreBreakdownItems and returns a final clamped score [0, 100].
Score starts at 0 and each breakdown item's delta is summed then clamped.
"""

from typing import List

from .models import ScoreBreakdownItem


def score_file(breakdown: List[ScoreBreakdownItem]) -> int:
    """Sum all deltas and clamp to [0, 100]."""
    total = sum(item.delta for item in breakdown)
    return max(0, min(100, total))
