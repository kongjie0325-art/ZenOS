"""Message broker implementing a publish/subscribe pattern with topics."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# A subscriber callback receives (topic: str, message: Any) -> None
Subscriber = Callable[[str, Any], None]


@dataclass
class _Subscription:
    """Internal representation of a topic subscription."""

    id: str
    callback: Subscriber
    filter_fn: Callable[[Any], bool] | None = None


@dataclass
class BrokerStats:
    """Message broker performance statistics.

    Attributes:
        topics: Number of active topics.
        total_subscriptions: Total number of subscriptions across all topics.
        messages_published: Total messages published.
        messages_delivered: Total messages delivered to subscribers.
    """

    topics: int = 0
    total_subscriptions: int = 0
    messages_published: int = 0
    messages_delivered: int = 0


class MessageBroker:
    """In-memory pub/sub message broker with topic-based routing.

    Supports multiple subscribers per topic, optional message filtering,
    and synchronous delivery. Thread-safe for concurrent publish/subscribe.

    Example::

        broker = MessageBroker()

        def on_event(topic: str, msg: Any) -> None:
            print(f"[{topic}] {msg}")

        sub_id = broker.subscribe("orders", on_event)
        broker.publish("orders", {"item": "widget", "qty": 3})
        broker.unsubscribe(sub_id)
    """

    def __init__(self) -> None:
        self._topics: dict[str, list[_Subscription]] = {}
        self._subscriptions: dict[str, _Subscription] = {}
        self._lock = threading.RLock()
        self._stats = BrokerStats()

    # ------------------------------------------------------------------ #
    #  Topic management
    # ------------------------------------------------------------------ #

    def create_topic(self, topic: str) -> bool:
        """Create a new topic.

        Args:
            topic: Topic name.

        Returns:
            True if the topic was created, False if it already exists.
        """
        with self._lock:
            if topic in self._topics:
                return False
            self._topics[topic] = []
            self._stats.topics += 1
            logger.debug("Created topic %s", topic)
            return True

    def delete_topic(self, topic: str, *, force: bool = False) -> bool:
        """Delete a topic and all its subscriptions.

        Args:
            topic: Topic name.
            force: If True, delete even when subscribers exist.

        Returns:
            True if the topic was deleted, False if it didn't exist.

        Raises:
            ValueError: If the topic has subscribers and ``force`` is False.
        """
        with self._lock:
            if topic not in self._topics:
                return False
            subs = self._topics[topic]
            if subs and not force:
                raise ValueError(
                    f"Topic {topic!r} has {len(subs)} subscriber(s). "
                    "Use force=True to delete anyway."
                )
            for sub in subs:
                self._subscriptions.pop(sub.id, None)
            del self._topics[topic]
            self._stats.topics -= 1
            self._stats.total_subscriptions -= len(subs)
            logger.debug("Deleted topic %s", topic)
            return True

    def list_topics(self) -> list[str]:
        """Return a list of all active topic names."""
        with self._lock:
            return list(self._topics.keys())

    # ------------------------------------------------------------------ #
    #  Subscription management
    # ------------------------------------------------------------------ #

    def subscribe(
        self,
        topic: str,
        callback: Subscriber,
        *,
        filter_fn: Callable[[Any], bool] | None = None,
    ) -> str:
        """Subscribe to a topic.

        If the topic does not exist, it is created automatically.

        Args:
            topic: Topic name to subscribe to.
            callback: Function called with ``(topic, message)`` on each
                published message.
            filter_fn: Optional predicate. Only messages for which
                ``filter_fn(message)`` returns True are delivered.

        Returns:
            A unique subscription identifier that can be passed to
            ``unsubscribe()``.
        """
        sub_id = str(uuid.uuid4())
        subscription = _Subscription(
            id=sub_id, callback=callback, filter_fn=filter_fn
        )
        with self._lock:
            if topic not in self._topics:
                self._topics[topic] = []
                self._stats.topics += 1
            self._topics[topic].append(subscription)
            self._subscriptions[sub_id] = subscription
            self._stats.total_subscriptions += 1
        logger.debug("Subscription %s added to topic %s", sub_id, topic)
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription.

        Args:
            subscription_id: The ID returned by ``subscribe()``.

        Returns:
            True if the subscription was found and removed.
        """
        with self._lock:
            sub = self._subscriptions.pop(subscription_id, None)
            if sub is None:
                return False
            # Remove from all topics (it should only be in one)
            for topic, subs in self._topics.items():
                if sub in subs:
                    subs.remove(sub)
                    break
            self._stats.total_subscriptions -= 1
        logger.debug("Removed subscription %s", subscription_id)
        return True

    def get_subscribers(self, topic: str) -> int:
        """Return the number of subscribers for a topic."""
        with self._lock:
            return len(self._topics.get(topic, []))

    # ------------------------------------------------------------------ #
    #  Publishing
    # ------------------------------------------------------------------ #

    def publish(self, topic: str, message: Any) -> int:
        """Publish a message to all subscribers of a topic.

        Args:
            topic: Target topic.
            message: The message payload.

        Returns:
            Number of subscribers the message was delivered to.
        """
        with self._lock:
            subs = list(self._topics.get(topic, []))
            self._stats.messages_published += 1

        delivered = 0
        for sub in subs:
            try:
                if sub.filter_fn is not None and not sub.filter_fn(message):
                    continue
                sub.callback(topic, message)
                delivered += 1
            except Exception:
                logger.exception(
                    "Subscriber %s on topic %s raised an error",
                    sub.id,
                    topic,
                )

        with self._lock:
            self._stats.messages_delivered += delivered

        logger.debug(
            "Published to topic %s: delivered to %d/%d subscribers",
            topic,
            delivered,
            len(subs),
        )
        return delivered

    # ------------------------------------------------------------------ #
    #  Statistics
    # ------------------------------------------------------------------ #

    def get_stats(self) -> BrokerStats:
        """Return current broker statistics."""
        with self._lock:
            return BrokerStats(
                topics=len(self._topics),
                total_subscriptions=self._stats.total_subscriptions,
                messages_published=self._stats.messages_published,
                messages_delivered=self._stats.messages_delivered,
            )
