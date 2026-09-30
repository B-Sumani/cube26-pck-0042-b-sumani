"""Storage manager for Pack Manager.

Enforces:
1. Unguessable storage keys with SHA-256 content hashing and UUID entropy.
2. Private storage bucket (no public access).
3. Short-lived signed URLs with tenant verification (cross-tenant access is rejected).
"""

from __future__ import annotations
import os
import time
import hmac
import hashlib
import uuid
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

STORAGE_BUCKET_NAME = os.getenv("STORAGE_BUCKET_NAME", "pack-evidence-records")
SIGNED_URL_EXPIRY_SECONDS = int(os.getenv("SIGNED_URL_EXPIRY_SECONDS", "3600"))
STORAGE_SECRET_KEY = os.getenv("STORAGE_SECRET_KEY", "insecure-dev-storage-secret-key-change-in-prod")


class TenancyStorageError(PermissionError):
    """Raised when a tenant attempts to access or sign keys belonging to another tenant."""
    pass


def generate_storage_key(org_id: str, unit_id: str, filename: str, content_bytes: bytes) -> str:
    """Generates an unguessable storage key containing the org_id, unit_id, random UUID, and content hash.
    
    Structure: tenants/{org_id}/{unit_id}/{uuid}_{content_hash}_{sanitized_filename}
    """
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    random_entropy = uuid.uuid4().hex
    safe_filename = os.path.basename(filename).replace(" ", "_")
    return f"tenants/{org_id}/{unit_id}/{random_entropy}_{content_hash[:16]}_{safe_filename}"


def extract_org_from_key(storage_key: str) -> Optional[str]:
    """Extracts the tenant org_id from a storage key."""
    parts = storage_key.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "tenants":
        return parts[1]
    return None


def create_signed_url(org_id: str, storage_key: str, expires_in: int = SIGNED_URL_EXPIRY_SECONDS) -> str:
    """Generates a short-lived signed URL for an image.
    
    STRICT TENANCY RULE:
    The requesting org_id MUST match the org_id encoded in the storage key.
    If org_demo_bravo attempts to request a signed URL for an org_demo_alpha key,
    a TenancyStorageError is raised immediately.
    """
    key_org = extract_org_from_key(storage_key)
    if key_org and key_org != org_id:
        raise TenancyStorageError(
            f"Tenant '{org_id}' is not authorized to access key '{storage_key}' belonging to '{key_org}'"
        )
    
    # If Supabase storage is configured, we can delegate to Supabase
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if supabase_url and supabase_service_key:
        try:
            from supabase import create_client
            client = create_client(supabase_url, supabase_service_key)
            res = client.storage.from_(STORAGE_BUCKET_NAME).create_signed_url(storage_key, expires_in)
            if "signedURL" in res:
                return res["signedURL"]
        except Exception:
            # Fall back to local HMAC signed URL generator
            pass
            
    # Standard HMAC-SHA256 short-lived token generation
    expires_at = int(time.time()) + expires_in
    message = f"{org_id}:{storage_key}:{expires_at}"
    signature = hmac.new(
        STORAGE_SECRET_KEY.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    return f"/api/storage/{storage_key}?org={org_id}&expires={expires_at}&sig={signature}"


def verify_signed_token(storage_key: str, requesting_org: str, expires_at: int, signature: str) -> bool:
    """Validates that a signed token is authentic, unexpired, and belongs to the requesting org."""
    if time.time() > expires_at:
        return False  # Expired
        
    key_org = extract_org_from_key(storage_key)
    if key_org and key_org != requesting_org:
        return False  # Cross-tenant mismatch
        
    expected_message = f"{requesting_org}:{storage_key}:{expires_at}"
    expected_sig = hmac.new(
        STORAGE_SECRET_KEY.encode("utf-8"),
        expected_message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_sig, signature)
