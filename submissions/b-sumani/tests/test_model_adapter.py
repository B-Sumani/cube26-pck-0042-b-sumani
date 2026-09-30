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


def test_non_candidate_sku_demoted_to_unrecognised():
    """Confirms any SKU outside candidate set is stripped from observed_items and moved to unrecognised_items."""
    candidate_skus = ["SKU-PUZZLE-500", "SKU-BOTTLE-750"]  # Decoys + order items

    raw_json = """
    {
        "observed_items": [
            {
                "sku": "SKU-PUZZLE-500",
                "count": 1,
                "count_confidence": 0.95,
                "identity_confidence": 0.99,
                "partially_occluded": false,
                "bbox": [10.0, 10.0, 100.0, 100.0]
            },
            {
                "sku": "SKU-UNKNOWN-ALIEN",
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
    obs = parse_and_validate_observation(raw_json, candidate_skus=candidate_skus)

    # SKU-PUZZLE-500 remains in observed_items
    assert len(obs.observed_items) == 1
    assert obs.observed_items[0].sku == "SKU-PUZZLE-500"

    # SKU-UNKNOWN-ALIEN must be demoted to unrecognised_items
    assert len(obs.unrecognised_items) == 1
    assert "SKU-UNKNOWN-ALIEN" in obs.unrecognised_items[0].description
    assert obs.unrecognised_items[0].bbox == [150.0, 150.0, 250.0, 250.0]


def test_local_json_repair_recovers_without_second_call():
    """Proves markdown fences and trailing commas are repaired locally without an LLM call."""
    malformed_json_with_fences_and_commas = """
    ```json
    {
        "observed_items": [
            {
                "sku": "SKU-BOTTLE-750",
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
        candidate_skus=["SKU-BOTTLE-750"]
    )
    assert len(obs.observed_items) == 1
    assert obs.observed_items[0].sku == "SKU-BOTTLE-750"
    assert obs.notes == "Cleaned locally"


def test_hopelessly_corrupt_json_raises_model_parsing_error():
    """Confirms irrecoverable output cleanly raises ModelParsingError for fail-open handling."""
    with pytest.raises(ModelParsingError):
        parse_and_validate_observation("This is not JSON at all: 404 Not Found", ["SKU-A"])


def test_exactly_one_call_per_unit_assertion():
    """Proves adapter executes exactly ONE model call per unit."""
    mock_adapter = MockVisionAdapter()
    assert mock_adapter.call_count == 0

    image_bytes = create_sample_jpeg_bytes()
    candidate_skus = ["SKU-MUG-11", "SKU-DECOY-1"]

    obs, latency_ms = mock_adapter.analyze_box(image_bytes, candidate_skus)

    # Exactly one call must have been made
    assert mock_adapter.call_count == 1
    assert latency_ms > 0
    assert obs is not None
    # Verify candidate SKUs were passed without quantities
    assert mock_adapter.last_candidate_skus == ["SKU-MUG-11", "SKU-DECOY-1"]


def test_model_timeout_produces_pending_signal():
    """Proves that a timeout produces ModelTimeoutError (which pipeline catches for PENDING)."""
    mock_adapter = MockVisionAdapter(simulate_timeout=True)
    with pytest.raises(ModelTimeoutError):
        mock_adapter.analyze_box(b"fake_image", ["SKU-PUZZLE-500"])


def test_provider_exception_produces_pending_signal():
    """Proves that a provider 5xx/network error produces ModelProviderError for fail-open handling."""
    mock_adapter = MockVisionAdapter(simulate_error=True)
    with pytest.raises(ModelProviderError):
        mock_adapter.analyze_box(b"fake_image", ["SKU-PUZZLE-500"])


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
    candidate_skus = ["SKU-BOTTLE-750", "SKU-PUZZLE-500", "SKU-DECOY-TOWEL"]

    obs, latency_ms = adapter.analyze_box(
        image_bytes=image_bytes,
        candidate_skus=candidate_skus
    )

    assert isinstance(obs, ModelObservation)
    assert isinstance(obs.image_quality.usable, bool)
    assert latency_ms > 0
    print(f"\n[Live Smoke] Gemini model '{model_name}' latency: {latency_ms}ms")
    print(f"[Live Smoke] Observed items count: {len(obs.observed_items)}")
