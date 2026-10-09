"""Deterministic Mock Vision Adapter for testing.

RULES:
1. Marked with IS_MOCK = True.
2. The evaluation harness must NEVER run with this adapter and explicitly refuses to run with it.
3. Allows precise testing of timeouts, provider errors, and call count assertions (proving 1 call per unit).
"""

from __future__ import annotations
from typing import List, Optional, Tuple
from agent.models.base import (
    VisionModelAdapter,
    ModelObservation,
    ObservedItem,
    ImageQuality,
    ModelTimeoutError,
    ModelProviderError,
)


class MockVisionAdapter(VisionModelAdapter):
    """Deterministic mock adapter for pipeline unit tests and fixture testing."""
    IS_MOCK: bool = True  # Evaluation harness checks this flag!

    def __init__(
        self,
        default_observation: Optional[ModelObservation] = None,
        simulate_timeout: bool = False,
        simulate_error: bool = False,
        simulated_latency_ms: int = 65
    ):
        self.default_observation = default_observation
        self.simulate_timeout = simulate_timeout
        self.simulate_error = simulate_error
        self.simulated_latency_ms = simulated_latency_ms
        self.call_count: int = 0
        self.last_ordered_item_names: List[str] = []
        self.last_candidate_skus: List[str] = []

    def set_observation(self, observation: ModelObservation) -> None:
        """Sets the observation to be returned on next call."""
        self.default_observation = observation

    def analyze_box(
        self,
        image_bytes: bytes | List[bytes],
        ordered_item_names: List[str],
        timeout_seconds: Optional[float] = None
    ) -> Tuple[ModelObservation, int]:
        """Simulates analyzing an open box."""
        self.call_count += 1
        self.last_ordered_item_names = list(ordered_item_names)
        self.last_candidate_skus = list(ordered_item_names)

        if self.simulate_timeout:
            raise ModelTimeoutError("Simulated model timeout (exceeded timeout budget)")

        if self.simulate_error:
            raise ModelProviderError("Simulated 500 provider error")

        if self.default_observation is not None:
            return self.default_observation.model_copy(deep=True), self.simulated_latency_ms

        # Fallback default observation: reports first ordered item as visible
        items = []
        if ordered_item_names:
            items.append(
                ObservedItem(
                    label=ordered_item_names[0],
                    visible_attributes="Standard packaging",
                    count=1,
                    count_confidence=0.95,
                    identity_confidence=0.98,
                    partially_occluded=False,
                    bbox=[100.0, 100.0, 400.0, 400.0],
                    matches_order_index=0
                )
            )

        observation = ModelObservation(
            observed_items=items,
            unrecognised_items=[],
            image_quality=ImageQuality(usable=True, issues=[]),
            occlusion_suspected=False,
            notes="Default mock observation"
        )
        return observation, self.simulated_latency_ms
