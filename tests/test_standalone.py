"""``evilflowers_image.standalone.figures`` in process (#7): leaves in, crops + ``figures.json`` + outcome out."""

import json

import pytest
from evilflowers_worker.testing import assert_outcome
from PIL import Image
from pydantic import ValidationError

from conftest import CHART_BOX, LOGO_BOX, FakeDecider, judges, write_leaf
from evilflowers_image.standalone import StandaloneFigures, StandaloneFiguresJob

ITEM = "digitized/book-1"
OUT = f"{ITEM}/_studio/jobs/figures-0001-a1"
OUTCOME = f"{OUT}/outcome.json"


def bbox(box: dict) -> list[float]:
    return [box["x0"], box["y0"], box["x1"], box["y1"]]


@pytest.fixture
def leaves(settings) -> list[dict]:
    """Three 300-dpi leaves with the same logo and their own chart."""
    found = []
    for number in (1, 2, 3):
        image = f"{ITEM}/leaves/{number:04d}.png"
        write_leaf(settings.storage_path / image, variant=number - 1)
        found.append({"leaf": number, "image": image})
    return found


def message(leaves, regions=None, **fields) -> dict:
    if regions is None:
        regions = []
        for leaf in leaves:
            regions += [
                {"leaf": leaf["leaf"], "kind": "picture", "seq": 0, "bbox": bbox(LOGO_BOX)},
                {"leaf": leaf["leaf"], "kind": "picture", "seq": 1, "bbox": bbox(CHART_BOX), "caption": None},
                {"leaf": leaf["leaf"], "kind": "table", "seq": 2, "bbox": bbox(CHART_BOX)},
            ]
    return {
        "run_id": "42",
        "job": "figures-0001-a1",
        "token": "secret-token",
        "leaves": leaves,
        "regions": regions,
        "output_dir": OUT,
        "outcome": OUTCOME,
        **fields,
    }


def handler(settings, decider=None) -> StandaloneFigures:
    return StandaloneFigures(settings, judges=judges(settings, decider) if decider else None)


def run(settings, kwargs, decider=None):
    return handler(settings, decider).run(StandaloneFiguresJob.model_validate(kwargs), 1)


def test_crops_then_figures_json_then_the_outcome(settings, leaves):
    decider = FakeDecider(choose=lambda _n: ("diagram", 0.9))
    assert run(settings, message(leaves), decider) == {"job": "figures-0001-a1", "figures": 6}

    outcome = assert_outcome(
        settings.storage_path, OUTCOME, run_id="42", token="secret-token", status="done", after=f"{OUT}/figures.json"
    )
    assert outcome == {
        "run_id": "42",
        "token": "secret-token",
        "status": "done",
        "job": "figures-0001-a1",
        "error": None,
        "figures": f"{OUT}/figures.json",
        "leaves": [1, 2, 3],
    }
    rows = json.loads((settings.storage_path / OUT / "figures.json").read_text())
    # The table row is not a picture; the logo on every leaf is page furniture, the charts went to the decider.
    assert [(row["leaf"], row["seq"]) for row in rows] == [(1, 0), (1, 1), (2, 0), (2, 1), (3, 0), (3, 1)]
    logo, chart = rows[0], rows[1]
    assert (logo["band"], logo["decision"]) == ("hide", "repeated") and "p" not in logo
    assert (chart["decision"], chart["p"], chart["category"]) == ("diagram", 0.9, "diagram")
    assert chart["bbox"] == pytest.approx(bbox(CHART_BOX))
    assert chart["crop"] == "p001-fig01.webp" and "image_path" not in chart and "page" not in chart
    assert all((settings.storage_path / OUT / row["crop"]).is_file() for row in rows)
    assert len(decider.calls) == 3


def test_a_300_dpi_leaf_is_cropped_at_crop_dpi_and_a_leaf_without_dpi_is_not_upsampled(settings, leaves):
    run(settings, message(leaves[:1], [{"leaf": 1, "seq": 0, "bbox": bbox(CHART_BOX)}]))
    crop = Image.open(settings.storage_path / OUT / "p001-fig00.webp")
    # 400 x 400 pt at 144 dpi.
    assert crop.size == pytest.approx((800, 800), abs=2)

    write_leaf(settings.storage_path / ITEM / "nodpi.png", variant=0, dpi=None)
    nodpi = [{"leaf": 1, "image": f"{ITEM}/nodpi.png"}]
    run(settings, message(nodpi, [{"leaf": 1, "seq": 0, "bbox": bbox(CHART_BOX)}]))
    crop = Image.open(settings.storage_path / OUT / "p001-fig00.webp")
    # The image's own pixels (PyMuPDF reads it as 96 dpi): 400 pt at 300 px per 72 pt, never 1.5 times that.
    assert crop.size == pytest.approx((1667, 1667), abs=2)


def test_inputs_alone_are_leaves_numbered_from_one(settings, leaves):
    kwargs = message(leaves[:2])
    kwargs["inputs"] = [leaf["image"] for leaf in kwargs.pop("leaves")]
    run(settings, kwargs)
    assert assert_outcome(settings.storage_path, OUTCOME, status="done")["leaves"] == [1, 2]


def test_leaves_alone_fill_the_kits_required_inputs(leaves):
    job = StandaloneFiguresJob.model_validate(message(leaves))
    assert job.inputs == [leaf["image"] for leaf in leaves]


def test_a_leaf_without_figures_is_still_reported(settings, leaves):
    assert run(settings, message(leaves, regions=[]))["figures"] == 0
    assert assert_outcome(settings.storage_path, OUTCOME, status="done")["leaves"] == [1, 2, 3]
    assert json.loads((settings.storage_path / OUT / "figures.json").read_text()) == []


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"leaves": [{"leaf": 1, "image": f"{ITEM}/leaves/missing.png"}]}, "no image"),
        ({"regions": [{"leaf": 9, "seq": 0, "bbox": [0.1, 0.1, 0.5, 0.5]}]}, "leaf 9"),
        ({"output_dir": "../elsewhere"}, "STORAGE_PATH"),
    ],
    ids=["missing leaf", "unknown leaf", "output outside the storage"],
)
def test_a_failure_writes_a_failed_outcome_and_raises(settings, leaves, change, error):
    with pytest.raises(RuntimeError, match=error):
        run(settings, message(leaves[:1]) | change)
    outcome = assert_outcome(settings.storage_path, OUTCOME, run_id="42", token="secret-token", status="failed")
    assert error in outcome["error"] and outcome["figures"] is None


def test_past_the_delivery_cap_it_fails_with_an_outcome(settings, leaves):
    job = StandaloneFiguresJob.model_validate(message(leaves))
    with pytest.raises(RuntimeError, match="gave up after 5 deliveries"):
        handler(settings).give_up(job, 6)
    assert not (settings.storage_path / OUT / "figures.json").exists()
    assert_outcome(settings.storage_path, OUTCOME, status="failed")


def test_an_invalid_message_that_names_its_outcome_fails_it(settings, leaves):
    kwargs = message(leaves, regions=[{"leaf": 1, "seq": "x", "bbox": [0, 0, 1]}])
    with pytest.raises(ValidationError) as caught:
        StandaloneFiguresJob.model_validate(kwargs)
    with pytest.raises(ValidationError):
        handler(settings).invalid(kwargs, caught.value)
    assert "regions" in assert_outcome(settings.storage_path, OUTCOME, status="failed", token="secret-token")["error"]


def test_an_invalid_message_without_a_safe_outcome_writes_nothing(settings, leaves):
    kwargs = message(leaves, outcome="../outside.json", regions="not a list")
    with pytest.raises(ValidationError) as caught:
        StandaloneFiguresJob.model_validate(kwargs)
    with pytest.raises(ValidationError):
        handler(settings).invalid(kwargs, caught.value)
    assert not (settings.storage_path.parent / "outside.json").exists()


def test_leaf_numbers_must_not_repeat(leaves):
    with pytest.raises(ValidationError, match="repeat"):
        StandaloneFiguresJob.model_validate(message([leaves[0], {**leaves[1], "leaf": 1}]))
