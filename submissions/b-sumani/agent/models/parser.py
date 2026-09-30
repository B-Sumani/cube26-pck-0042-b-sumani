"""JSON parsing and local string repair for model outputs.

Follows context.md Section 4:
- Validates structured JSON against ModelObservation schema.
- Performs deterministic local string repair once (strips markdown code fences, extracts JSON object, removes trailing commas).
- ZERO second model calls! No LLM repair loops.
- Demotes any SKUs not in candidate_skus to unrecognised_items.
- Raises ModelParsingError if payload cannot be parsed, signaling fail-open PENDING.
"""

from __future__ import annotations
import re
import json
from typing import List, Any, Dict
from pydantic import ValidationError
from agent.models.base import ModelObservation, ModelParsingError


def local_repair_json_string(raw: str) -> str:
    """Performs deterministic local string repairs on malformed JSON without calling an LLM."""
    cleaned = raw.strip()
    
    # 1. Strip markdown code fences if present (```json ... ``` or ``` ...)
    fence_pattern = r"^```(?:json)?\s*([\s\S]*?)\s*```$"
    match = re.search(fence_pattern, cleaned, re.MULTILINE)
    if match:
        cleaned = match.group(1).strip()
    else:
        # Fallback: find first '{' and last '}'
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start:end+1].strip()

    # 2. Remove trailing commas before closing braces/brackets
    cleaned = re.sub(r",\s*([\}\]])", r"\1", cleaned)

    return cleaned


def parse_and_validate_observation(
    raw_text: str,
    candidate_skus: List[str]
) -> ModelObservation:
    """Parses raw model output string into validated ModelObservation.
    
    Tries direct JSON parse; if that fails, performs deterministic local string repair.
    Enforces candidate SKU filtering (demoting non-candidates to unrecognised_items).
    """
    if not raw_text or not raw_text.strip():
        raise ModelParsingError("Model returned empty or whitespace-only response")

    data: Dict[str, Any] = {}
    try:
        # Attempt 1: direct parse
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        # Attempt 2: local string repair
        repaired = local_repair_json_string(raw_text)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError as err:
            raise ModelParsingError(f"Failed to parse JSON even after local repair: {err}") from err

    # Sanitize observed_items and unrecognised_items bboxes to exactly 4 coordinates
    if isinstance(data, dict):
        for key in ("observed_items", "unrecognised_items"):
            items = data.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and "bbox" in item:
                        bbox = item.get("bbox")
                        if isinstance(bbox, list) and len(bbox) != 4:
                            if len(bbox) >= 4 and len(bbox) % 4 == 0:
                                ymin = min(bbox[0::4])
                                xmin = min(bbox[1::4])
                                ymax = max(bbox[2::4])
                                xmax = max(bbox[3::4])
                                item["bbox"] = [ymin, xmin, ymax, xmax]
                            elif len(bbox) > 4:
                                item["bbox"] = bbox[:4]
                            else:
                                item["bbox"] = [0, 0, 1000, 1000]

    # Validate against Pydantic schema
    try:
        observation = ModelObservation.model_validate(data)
    except ValidationError as err:
        raise ModelParsingError(f"Model output failed schema validation: {err}") from err

    # Enforce candidate set boundary
    observation.demote_unexpected_skus(candidate_skus)

    return observation
