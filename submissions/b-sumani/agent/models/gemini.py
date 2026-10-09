"""Google Gemini Vision Model Adapter.

Implements the single-call vision contract:
- Exactly ONE model call per unit.
- Candidate SKUs only (order SKUs + decoys). NO order quantities sent!
- Gemini structured JSON mode with response_schema.
- Transport retries: at most 2 retries for HTTP 429/5xx inside total timeout budget.
- Logs each attempt with latency and status.
- Local string repair on response; no second LLM call.
"""

from __future__ import annotations
import os
import time
import base64
import logging
from typing import List, Optional, Tuple, Dict
import httpx
from dotenv import load_dotenv

from agent.models.base import (
    VisionModelAdapter,
    ModelObservation,
    ModelTimeoutError,
    ModelProviderError,
    ModelParsingError,
    PROMPT_VERSION,
)
from agent.models.parser import parse_and_validate_observation

load_dotenv()

logger = logging.getLogger("pack_manager.gemini")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Standard Gemini response schema for structured output
GEMINI_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "notes": {"type": "STRING"},
        "observed_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "label": {"type": "STRING"},
                    "visible_attributes": {"type": "STRING"},
                    "count": {"type": "INTEGER"},
                    "count_confidence": {"type": "NUMBER"},
                    "identity_confidence": {"type": "NUMBER"},
                    "partially_occluded": {"type": "BOOLEAN"},
                    "bbox": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                    "matches_order_index": {"type": "INTEGER", "nullable": True}
                },
                "required": ["label", "visible_attributes", "count", "count_confidence", "identity_confidence", "partially_occluded", "bbox"]
            }
        },
        "image_quality": {
            "type": "OBJECT",
            "properties": {
                "usable": {"type": "BOOLEAN"},
                "issues": {"type": "ARRAY", "items": {"type": "STRING"}}
            },
            "required": ["usable", "issues"]
        },
        "occlusion_suspected": {"type": "BOOLEAN"}
    },
    "required": ["notes", "observed_items", "image_quality", "occlusion_suspected"]
}


import csv
from pathlib import Path

def load_catalogue(catalogue_csv_path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """Loads catalogue mapping: sku -> {'title': ..., 'description': ...}."""
    if catalogue_csv_path is None:
        catalogue_csv_path = Path(__file__).resolve().parents[2] / "data" / "catalogue.csv"
    if not catalogue_csv_path.exists():
        return {}
    mapping = {}
    with open(catalogue_csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sku = row.get("sku", "").strip()
            if sku:
                mapping[sku] = {
                    "title": row.get("title", "").strip(),
                    "description": row.get("description", "").strip(),
                }
    return mapping


class GeminiVisionAdapter(VisionModelAdapter):
    """Adapter for Google Gemini Vision models."""
    IS_MOCK: bool = False

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        eval_mode: bool = False,
        total_timeout_budget: float = 15.0,
        max_transport_retries: int = 2,
        catalogue: Optional[Dict[str, Dict[str, str]]] = None
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            logger.warning("GEMINI_API_KEY is not set. Live calls will fail.")

        if model_name:
            self.model_name = model_name
        elif eval_mode:
            # Use single unified evaluation model
            self.model_name = os.getenv("MODEL_NAME_EVAL", "gemini-3.1-flash-lite-preview")
        else:
            # Use single unified model
            self.model_name = os.getenv("MODEL_NAME", "gemini-3.1-flash-lite-preview")

        self.total_timeout_budget = total_timeout_budget
        self.max_transport_retries = max_transport_retries
        self.catalogue = catalogue if catalogue is not None else load_catalogue()

    def _build_prompt(self, ordered_item_names: List[str]) -> str:
        """Constructs prompt containing ordered item names (never quantities).
        
        CRITICAL: Never send order quantities or assume an ordered item is present.
        """
        items_formatted = []
        for idx, name in enumerate(ordered_item_names):
            items_formatted.append(f"[{idx}] {name}")
        ordered_items_str = "\n".join(items_formatted) if items_formatted else "(None specified)"

        return (
            "You are an expert warehouse QA inspector verifying an open shipping box before it is sealed.\n"
            "Below is the list of ordered product names for this shipment:\n"
            f"{ordered_items_str}\n\n"
            "Instructions:\n"
            "1. In the 'notes' field, list every distinct visible item you see in the box in free text first.\n"
            "2. Inspect all visible objects in the box. NEVER assume an ordered item is present simply because it is in the order list.\n"
            "3. Multiple photographs (if provided) are different angles/views of the SAME box. Count each physical object once across all views.\n"
            "4. For each distinct visible item observed in the box, output an entry in 'observed_items' with:\n"
            "   - 'label': Clear descriptive name of the item.\n"
            "   - 'visible_attributes': Distinctive visible features (color, branding, packaging, shape, markings).\n"
            "   - 'count': Number of physical units visible in the box (integer >= 0).\n"
            "   - 'count_confidence': Confidence in the visible count (0.0 to 1.0).\n"
            "   - 'identity_confidence': Confidence in the item identity (0.0 to 1.0).\n"
            "   - 'partially_occluded': true if the item is partially hidden, covered, or cut off.\n"
            "   - 'bbox': [ymin, xmin, ymax, xmax] coordinates normalized to 0-1000.\n"
            "   - 'matches_order_index': 0-based integer index of the matched ordered item above (e.g. 0 or 1), or null if the item does NOT match any item in the order list.\n"
            "     * Set matches_order_index only if the visible title, brand and product name on the item match the ordered item's name. If the item is a similar product (same author, series, brand or packaging style) but the printed title or product name is different from the ordered item, set matches_order_index to null.\n"
            "     * Use the label field to write exactly what is printed on the item (for example the exact book title), not the name of the ordered item.\n"
            "     * Do not set null for items whose printed title and brand clearly match the ordered item.\n"
            "5. Evaluate image quality in 'image_quality': set 'usable' to true/false, and list any 'issues' (blur, glare, dark, box_not_in_frame):\n"
            "   - If any ordered item, carton or box edge is clipped or cut off by the edge of the frame, set usable to false and add \"box_not_in_frame\" to issues, even if the items are still recognisable.\n"
            "   - If reflective glare covers part of a carton, label or item so that some text or surface cannot be read clearly, add \"glare\" to issues and set usable to false, even if you can still guess the item.\n"
            "   - Do not flag these for normal, well-lit photos with the whole box in frame.\n"
            "6. Set 'occlusion_suspected' to true ONLY if you can actually see something covering part of the box interior: packing paper, bubble wrap, filler, crumpled paper or cloth lying over the contents, or items stacked so that lower ones are not visible. A missing ordered item alone is NOT a reason to set occlusion_suspected.\n"
            "7. If an ordered item is not visible AND the box interior is clearly visible where it would be, it is absent: leave it out of observed_items and leave occlusion_suspected false (unless rule 6 applies elsewhere). If an ordered item is not visible AND covering material (rule 6) lies over space where it could be, leave it out of observed_items and set occlusion_suspected to true."
        )

    def analyze_box(
        self,
        image_bytes: bytes | List[bytes],
        ordered_item_names: List[str],
        timeout_seconds: Optional[float] = None
    ) -> Tuple[ModelObservation, int]:
        """Executes single vision model call with transport retries and local JSON repair."""
        if not self.api_key:
            raise ModelProviderError("GEMINI_API_KEY is not configured")

        budget = timeout_seconds or self.total_timeout_budget
        start_time = time.monotonic()

        images_list: List[bytes] = [image_bytes] if isinstance(image_bytes, bytes) else list(image_bytes)
        prompt_text = self._build_prompt(ordered_item_names)

        url = GEMINI_API_URL.format(model=self.model_name)
        url_with_key = f"{url}?key={self.api_key}"

        parts: List[Dict[str, Any]] = [{"text": prompt_text}]
        for img in images_list:
            mime_type = "image/png" if img.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg"
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(img).decode("utf-8")
                }
            })

        payload = {
            "contents": [
                {
                    "parts": parts
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
                "response_schema": GEMINI_RESPONSE_SCHEMA,
                "temperature": 0.0
            }
        }

        attempts = 0
        last_error = None

        while attempts <= self.max_transport_retries:
            elapsed = time.monotonic() - start_time
            remaining_time = budget - elapsed
            if remaining_time <= 0:
                raise ModelTimeoutError(
                    f"Model call exceeded total timeout budget of {budget:.1f}s after {attempts} attempts"
                )

            attempts += 1
            attempt_start = time.monotonic()

            try:
                logger.info(
                    f"[Attempt {attempts}/{self.max_transport_retries + 1}] Calling Gemini model '{self.model_name}', remaining timeout: {remaining_time:.2f}s"
                )
                with httpx.Client(timeout=remaining_time) as client:
                    resp = client.post(url_with_key, json=payload)
                
                attempt_latency = int((time.monotonic() - attempt_start) * 1000)
                logger.info(f"[Attempt {attempts}] HTTP status: {resp.status_code}, latency: {attempt_latency}ms")

                if resp.status_code == 200:
                    resp_json = resp.json()
                    candidates = resp_json.get("candidates", [])
                    if not candidates:
                        raise ModelProviderError("Gemini returned empty candidates list (possibly blocked by safety filter)")
                    
                    raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    total_latency_ms = int((time.monotonic() - start_time) * 1000)

                    # Local string repair and schema validation (ZERO second LLM calls!)
                    num_items = len(ordered_item_names)
                    observation = parse_and_validate_observation(raw_text, num_items)
                    return observation, total_latency_ms

                elif resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.warning(f"Transient error on attempt {attempts}: {last_error}")
                    # Allow at most max_transport_retries for 429/5xx
                    if attempts <= self.max_transport_retries:
                        retry_after = 2.5 * attempts
                        try:
                            resp_err = resp.json().get("error", {})
                            for detail in resp_err.get("details", []):
                                if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                                    delay_str = detail.get("retryDelay", "")
                                    if delay_str.endswith("s"):
                                        retry_after = max(retry_after, float(delay_str[:-1]))
                        except Exception:
                            pass
                        sleep_time = min(retry_after, max(0.1, remaining_time))
                        logger.info(f"Backing off for {sleep_time:.1f}s before retry...")
                        time.sleep(sleep_time)
                        continue
                    else:
                        raise ModelProviderError(f"Exhausted retries ({attempts}): {last_error}")
                else:
                    # Non-retryable client error (e.g. 400 Bad Request, 401 Unauthorized)
                    raise ModelProviderError(f"Gemini API error (HTTP {resp.status_code}): {resp.text[:300]}")

            except httpx.TimeoutException as te:
                last_error = te
                logger.warning(f"Timeout on attempt {attempts}: {te}")
                raise ModelTimeoutError(f"Model call timed out: {te}") from te
            except httpx.RequestError as re:
                last_error = re
                logger.warning(f"Network error on attempt {attempts}: {re}")
                if attempts <= self.max_transport_retries:
                    time.sleep(min(0.5 * attempts, max(0.1, remaining_time)))
                    continue
                raise ModelProviderError(f"Network request error: {re}") from re

        total_latency_ms = int((time.monotonic() - start_time) * 1000)
        raise ModelProviderError(f"Failed to obtain observation after {attempts} attempts: {last_error}")
