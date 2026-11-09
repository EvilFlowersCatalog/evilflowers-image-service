"""The task name, queue and worker settings are a contract with the analyzer and the catalog's routing."""

import inspect

from evilflowers_image import tasks
from evilflowers_image.settings import Settings
from evilflowers_image.worker import app, create_app


def test_the_figures_task_is_registered_under_its_contract_name():
    app.loader.import_default_modules()
    assert "evilflowers_image.figures" in app.tasks
    assert app.tasks["evilflowers_image.figures"].acks_late


def test_the_task_accepts_the_analyzer_kwargs_and_more():
    parameters = inspect.signature(tasks.figures.run).parameters
    assert list(parameters)[:4] == ["run_id", "source", "output_dir", "regions"]
    assert any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())


def test_queue_routing_and_late_acknowledgement():
    conf = create_app(Settings(_env_file=None)).conf
    assert conf.task_default_queue == "evilflowers_image"
    assert conf.task_routes == {"evilflowers_image.*": {"queue": "evilflowers_image"}}
    assert conf.task_acks_late and conf.task_reject_on_worker_lost
    assert conf.worker_prefetch_multiplier == 1


def test_settings_keep_the_deployed_variable_names(monkeypatch):
    for name, value in {
        "IMAGE_QUEUE": "custom_queue",
        "REDIS_URL": "redis://elsewhere:6379/1",
        "CAPTIONS_ENABLED": "1",
        "MIN_SIDE_PX": "100",
        "CATALOG_API_KEY": "key",
    }.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert settings.queue == "custom_queue"
    assert settings.redis_url == "redis://elsewhere:6379/1"
    assert settings.captions_enabled is True
    assert settings.min_side_px == 100
    assert settings.catalog_api_key.get_secret_value() == "key"
