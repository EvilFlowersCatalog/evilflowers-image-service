"""The task name, queue and worker settings are a contract with the analyzer and the catalog's routing."""

from evilflowers_worker.runtime import create_app
from evilflowers_worker.settings import VISIBILITY_TIMEOUT

from evilflowers_image.settings import Settings
from evilflowers_image.worker import app


def test_the_figures_task_is_registered_under_its_contract_name():
    app.loader.import_default_modules()
    task = app.tasks["evilflowers_image.figures"]
    assert task.acks_late and task.reject_on_worker_lost


def test_queue_routing_and_delivery_semantics():
    conf = create_app("image", Settings(_env_file=None), include=["evilflowers_image.tasks"]).conf
    assert conf.task_default_queue == "evilflowers_image"
    assert conf.task_routes == {"evilflowers_image.*": {"queue": "evilflowers_image"}}
    assert conf.worker_prefetch_multiplier == 1
    assert conf.broker_transport_options == {"visibility_timeout": VISIBILITY_TIMEOUT}
    # Scale-in is the kit's (warm SIGTERM, then cancel and requeue); Celery's own soft shutdown is off.
    assert conf.worker_soft_shutdown_timeout == 0
    assert "worker_enable_soft_shutdown_on_idle" not in conf.changes


def test_settings_keep_the_deployed_variable_names(monkeypatch):
    for name, value in {
        "IMAGE_QUEUE": "custom_queue",
        "REDIS_URL": "redis://elsewhere:6379/1",
        "CAPTIONS_ENABLED": "1",
        "MIN_SIDE_PX": "100",
        "CATALOG_API_KEY": "key",
        "WORKER_SOFT_SHUTDOWN_TIMEOUT": "25",
        "MAX_DELIVERIES": "3",
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.queue == "custom_queue"
    assert settings.redis_url == "redis://elsewhere:6379/1"
    assert settings.captions_enabled is True
    assert settings.min_side_px == 100
    assert settings.catalog_api_key.get_secret_value() == "key"
    assert settings.worker_soft_shutdown_timeout == 25.0
    assert settings.max_deliveries == 3
    assert settings.broker_visibility_timeout == VISIBILITY_TIMEOUT
