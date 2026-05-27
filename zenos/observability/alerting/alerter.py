"""Alert Manager - Rule-based alerting with multiple channels."""

from __future__ import annotations

import time
import logging
import threading
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    id: str
    name: str
    condition: Callable[[Dict[str, Any]], bool]
    severity: AlertSeverity
    message_template: str
    cooldown_seconds: float = 300.0
    enabled: bool = True
    channels: List[str] = field(default_factory=lambda: ["log"])
    last_triggered: float = 0.0
    trigger_count: int = 0


@dataclass
class Alert:
    rule_id: str
    rule_name: str
    severity: AlertSeverity
    message: str
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    acknowledged: bool = False


class AlertChannel:
    """Base class for alert delivery channels."""

    def send(self, alert: Alert) -> bool:
        raise NotImplementedError


class LogAlertChannel(AlertChannel):
    def send(self, alert: Alert) -> bool:
        level = {
            AlertSeverity.INFO: logging.INFO,
            AlertSeverity.WARNING: logging.WARNING,
            AlertSeverity.ERROR: logging.ERROR,
            AlertSeverity.CRITICAL: logging.CRITICAL,
        }.get(alert.severity, logging.WARNING)
        logger.log(level, f"[ALERT:{alert.severity.value}] {alert.message}")
        return True


class WebhookAlertChannel(AlertChannel):
    def __init__(self, url: str):
        self._url = url

    def send(self, alert: Alert) -> bool:
        try:
            import urllib.request, json
            data = json.dumps({
                'severity': alert.severity.value,
                'message': alert.message,
                'timestamp': alert.timestamp,
            }).encode()
            req = urllib.request.Request(self._url, data=data,
                                          headers={'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception as e:
            logger.error(f"Webhook alert failed: {e}")
            return False


class AlertManager:
    """Rule-based alerting with cooldown and multi-channel delivery."""

    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._channels: Dict[str, AlertChannel] = {}
        self._alerts: List[Alert] = []
        self._lock = threading.Lock()
        self._max_alerts = 10000
        # Default channel
        self._channels['log'] = LogAlertChannel()

    def add_rule(self, rule: AlertRule) -> None:
        self._rules[rule.id] = rule
        logger.info(f"Added alert rule: {rule.name}")

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def add_channel(self, name: str, channel: AlertChannel) -> None:
        self._channels[name] = channel

    def evaluate(self, data: Dict[str, Any]) -> List[Alert]:
        """Evaluate all rules against the given data. Returns triggered alerts."""
        triggered = []
        now = time.time()
        with self._lock:
            for rule in self._rules.values():
                if not rule.enabled:
                    continue
                if now - rule.last_triggered < rule.cooldown_seconds:
                    continue
                try:
                    if rule.condition(data):
                        rule.last_triggered = now
                        rule.trigger_count += 1
                        alert = Alert(
                            rule_id=rule.id,
                            rule_name=rule.name,
                            severity=rule.severity,
                            message=rule.message_template.format(**data),
                            data=data,
                        )
                        self._alerts.append(alert)
                        if len(self._alerts) > self._max_alerts:
                            self._alerts = self._alerts[-self._max_alerts:]
                        triggered.append(alert)
                        self._dispatch(alert, rule.channels)
                except Exception as e:
                    logger.error(f"Alert rule evaluation error ({rule.name}): {e}")
        return triggered

    def _dispatch(self, alert: Alert, channel_names: List[str]) -> None:
        for name in channel_names:
            channel = self._channels.get(name)
            if channel:
                try:
                    channel.send(alert)
                except Exception as e:
                    logger.error(f"Alert dispatch error ({name}): {e}")

    def get_alerts(self, severity: Optional[AlertSeverity] = None,
                   limit: int = 100, include_acknowledged: bool = False) -> List[Alert]:
        alerts = self._alerts
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if not include_acknowledged:
            alerts = [a for a in alerts if not a.acknowledged]
        return alerts[-limit:]

    def acknowledge(self, index: int = -1) -> bool:
        with self._lock:
            alerts = [a for a in self._alerts if not a.acknowledged]
            if abs(index) <= len(alerts):
                alerts[index].acknowledged = True
                return True
        return False

    def get_rules(self) -> List[AlertRule]:
        return list(self._rules.values())
