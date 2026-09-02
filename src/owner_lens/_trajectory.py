"""Shared net-cash trajectory primitive for OwnerLens interpretation layers.

Internal module. Slices 2A, 2B, and 2C each judge whether a company's net cash
or net debt position improved or deteriorated across two points in time using the
identical rule: a turn to net debt or a deepening net-debt position is genuine
deterioration, while drawing down surplus cash while remaining net-cash positive
is not. Extracted here after three concrete consumers duplicated the rule.
"""

from __future__ import annotations

from typing import NamedTuple


class NetCashTrajectory(NamedTuple):
    """Net cash or net debt movement between a start and an end value.

    ``direction`` is +1 improved, -1 deteriorated, 0 immaterial. ``flipped`` is
    True when the position crossed between net cash and net debt. ``net_debt`` is
    True when the end position is a net-debt position (value < 0).
    """

    direction: int
    flipped: bool
    net_debt: bool


def net_cash_trajectory(
    start: int | None, end: int | None, *, material: float
) -> NetCashTrajectory | None:
    """Classify the net-cash movement from ``start`` to ``end``.

    Returns None when either endpoint is absent. A sign flip between net cash and
    net debt is always material; otherwise the change is material when it exceeds
    ``material`` as a fraction of the prior absolute magnitude.
    """
    if start is None or end is None:
        return None
    if start >= 0 and end < 0:
        return NetCashTrajectory(-1, True, True)
    if start < 0 and end >= 0:
        return NetCashTrajectory(1, True, False)
    base = abs(start) or 1
    rel = (end - start) / base
    net_debt = end < 0
    if rel >= material:
        return NetCashTrajectory(1, False, net_debt)
    if rel <= -material:
        return NetCashTrajectory(-1, False, net_debt)
    return NetCashTrajectory(0, False, net_debt)
