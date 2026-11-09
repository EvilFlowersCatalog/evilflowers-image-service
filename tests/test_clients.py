import pytest
import requests
from pydantic import SecretStr

from evilflowers_image.clients import catalog as catalog_module
from evilflowers_image.clients.catalog import CatalogClient, RunNotRunning
from evilflowers_image.clients.http import USER_AGENT, session


class Response:
    def __init__(self, status_code=200, body=b"{}"):
        self.status_code, self.content, self.text = status_code, body, body.decode()

    def json(self):
        return {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Http:
    def __init__(self, *statuses):
        self.statuses, self.posts = list(statuses), []

    def post(self, url, json, timeout):
        self.posts.append((url, json))
        return Response(self.statuses.pop(0) if self.statuses else 200)


@pytest.fixture
def client(settings, monkeypatch):
    monkeypatch.setattr(catalog_module.time, "sleep", lambda _: None)
    settings = settings.model_copy(update={"catalog_attempts": 3, "catalog_batch_size": 2})

    def make(*statuses):
        http = Http(*statuses)
        return CatalogClient("run-1", settings=settings, http=http), http

    return make


def test_regions_go_in_batches(client):
    catalog, http = client()
    catalog.regions([{"seq": number} for number in range(5)])
    assert [len(payload["regions"]) for _, payload in http.posts] == [2, 2, 1]
    assert http.posts[0][0] == "http://catalog:8000/extraction/v1/runs/run-1/regions"


def test_job_report_shape(client):
    catalog, http = client()
    catalog.job("figures", status="failed", error="x" * 5000)
    [(url, payload)] = http.posts
    assert url.endswith("/jobs/figures")
    assert payload["status"] == "failed" and payload["provenance"] == {} and len(payload["error"]) == 2000


def test_5xx_is_retried_and_409_is_not(client):
    catalog, http = client(503, 200)
    catalog.job("figures", status="done")
    assert len(http.posts) == 2

    catalog, http = client(409)
    with pytest.raises(RunNotRunning):
        catalog.job("figures", status="done")
    assert len(http.posts) == 1


def test_4xx_raises_at_once(client):
    catalog, http = client(400)
    with pytest.raises(requests.HTTPError):
        catalog.job("figures", status="done")
    assert len(http.posts) == 1


def test_session_headers():
    assert "Authorization" not in session(None).headers
    assert "Authorization" not in session(SecretStr("")).headers
    assert session(None).headers["User-Agent"] == USER_AGENT
    assert session(SecretStr("secret")).headers["Authorization"] == "Bearer secret"
