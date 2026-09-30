"""Base domain models and abstract interface for vision model adapters.

Follows context.md Section 4 contract:
- One model call per unit
- Strict schema with confidences in [0, 1], count >= 0, bbox exactly 4 values
- SKUs outside candidate set are demoted to unrecognised_items
- Bounding boxes are evidence only, never used in verdict decisions
- Mock adapters are strictly forbidden in evaluation harness
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class ModelError(Exception):
    """Base exception for model adapter errors."""
    pass


class ModelTimeoutError(ModelError):
    """Raised when the model call exceeds its total timeout budget."""
    pass


class ModelProviderError(ModelError):
    """Raised when the model provider returns an unrecoverable HTTP/API error."""
    pass


class ModelParsingError(ModelError):
    """Raised when model response cannot be parsed into valid schema."""
    pass


class ObservedItem(BaseModel):
    sku: str
    count: int = Field(ge=0, description="Count of visible units of this SKU")
    count_confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the count assessment [0, 1]")
    identity_confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the SKU identity [0, 1]")
    partially_occluded: bool = Field(default=False, description="Whether this SKU is partially occluded")
    bbox: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0], description="[ymin, xmin, ymax, xmax]")

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: List[float]) -> List[float]:
        if len(v) != 4:
            raise ValueError(f"bbox must contain exactly 4 values [ymin, xmin, ymax, xmax], got {len(v)}")
        return v


class UnrecognisedItem(BaseModel):
    description: str
    bbox: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, v: List[float]) -> List[float]:
        if len(v) != 4:
            raise ValueError(f"bbox must contain exactly 4 values [ymin, xmin, ymax, xmax], got {len(v)}")
        return v


class ImageQuality(BaseModel):
    usable: bool = Field(description="True if image is usable for packing verification")
    issues: List[str] = Field(default_factory=list, description="Issues like blur, glare, box_not_in_frame, dark")


class ModelObservation(BaseModel):
    observed_items: List[ObservedItem] = Field(default_factory=list)
    unrecognised_items: List[UnrecognisedItem] = Field(default_factory=list)
    image_quality: ImageQuality
    occlusion_suspected: bool = Field(default=False)
    notes: Optional[str] = Field(default="")

    def demote_unexpected_skus(self, candidate_skus: List[str]) -> None:
        """Demotes any observed item whose SKU is outside candidate_skus to unrecognised_items.
        
        Enforces Rule 4 requirement: The model must discriminate among candidate SKUs.
        Any hallucinated or non-candidate SKU is treated as unrecognised.
        """
        valid_candidates = set(candidate_skus)
        remaining_observed: List[ObservedItem] = []
        for item in self.observed_items:
            if item.sku in valid_candidates:
                remaining_observed.append(item)
            else:
                self.unrecognised_items.append(
                    UnrecognisedItem(
                        description=f"Non-candidate item reported as '{item.sku}' (count: {item.count})",
                        bbox=item.bbox
                    )
                )
        self.observed_items = remaining_observed


class VisionModelAdapter(ABC):
    """Abstract base class for vision model providers."""
    IS_MOCK: bool = False

    @abstractmethod
    def analyze_box(
        self,
        image_bytes: bytes,
        candidate_skus: List[str],
        timeout_seconds: Optional[float] = None
    ) -> tuple[ModelObservation, int]:
        """Analyzes an open box image against candidate SKUs.
        
        CRITICAL RULES:
        1. Only candidate SKUs are sent (order SKUs + decoys). NO order quantities are sent!
        2. Exactly ONE model call is made per unit.
        
        Returns:
            tuple[ModelObservation, int]: (parsed observation, model latency in milliseconds)
        """
        pass


def validate_eval_adapter(adapter: VisionModelAdapter) -> None:
    """Guards the evaluation harness against running with mock adapters.
    
    Hard Rule: Mock adapter must NEVER be used for eval numbers.
    """
    if getattr(adapter, "IS_MOCK", False):
        raise ValueError(
            "Evaluation harness strictly refuses to run with mock adapter. "
            "Evaluation must be performed using a real vision model adapter."
        )
