import httpx
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
IMAGES_DIR = Path(r"C:\Users\user\Desktop\Pack Manager\images")

def test_validations_and_timeout():
    print("Testing upload validation and timeout handling against live server...")
    client = httpx.Client(base_url=BASE_URL, timeout=30.0)

    # 1. Non-image upload (.txt file)
    print("\n1. Testing non-image upload (.txt file)...")
    files = {"photo": ("notes.txt", b"Hello text file not image", "text/plain")}
    data = {
        "org_id": "org_demo_alpha",
        "order_id": "ORD-TEST-1",
        "unit_id": "UNIT-TEST-1",
        "order_lines": "SKU-SOAP-MYSORE:1",
        "candidate_skus": "SKU-SOAP-MYSORE",
        "operator_id": "op_test"
    }
    r1 = client.post("/pack/verify", data=data, files=files)
    print(f"  Non-image response: status={r1.status_code}, detail={r1.json() if r1.headers.get('content-type')=='application/json' else r1.text[:80]}")
    assert r1.status_code == 400
    assert "Invalid image format" in r1.text

    # 2. Oversize file (> 10MB)
    print("\n2. Testing oversize upload (> 10MB)...")
    big_bytes = b"\xff\xd8" + b"0" * (11 * 1024 * 1024) # 11MB pseudo jpeg
    files2 = {"photo": ("big.jpg", big_bytes, "image/jpeg")}
    r2 = client.post("/pack/verify", data=data, files=files2)
    print(f"  Oversize response: status={r2.status_code}, detail={r2.json() if r2.headers.get('content-type')=='application/json' else r2.text[:80]}")
    assert r2.status_code == 400
    assert "File too large" in r2.text

    # 3. Path traversal tricks in filename
    print("\n3. Testing path-traversal filename ('../../secret.jpg')...")
    files3 = {"photo": ("../../secret.jpg", b"\xff\xd8\xff\xe0" + b"fakejpg", "image/jpeg")}
    r3 = client.post("/pack/verify", data=data, files=files3)
    print(f"  Path traversal response: status={r3.status_code}, detail={r3.json() if r3.headers.get('content-type')=='application/json' else r3.text[:80]}")
    assert r3.status_code == 400
    assert "path traversal tricks forbidden" in r3.text

    # 4. Simulated Timeout
    print("\n4. Testing simulated timeout (simulate_timeout='true')...")
    img_bytes = (IMAGES_DIR / "UNIT-0017_open_box.jpeg").read_bytes()
    files4 = {"photo": ("UNIT-0017_open_box.jpeg", img_bytes, "image/jpeg")}
    data_timeout = {
        "org_id": "org_demo_alpha",
        "order_id": "ORD-TEST-TIMEOUT",
        "unit_id": "UNIT-0017",
        "order_lines": "SKU-EARBUDS-BOAT:1;SKU-PHONE-M36:1",
        "candidate_skus": "SKU-EARBUDS-BOAT, SKU-PHONE-M36",
        "operator_id": "op_timeout_test",
        "simulate_timeout": "true"
    }
    r4 = client.post("/pack/verify", data=data_timeout, files=files4)
    print(f"  Timeout response: status={r4.status_code}")
    assert r4.status_code == 200
    assert "PENDING" in r4.text
    assert "Agent unavailable: seal on your own judgment" in r4.text
    assert "Fail-Open" in r4.text
    print("  PENDING message confirmed in response HTML!")

    print("\nAll validation and timeout tests PASSED completely!")

if __name__ == "__main__":
    test_validations_and_timeout()
