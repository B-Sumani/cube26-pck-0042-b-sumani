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
    num_ordered_items: int | List[Any] = 0
) -> ModelObservation:
    """Parses raw model output string into validated ModelObservation.
    
    Tries direct JSON parse; if that fails, performs deterministic local string repair.
    Coerces out-of-range matches_order_index to None.
    """
    if not raw_text or not raw_text.strip():
        raise ModelParsingError("Model returned empty or whitespace-only response")

    if isinstance(num_ordered_items, list):
        max_idx = len(num_ordered_items)
    else:
        max_idx = int(num_ordered_items)

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

    # Sanitize observed_items: sanitize bbox and bounds-check matches_order_index
    if isinstance(data, dict):
        obs_items = data.get("observed_items")
        if isinstance(obs_items, list):
            for item in obs_items:
                if isinstance(item, dict):
                    # Out of range matches_order_index becomes null
                    idx = item.get("matches_order_index")
                    if idx is not None:
                        if not isinstance(idx, int) or isinstance(idx, bool) or idx < 0 or idx >= max_idx:
                            item["matches_order_index"] = None

                    # Sanitize bbox to exactly 4 numbers
                    if "bbox" in item:
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
                                item["bbox"] = [0.0, 0.0, 1000.0, 1000.0]

        unrec_items = data.get("unrecognised_items")
        if isinstance(unrec_items, list):
            for item in unrec_items:
                if isinstance(item, dict) and "bbox" in item:
                    bbox = item.get("bbox")
                    if isinstance(bbox, list) and len(bbox) != 4:
                        if len(bbox) > 4:
                            item["bbox"] = bbox[:4]
                        else:
                            item["bbox"] = [0.0, 0.0, 1000.0, 1000.0]

    # Validate against Pydantic schema
    try:
        observation = ModelObservation.model_validate(data)
    except ValidationError as err:
        raise ModelParsingError(f"Model output failed schema validation: {err}") from err

    return observation
