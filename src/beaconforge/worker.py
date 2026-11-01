import logging
import time
from typing import Any

from celery import Celery
from celery.exceptions import Reject
from kombu import Exchange, Queue

from beaconforge.config import Settings
from beaconforge.database import Database
from beaconforge.outbox import dispatch
from beaconforge.services import dead_letter, process

settings = Settings()
celery = Celery("beaconforge", broker=settings.broker_url.get_secret_value())
dead_exchange = Exchange("beaconforge.dead", type="direct", durable=True)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_timeout=3,
    broker_transport_options={"confirm_publish": True},
    task_default_queue="beaconforge.events",
    task_queues=(
        Queue(
            "beaconforge.events",
            durable=True,
            queue_arguments={
                "x-dead-letter-exchange": "beaconforge.dead",
                "x-dead-letter-routing-key": "dead",
            },
        ),
        Queue("beaconforge.dead", exchange=dead_exchange, routing_key="dead", durable=True),
    ),
)


class CeleryPublisher:
    def publish(self, event_id: str, revision: int, purpose: str) -> None:
        task = "beaconforge.process" if purpose == "process" else "beaconforge.dead_letter"
        arguments: dict[str, Any] = {"queue": "beaconforge.events", "retry": False}
        if purpose == "dead":
            arguments.update(
                queue="beaconforge.dead", exchange="beaconforge.dead", routing_key="dead"
            )
        celery.send_task(task, args=[event_id, revision], **arguments)


@celery.task(bind=True, name="beaconforge.process", max_retries=3)
def process_event(task: Any, event_id: str, revision: int) -> None:
    database = Database(settings.database_url.get_secret_value())
    try:
        process(database, event_id, revision)
    except Exception as error:
        if task.request.retries < settings.retry_limit:
            raise task.retry(exc=error, countdown=2**task.request.retries) from error
        try:
            dead_letter(database, event_id, "processing_failed", revision)
        except Exception:
            raise Reject("database unavailable after bounded retries", requeue=False) from None
    finally:
        database.engine.dispose()


def run_outbox() -> None:
    database = Database(settings.database_url.get_secret_value())
    publisher = CeleryPublisher()
    while True:
        try:
            dispatch(database, publisher, settings.batch_size, settings.retry_limit)
        except Exception:
            logging.getLogger(__name__).warning("Outbox batch unavailable; retrying")
        time.sleep(1)


def synchronize_dead_letters(limit: int = 100) -> int:
    database = Database(settings.database_url.get_secret_value())
    count = 0
    with celery.connection_for_read() as connection:
        queue = connection.SimpleQueue(
            "beaconforge.dead", queue_opts={"durable": True}, exchange_opts={"durable": True}
        )
        while count < limit:
            try:
                message = queue.get(block=False)
            except queue.Empty:
                break
            try:
                args = message.payload[0]
                dead_letter(database, str(args[0]), "processing_failed", int(args[1]))
                message.ack()
            except Exception:
                message.reject(requeue=True)
                raise
            count += 1
        queue.close()
    database.engine.dispose()
    return count


if __name__ == "__main__":
    run_outbox()
