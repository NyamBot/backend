from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from app.core.config import settings


logger = logging.getLogger(__name__)


class ChatMessageQueue:
    task_type = "chat_message.save"

    @property
    def configured(self) -> bool:
        return (
            settings.chat_message_queue_enabled
            and bool(settings.rabbitmq_host)
            and bool(settings.rabbitmq_username)
            and bool(settings.rabbitmq_password)
        )

    def publish_save_message(
        self,
        session_id: str,
        user_id: str | None,
        role: str,
        content: str,
        retrieved_context: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if not self.configured:
            return False

        payload = {
            "task": self.task_type,
            "version": 1,
            "message": {
                "session_id": session_id,
                "user_id": user_id,
                "role": role,
                "content": content,
                "retrieved_context": retrieved_context,
                "metadata": metadata or {},
            },
        }
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        connection = self._open_connection()
        try:
            channel = connection.channel()
            self._declare_queue(channel)
            channel.basic_publish(
                exchange="",
                routing_key=settings.chat_message_queue_name,
                body=body,
                properties=self._basic_properties(),
            )
        finally:
            connection.close()
        return True

    def consume_forever(self, handler: Callable[[dict[str, Any]], None]) -> None:
        if not self.configured:
            logger.warning("Chat message queue is disabled or missing RabbitMQ credentials.")
            while True:
                time.sleep(3600)

        while True:
            try:
                connection = self._open_connection()
                channel = connection.channel()
                self._declare_queue(channel)
                channel.basic_qos(prefetch_count=1)

                def callback(ch: Any, method: Any, properties: Any, body: bytes) -> None:
                    try:
                        payload = json.loads(body.decode("utf-8"))
                        handler(payload)
                    except Exception:
                        logger.exception("Failed to process chat message job")
                        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
                        time.sleep(settings.rabbitmq_retry_delay_seconds)
                        return
                    ch.basic_ack(delivery_tag=method.delivery_tag)

                channel.basic_consume(
                    queue=settings.chat_message_queue_name,
                    on_message_callback=callback,
                )
                logger.info("Consuming chat message jobs from %s", settings.chat_message_queue_name)
                channel.start_consuming()
            except Exception:
                logger.exception("RabbitMQ consumer failed; reconnecting")
                time.sleep(settings.rabbitmq_retry_delay_seconds)

    def _open_connection(self):
        try:
            import pika
        except ImportError as error:
            raise RuntimeError("pika is not installed") from error

        credentials = pika.PlainCredentials(settings.rabbitmq_username, settings.rabbitmq_password)
        parameters = pika.ConnectionParameters(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            virtual_host=settings.rabbitmq_vhost,
            credentials=credentials,
            heartbeat=30,
            blocked_connection_timeout=5,
            connection_attempts=3,
            retry_delay=1,
        )
        return pika.BlockingConnection(parameters)

    def _declare_queue(self, channel: Any) -> None:
        channel.queue_declare(queue=settings.chat_message_queue_name, durable=True)

    def _basic_properties(self):
        try:
            import pika
        except ImportError as error:
            raise RuntimeError("pika is not installed") from error

        return pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,
            type=self.task_type,
        )


chat_message_queue = ChatMessageQueue()
