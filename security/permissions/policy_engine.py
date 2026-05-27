"""ZenOS Policy Engine - 策略引擎

RBAC + 工具权限控制 + Human Approval
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class PermissionLevel(int, Enum):
    ALLOW = 0      # 自动允许
    LOG = 1        # 允许但记录
    REQUIRE_APPROVAL = 2  # 需要人工审批
    DENY = 3       # 禁止


# Default tool permission levels
DEFAULT_TOOL_PERMISSIONS: dict[str, PermissionLevel] = {
    # Safe tools
    "read_file": PermissionLevel.ALLOW,
    "list_files": PermissionLevel.ALLOW,
    "search": PermissionLevel.ALLOW,
    "git_status": PermissionLevel.ALLOW,
    "git_log": PermissionLevel.ALLOW,
    "docker_ps": PermissionLevel.ALLOW,
    "get_metrics": PermissionLevel.ALLOW,

    # Moderate tools (logged)
    "write_file": PermissionLevel.LOG,
    "git_commit": PermissionLevel.LOG,
    "git_push": PermissionLevel.LOG,
    "docker_exec": PermissionLevel.LOG,
    "ssh_exec": PermissionLevel.LOG,
    "http_request": PermissionLevel.LOG,

    # Dangerous tools (require approval)
    "rm_file": PermissionLevel.REQUIRE_APPROVAL,
    "systemctl": PermissionLevel.REQUIRE_APPROVAL,
    "iptables": PermissionLevel.REQUIRE_APPROVAL,
    "dd": PermissionLevel.REQUIRE_APPROVAL,
    "docker_rm": PermissionLevel.REQUIRE_APPROVAL,
    "reboot": PermissionLevel.REQUIRE_APPROVAL,

    # Denied
    "rm_rf_root": PermissionLevel.DENY,
    "format_disk": PermissionLevel.DENY,
}


@dataclass
class PolicyDecision:
    """策略决策"""
    tool_name: str
    allowed: bool
    level: PermissionLevel
    reason: str
    requires_approval: bool = False
    approver: str | None = None


class PolicyEngine:
    """策略引擎"""

    def __init__(
        self,
        tool_permissions: dict[str, PermissionLevel] | None = None,
        approvers: list[str] | None = None,
    ):
        self._permissions = tool_permissions or DEFAULT_TOOL_PERMISSIONS
        self._approvers = approvers or []
        self._pending_approvals: dict[str, dict[str, Any]] = {}
        self._audit_log: list[dict[str, Any]] = []

    def check_permission(self, tool_name: str, context: dict[str, Any] | None = None) -> PolicyDecision:
        """检查工具权限"""
        level = self._permissions.get(tool_name, PermissionLevel.REQUIRE_APPROVAL)

        decision = PolicyDecision(
            tool_name=tool_name,
            allowed=level < PermissionLevel.DENY,
            level=level,
            reason=f"Permission level: {level.name}",
            requires_approval=level == PermissionLevel.REQUIRE_APPROVAL,
        )

        # Audit log
        self._audit_log.append({
            "tool_name": tool_name,
            "decision": decision.allowed,
            "level": level.name,
            "context": context,
        })

        return decision

    def request_approval(self, tool_name: str, params: dict[str, Any], requester: str) -> str:
        """请求人工审批"""
        approval_id = f"approval_{len(self._pending_approvals)}"
        self._pending_approvals[approval_id] = {
            "tool_name": tool_name,
            "params": params,
            "requester": requester,
            "status": "pending",
        }
        return approval_id

    def approve(self, approval_id: str, approver: str) -> bool:
        """批准"""
        if approval_id in self._pending_approvals:
            self._pending_approvals[approval_id]["status"] = "approved"
            self._pending_approvals[approval_id]["approver"] = approver
            return True
        return False

    def deny(self, approval_id: str, approver: str) -> bool:
        """拒绝"""
        if approval_id in self._pending_approvals:
            self._pending_approvals[approval_id]["status"] = "denied"
            self._pending_approvals[approval_id]["approver"] = approver
            return True
        return False

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_log[-limit:]


class ToolGuard:
    """工具守卫：在执行前检查权限"""

    def __init__(self, policy: PolicyEngine):
        self.policy = policy

    def guard(self, tool_name: str, **kwargs: Any) -> tuple[bool, str]:
        """返回 (allowed, reason)"""
        decision = self.policy.check_permission(tool_name, kwargs)

        if decision.level == PermissionLevel.DENY:
            return False, f"Tool '{tool_name}' is denied by policy"

        if decision.requires_approval:
            approval_id = self.policy.request_approval(tool_name, kwargs, "orchestrator")
            return False, f"Tool '{tool_name}' requires approval. ID: {approval_id}"

        return True, "OK"
