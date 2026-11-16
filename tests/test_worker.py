"""The task names, queues and worker settings are a contract with the analyzer, the digitalizer and the catalog's
routing."""

import pytest
from evilflowers_worker.judges import Judges
from evilflowers_worker.runtime import create_app
from evilflowers_worker.settings import VISIBILITY_TIMEOUT

from evilflowers_image.settings import Settings
from evilflowers_image.worker import app


@pytest.mark.parametrize("name", ["evilflowers_image.figures", "evilflowers_image.standalone.figures"])
def test_the_figures_tasks_are_registered_under_their_contract_names(name):
    app.loader.import_default_modules()
    task = app.tasks[name]
    assert task.acks_late and task.reject_on_worker_lost


def test_the_standalone_worker_consumes_both_standalone_queues_interactive_first(monkeypatch):
    monkeypatch.setenv("IMAGE_STANDALONE", "1")
    settings = Settings(_env_file=None)
    assert settings.catalog_api_key is None
    assert settings.queues() == ["evilflowers_image.standalone.interactive", "evilflowers_image.standalone"]
    conf = create_app(
        "image",
        settings,
        include=["evilflowers_image.tasks"],
        queues=settings.queues(),
        routes={"evilflowers_image.standalone.*": settings.standalone_queue},
    ).conf
    assert [queue.name for queue in conf.task_queues] == settings.queues()
    assert conf.task_routes == {"evilflowers_image.standalone.*": {"queue": "evilflowers_image.standalone"}}


def test_the_decider_reads_the_variables_the_cluster_sets(monkeypatch):
    for name, value in {
        "DECIDER_ENABLED": "true",
        "DECIDER_VISION_URL": "http://decider-vision.shared.svc.cluster.local",
        "DECIDER_TIMEOUT": "30",
        "JUDGE_THRESHOLDS": '{"figure_kind": {"keep": 0.8, "hide": 0.9}}',
        "REPEAT_MIN_PAGES": "4",
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.judges_enabled and settings.decider_timeout == 30
    assert settings.judge_thresholds["figure_kind"].hide == 0.9
    assert settings.repeat_min_pages == 4
    vision = Judges.from_settings(settings).decider_vision
    assert vision is not None and vision.url == "http://decider-vision.shared.svc.cluster.local"


def test_decider_variables_left_empty_mean_off(monkeypatch):
    for name in ("DECIDER_ENABLED", "DECIDER_VISION_URL", "JUDGE_THRESHOLDS"):
        monkeypatch.setenv(name, "")
    settings = Settings(_env_file=None)
    assert not settings.judges_enabled and Judges.from_settings(settings).decider_vision is None


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
