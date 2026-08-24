from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "smm_reseller",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.sync_services", "app.tasks.poll_orders"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "sync-panel-services": {
        "task": "app.tasks.sync_services.sync_services_task",
        "schedule": float(max(1, settings.services_sync_interval_minutes) * 60),
    },
    "poll-order-statuses": {
        "task": "app.tasks.poll_orders.poll_order_statuses_task",
        "schedule": float(settings.order_status_poll_seconds),
    },
}
