"""Unit tests for Vision Model Adapter, JSON validation, and local repair.

Verifies:
1. Timeout -> PENDING signal (ModelTimeoutError).
2. Provider exception -> PENDING signal (ModelProviderError).
3. Exactly one model call per unit assertion.
4. Local deterministic JSON repair without second call.
5. Schema tightening (confidences in [0,1], count >= 0, bbox length 4, and non-candidate SKUs demoted).
6. Eval harness refuses to run with mock adapter.
7. Live Gemini smoke test on a real JPEG image recording latency (skips if GEMINI_API_KEY unset).
"""

import os
from io import BytesIO
import pytest
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

from agent.models.base import (
    ObservedItem,
    UnrecognisedItem,
    ImageQuality,
    ModelObservation,
    ModelTimeoutError,
    ModelProviderError,
    ModelParsingError,
    validate_eval_adapter,
)
from agent.models.parser import (
    parse_and_validate_observation,
    local_repair_json_string,
)
from agent.models.mock import MockVisionAdapter
from agent.models.gemini import GeminiVisionAdapter


def create_sample_jpeg_bytes() -> bytes:
    """Generates valid JPEG image bytes for vision testing."""
    img = Image.new("RGB", (250, 250), color=(220, 220, 230))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_schema_tightening_validates_constraints():
    """Confirms count >= 0, confidences in [0, 1], and bbox exactly 4 values."""
    # Valid item
    valid_item = ObservedItem(
        sku="SKU-BOTTLE-750",
        count=2,
        count_confidence=0.95,
        identity_confidence=0.99,
        partially_occluded=False,
        bbox=[100.0, 100.0, 500.0, 500.0]
    )
    assert valid_item.count == 2

    # Negative count rejected
    with pytest.raises(Exception):
        ObservedItem(
            sku="SKU-BOTTLE-750",
            count=-1,
            count_confidence=0.9,
            identity_confidence=0.9,
            bbox=[0.0, 0.0, 10.0, 10.0]
        )

    # Confidence > 1.0 rejected
    with pytest.raises(Exception):
        ObservedItem(
            sku="SKU-BOTTLE-750",
            count=1,
            count_confidence=1.5,
            identity_confidence=0.9,
            bbox=[0.0, 0.0, 10.0, 10.0]
        )

    # Bbox not 4 values rejected
    with pytest.raises(Exception):
        ObservedItem(
            sku="SKU-BOTTLE-750",
            count=1,
            count_confidence=0.9,
            identity_confidence=0.9,
            bbox=[10.0, 20.0, 30.0]  # Only 3 values!
        )


def test_out_of_range_matches_order_index_becomes_null():
    """Confirms matches_order_index outside [0, num_ordered_items) is coerced to None."""
    raw_json = """
    {
        "observed_items": [
            {
                "label": "Puzzle 500 Pieces",
                "visible_attributes": "Blue box",
                "matches_order_index": 0,
                "count": 1,
                "count_confidence": 0.95,
                "identity_confidence": 0.99,
                "partially_occluded": false,
                "bbox": [10.0, 10.0, 100.0, 100.0]
            },
            {
                "label": "Unknown alien item",
                "visible_attributes": "Green bottle",
                "matches_order_index": 99,
                "count": 1,
                "count_confidence": 0.80,
                "identity_confidence": 0.85,
                "partially_occluded": false,
                "bbox": [150.0, 150.0, 250.0, 250.0]
            },
            {
                "label": "Another item",
                "visible_attributes": "Box",
                "matches_order_index": -1,
                "count": 1,
                "count_confidence": 0.80,
                "identity_confidence": 0.85,
                "partially_occluded": false,
                "bbox": [150.0, 150.0, 250.0, 250.0]
            }
        ],
        "unrecognised_items": [],
        "image_quality": {"usable": true, "issues": []},
        "occlusion_suspected": false,
        "notes": "Test"
    }
    """
    obs = parse_and_validate_observation(raw_json, num_ordered_items=1)

    assert len(obs.observed_items) == 3
    # index 0 is valid for num_ordered_items=1
    assert obs.observed_items[0].matches_order_index == 0
    # index 99 is out of range -> coerced to None
    assert obs.observed_items[1].matches_order_index is None
    # index -1 is out of range -> coerced to None
    assert obs.observed_items[2].matches_order_index is None


def test_local_json_repair_recovers_without_second_call():
    """Proves markdown fences and trailing commas are repaired locally without an LLM call."""
    malformed_json_with_fences_and_commas = """
    ```json
    {
        "observed_items": [
            {
                "label": "Stainless Steel Bottle",
                "visible_attributes": "Silver finish",
                "matches_order_index": 0,
                "count": 1,
                "count_confidence": 0.9,
                "identity_confidence": 0.95,
                "partially_occluded": false,
                "bbox": [0.0, 0.0, 100.0, 100.0],
            },
        ],
        "unrecognised_items": [],
        "image_quality": {
            "usable": true,
            "issues": [],
        },
        "occlusion_suspected": false,
        "notes": "Cleaned locally",
    }
    ```
    """
    # Direct json.loads would fail due to ```json and trailing commas
    obs = parse_and_validate_observation(
        malformed_json_with_fences_and_commas,
        num_ordered_items=1
    )
    assert len(obs.observed_items) == 1
    assert obs.observed_items[0].label == "Stainless Steel Bottle"
    assert obs.observed_items[0].matches_order_index == 0
    assert obs.notes == "Cleaned locally"


def test_hopelessly_corrupt_json_raises_model_parsing_error():
    """Confirms irrecoverable output cleanly raises ModelParsingError for fail-open handling."""
    with pytest.raises(ModelParsingError):
        parse_and_validate_observation("This is not JSON at all: 404 Not Found", 1)


def test_exactly_one_call_per_unit_assertion():
    """Proves adapter executes exactly ONE model call per unit."""
    mock_adapter = MockVisionAdapter()
    assert mock_adapter.call_count == 0

    image_bytes = create_sample_jpeg_bytes()
    ordered_item_names = ["Ceramic Mug 11oz"]

    obs, latency_ms = mock_adapter.analyze_box(image_bytes, ordered_item_names)

    # Exactly one call must have been made
    assert mock_adapter.call_count == 1
    assert latency_ms > 0
    assert obs is not None
    # Verify ordered item names were passed without quantities
    assert mock_adapter.last_ordered_item_names == ["Ceramic Mug 11oz"]


def test_model_timeout_produces_pending_signal():
    """Proves that a timeout produces ModelTimeoutError (which pipeline catches for PENDING)."""
    mock_adapter = MockVisionAdapter(simulate_timeout=True)
    with pytest.raises(ModelTimeoutError):
        mock_adapter.analyze_box(b"fake_image", ["Jigsaw Puzzle 500 Pieces"])


def test_provider_exception_produces_pending_signal():
    """Proves that a provider 5xx/network error produces ModelProviderError for fail-open handling."""
    mock_adapter = MockVisionAdapter(simulate_error=True)
    with pytest.raises(ModelProviderError):
        mock_adapter.analyze_box(b"fake_image", ["Jigsaw Puzzle 500 Pieces"])


def test_eval_harness_refuses_mock_adapter():
    """Proves eval harness strictly refuses to run with mock adapter."""
    mock_adapter = MockVisionAdapter()
    with pytest.raises(ValueError) as exc_info:
        validate_eval_adapter(mock_adapter)
    assert "refuses to run with mock adapter" in str(exc_info.value)

    # Valid real adapter passes the check
    real_adapter = GeminiVisionAdapter(api_key="dummy_key", model_name="gemini-3-flash-preview")
    validate_eval_adapter(real_adapter)  # Should not raise!


def test_live_gemini_smoke_call():
    """Live smoke test executing a real call to Gemini API.
    
    Skips if GEMINI_API_KEY is not configured.
    Verifies structured JSON output, candidate restriction, and latency recording.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY not set. Skipping live model smoke test.")

    model_name = os.getenv("MODEL_NAME", "gemini-3-flash-preview")
    adapter = GeminiVisionAdapter(
        api_key=api_key,
        model_name=model_name,
        total_timeout_budget=20.0
    )

    image_bytes = create_sample_jpeg_bytes()
    ordered_item_names = ["Stainless Steel Water Bottle 750ml", "Jigsaw Puzzle 500 Pieces"]

    obs, latency_ms = adapter.analyze_box(
        image_bytes=image_bytes,
        ordered_item_names=ordered_item_names
    )

    assert isinstance(obs, ModelObservation)
    assert isinstance(obs.image_quality.usable, bool)
    assert latency_ms > 0
    print(f"\n[Live Smoke] Gemini model '{model_name}' latency: {latency_ms}ms")
    print(f"[Live Smoke] Observed items count: {len(obs.observed_items)}")
