"""Validation rules: find KC Works schema problems and propose safe fixes.

Each rule inspects records and returns findings. A finding may carry a
Proposal (the concrete corrected value — value=None means "remove the
field"); findings without a proposal are flag-only and need `edit`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Proposal:
    value: object  # None means: remove the field


@dataclass(frozen=True)
class Finding:
    rule: str
    record_id: str
    field: str
    current: object
    proposal: Proposal | None = None
    note: str | None = None


def available_rules() -> list[str]:
    """Names of all registered rules, in run order."""
    raise NotImplementedError


def run_rules(
    records: list[dict],
    names: list[str] | None = None,
    as_of: str | None = None,
) -> list[Finding]:
    """Run rules (all by default) over records and return their findings."""
    raise NotImplementedError
