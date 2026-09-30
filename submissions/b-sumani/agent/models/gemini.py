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
)
from agent.models.parser import parse_and_validate_observation

load_dotenv()

logger = logging.getLogger("pack_manager.gemini")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Standard Gemini response schema for structured output
GEMINI_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "observed_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "sku": {"type": "STRING"},
                    "count": {"type": "INTEGER"},
                    "count_confidence": {"type": "NUMBER"},
                    "identity_confidence": {"type": "NUMBER"},
                    "partially_occluded": {"type": "BOOLEAN"},
                    "bbox": {"type": "ARRAY", "items": {"type": "NUMBER"}}
                },
                "required": ["sku", "count", "count_confidence", "identity_confidence", "partially_occluded", "bbox"]
            }
        },
        "unrecognised_items": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "description": {"type": "STRING"},
                    "bbox": {"type": "ARRAY", "items": {"type": "NUMBER"}}
                },
                "required": ["description", "bbox"]
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
        "occlusion_suspected": {"type": "BOOLEAN"},
        "notes": {"type": "STRING"}
    },
    "required": ["observed_items", "unrecognised_items", "image_quality", "occlusion_suspected"]
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
            # Use stronger evaluation model
            self.model_name = os.getenv("MODEL_NAME_EVAL", "gemini-3.1-pro-preview")
        else:
            # Use fast iteration dev model
            self.model_name = os.getenv("MODEL_NAME", "gemini-3-flash-preview")

        self.total_timeout_budget = total_timeout_budget
        self.max_transport_retries = max_transport_retries
        self.catalogue = catalogue if catalogue is not None else load_catalogue()

    def _build_prompt(self, candidate_skus: List[str]) -> str:
        """Constructs the prompt containing candidate SKUs and seller catalogue descriptions.
        
        CRITICAL: Never send order quantities or indicate which SKUs are real order items.
        """
        sku_lines = []
        for sku in candidate_skus:
            cat_entry = self.catalogue.get(sku)
            if cat_entry and cat_entry.get("title"):
                title = cat_entry.get("title", "")
                desc = cat_entry.get("description", "")
                if desc:
                    sku_lines.append(f"- {sku}: {title} - {desc}")
                else:
                    sku_lines.append(f"- {sku}: {title}")
            else:
                sku_lines.append(f"- {sku}")

        sku_list = "\n".join(sku_lines)
        return (
            "You are inspecting a photograph of an open shipping box before it is sealed.\n"
            "Below is the seller's catalogue of candidate products that may be packed in this box:\n"
            f"{sku_list}\n\n"
            "Instructions:\n"
            "1. Carefully identify which candidate SKUs from the catalogue above are visible in the open box.\n"
            "2. For each SKU observed, count how many units are visible, report count_confidence (0.0 to 1.0) "
            "and identity_confidence (0.0 to 1.0), whether it is partially occluded, and its bounding box [ymin, xmin, ymax, xmax].\n"
            "3. If you observe any item in the box that does NOT match any candidate SKU, add it to unrecognised_items "
            "with a description and bounding box.\n"
            "4. Inspect the image quality: mark usable as true/false, and list any issues (blur, glare, box_not_in_frame, dark).\n"
            "5. State whether occlusion is suspected (e.g. items stacked, hidden under packing material, or bottom not visible)."
        )

    def analyze_box(
        self,
        image_bytes: bytes,
        candidate_skus: List[str],
        timeout_seconds: Optional[float] = None
    ) -> Tuple[ModelObservation, int]:
        """Executes single vision model call with transport retries and local JSON repair."""
        if not self.api_key:
            raise ModelProviderError("GEMINI_API_KEY is not configured")

        budget = timeout_seconds or self.total_timeout_budget
        start_time = time.monotonic()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        prompt_text = self._build_prompt(candidate_skus)

        url = GEMINI_API_URL.format(model=self.model_name)
        url_with_key = f"{url}?key={self.api_key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt_text},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_b64
                            }
                        }
                    ]
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
                    observation = parse_and_validate_observation(raw_text, candidate_skus)
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
