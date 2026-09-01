"""Typed state shared by the M4 clients, resolver, and planner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Access(str, Enum):
    PASS = "PASS"
    DENIED = "DENIED"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class Resolution(str, Enum):
    RESOLVED = "RESOLVED"
    UNMAPPED = "UNMAPPED"
    AMBIGUOUS = "AMBIGUOUS"
    NEEDS_REVIEW = "NEEDS_REVIEW"


@dataclass(frozen=True)
class Dataset:
    name: str
    access: Access
    records: Optional[tuple[dict[str, Any], ...]]
    status: Optional[int] = None
    reason: str = ""

    @property
    def count(self) -> Optional[int]:
        return None if self.records is None else len(self.records)


@dataclass
class Candidate:
    object_type: str
    netbox_id: int
    host: str
    display_name: str
    management_ip: Optional[str]
    site: Optional[str]
    role: Optional[str]
    platform: Optional[str]
    eligible: Optional[bool]
    eligibility_state: Resolution
    mapping_state: Resolution
    ip_state: Resolution
    groups: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()
    reasons: list[str] = field(default_factory=list)

    @property
    def identity(self) -> tuple[str, str]:
        return self.object_type, str(self.netbox_id)

    @property
    def actionable(self) -> bool:
        return (
            self.eligible is True
            and self.eligibility_state is Resolution.RESOLVED
            and self.mapping_state is Resolution.RESOLVED
            and self.ip_state is Resolution.RESOLVED
        )


@dataclass
class Action:
    kind: str
    identity: tuple[str, str]
    changes: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class Plan:
    mode: str = "DRY_RUN"
    source_complete: bool = False
    source_counts: dict[str, Optional[int]] = field(default_factory=dict)
    endpoint_access: dict[str, str] = field(default_factory=dict)
    candidate_counts: dict[str, int] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)
    change_ratio: float = 0.0
    change_budget: float = 0.10
    gates: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def counts_by_action(self) -> dict[str, Any]:
        counts: dict[str, Any] = {
            name: 0
            for name in (
                "CREATE",
                "UPDATE",
                "UNCHANGED",
                "UNMAPPED",
                "AMBIGUOUS",
                "NEEDS_REVIEW",
                "SKIPPED",
                "ORPHAN",
                "IP_CHANGE_REVIEW",
                "TEMPLATE_DRIFT",
                "GROUP_DRIFT",
            )
        }
        for action in self.actions:
            counts[action.kind] = counts.get(action.kind, 0) + 1
        if not self.source_complete:
            counts["ORPHAN"] = None
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "netbox-zabbix-sync-report-v1",
            "mode": self.mode,
            "source_complete": self.source_complete,
            "source_counts": self.source_counts,
            "endpoint_access": self.endpoint_access,
            "candidate_counts": self.candidate_counts,
            "action_counts": self.counts_by_action(),
            "change_ratio": round(self.change_ratio, 6),
            "change_budget": self.change_budget,
            "gates": self.gates,
            "errors": self.errors,
        }
