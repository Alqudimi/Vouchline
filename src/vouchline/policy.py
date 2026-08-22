"""Deterministic policy assertions over verified evidence."""

from __future__ import annotations

from .errors import PolicyError
from .integrity import verify_artifact
from .models import Artifact, Policy, PolicyFinding, PolicyReport


def evaluate_policy(artifact: Artifact, policy: Policy) -> PolicyReport:
    verify_artifact(artifact)
    denied = set(policy.deny_tools)
    required = set(policy.require_tools)
    denied_statuses = set(policy.deny_statuses)
    tool_names: list[str] = []
    findings: list[PolicyFinding] = []
    response_statuses: list[tuple[int, str, str | None]] = []
    total_cost: float = 0.0
    total_tokens: int = 0

    for event in artifact.events:
        if event.kind == "tool.requested":
            tool = event.payload.get("tool")
            if not isinstance(tool, str) or not tool:
                raise PolicyError(
                    "tool request is missing a valid tool name",
                    details={"sequence": event.sequence},
                )
            tool_names.append(tool)
            if tool in denied:
                findings.append(
                    PolicyFinding(
                        rule="deny_tools",
                        message=f"tool '{tool}' is denied by policy",
                        sequence=event.sequence,
                        call_id=event.call_id,
                    )
                )
        elif event.kind == "tool.responded":
            status = event.payload.get("status")
            if not isinstance(status, str) or not status:
                raise PolicyError(
                    "tool response is missing a valid status",
                    details={"sequence": event.sequence},
                )
            response_statuses.append((event.sequence, status, event.call_id))

            # Extract usage metrics if available
            usage = event.payload.get("usage", {})
            if isinstance(usage, dict):
                total_cost += float(usage.get("cost", 0.0))
                total_tokens += int(usage.get("total_tokens", 0))

    if policy.max_tool_calls is not None and len(tool_names) > policy.max_tool_calls:
        findings.append(
            PolicyFinding(
                rule="max_tool_calls",
                message=(
                    f"tool call count {len(tool_names)} exceeds limit {policy.max_tool_calls}"
                ),
            )
        )
    for required_tool in sorted(required - set(tool_names)):
        findings.append(
            PolicyFinding(
                rule="require_tools",
                message=f"required tool '{required_tool}' was not called",
            )
        )
    for sequence, status, call_id in response_statuses:
        if status in denied_statuses:
            findings.append(
                PolicyFinding(
                    rule="deny_statuses",
                    message=f"response status '{status}' is denied by policy",
                    sequence=sequence,
                    call_id=call_id,
                )
            )
    if policy.max_cost is not None and total_cost > policy.max_cost:
        findings.append(
            PolicyFinding(
                rule="max_cost",
                message=f"total cost {total_cost:.4f} exceeds limit {policy.max_cost:.4f}",
            )
        )

    if policy.max_total_tokens is not None and total_tokens > policy.max_total_tokens:
        findings.append(
            PolicyFinding(
                rule="max_total_tokens",
                message=f"total tokens {total_tokens} exceeds limit {policy.max_total_tokens}",
            )
        )

    return PolicyReport(
        passed=not findings,
        findings=findings,
        tool_call_count=len(tool_names),
        total_cost=total_cost,
        total_tokens=total_tokens,
    )
