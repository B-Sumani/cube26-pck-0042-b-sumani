# Cross-Pod Evidence Record Contract · Pack Manager (Stage 3)

This directory defines the formal data contract between **Pack Manager (Stage 3)** and downstream pods in the Cube Buildathon commerce pipeline:
- **Returns Manager (Stage 4)**: Consumes pack evidence to verify whether returned goods match what was physically sealed into the parcel.
- **Recovery Manager (Stage 5)**: Consumes pack evidence to adjudicate buyer disputes, empty-box claims, wrong-item claims, and compile dispute filings.

---

## 1. Cross-Pod Join Key (`unit_id`)

All five pods in the commerce chain share the canonical identifier format:
$$\text{UNIT-0001} \dots \text{UNIT-0100}$$

```text
 01 Receiving       02 Prep            03 Pack             04 Returns          05 Recovery
 ┌──────────────┐   ┌──────────────┐   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
 │ Condition    │──▶│ Compliance   │──▶│ Contents at  │───▶│ Return State │───▶│ Adjudicate   │
 │ on arrival   │   │ proof        │   │ seal         │    │ vs Packed    │    │ Claims / Disp│
 └──────┬───────┘   └──────┬───────┘   └──────┬───────┘    └──────┬───────┘    └──────▲───────┘
        └──────────────────┴──────────────────┴───────────────────┴───────────────────┘
                                   Joined on: unit_id
```

Each physical unit follows either an **FBA path** (Receiving $\to$ Prep $\to$ Amazon) or a **Merchant-Fulfilled / 3PL path** (Receiving $\to$ Pack $\to$ Outbound). Therefore, a unit processed by Pack Manager has a record keyed by `unit_id`.

---

## 2. Record Identification & Schema

- **Record ID Pattern**: `PCK-[A-Za-z0-9_-]+`
- **Schema Definition**: [`evidence-record.schema.json`](./evidence-record.schema.json) (Draft 2020-12 compliant)
- **Tenancy Boundary**: Every query must include the tenant context (`org_id`). Pack records cannot be accessed across tenant boundaries.

### Core Field Specifications

| Field | Type | Description | Downstream Use |
|---|---|---|---|
| `id` | `string` | Unique record ID (`PCK-...`) | Audit anchor |
| `unit_id` | `string` | Cross-pod join key (`UNIT-XXXX`) | Foreign key across all 5 repos |
| `org_id` | `string` | Tenant organization ID | Row-level security partition |
| `order_lines` | `string` | Expected SKU counts (`SKU:qty;...`) | Baseline customer order |
| `observed_in_box` | `string` | Vision-observed SKU counts (`SKU:qty;...`) | Actual packed inventory |
| `checks` | `object` | Three orthogonal check evaluations | Explanatory defect breakdown |
| `verdict` | `enum / null` | `SEAL`, `STOP_AND_FIX`, `UNCERTAIN`, or `null` | Primary gating decision |
| `status` | `enum` | `completed` or `pending` | Operational health signal |
| `content_hash` | `string` | SHA-256 digest of original photo bytes | Proof of original photograph contents |
| `overrides` | `array` | Supervisor adjustments (append-only) | Traceability of manual actions |

---

## 3. The Three Orthogonal Checks ("One Home Per Check")

Pack Manager enforces a strict partitioning where every physical packaging outcome maps to exactly one check:

1. **`all_items_present` (Presence / Identity)**:
   - Evaluates if every ordered SKU has an observed count $\ge 1$.
   - Defect reason: `MISSING_ITEMS` (`cause = 'recognition'`).
   - Occlusion reason: `ITEM_OCCLUDED` (`cause = 'occlusion'`).
2. **`quantities_correct` (Piece Count Accuracy)**:
   - Evaluates whether the piece counts of present ordered SKUs match the expected quantities.
   - Completely missing items are deferred to `all_items_present` so defects are not double-penalized.
   - Defect reasons: `SHORT_QUANTITY` or `SURPLUS_QUANTITY` (`cause = 'recognition'`).
3. **`nothing_extra` (Decoys & Foreign Objects)**:
   - Evaluates whether unauthorized items were placed in the parcel.
   - Defect reasons: `DECOY_ITEM_PRESENT` (seller catalog decoys) or `UNRECOGNISED_ITEMS_PRESENT` (foreign items).

---

## 4. Operational Status & Fail-Open Semantics

- **`status = 'completed'`**: The vision model and rules evaluator finished execution. `verdict` is populated (`SEAL`, `STOP_AND_FIX`, or `UNCERTAIN`).
- **`status = 'pending'`**: Fail-open mode triggered due to model timeout or unrecoverable provider exception.
  - **Constraint**: `verdict` is strictly `NULL`.
  - **Warehouse instruction**: *"Agent unavailable: seal on your own judgment"*.
  - Downstream pods should treat `pending` records as unverified at pack time; physical recovery claims must rely on upstream Prep or Receiving records.

---

## 5. Sample Contract Payloads

### Example 1: Clean Pack Approved for Sealing (`SEAL`)

```json
{
  "id": "PCK-A1B2C3D4",
  "org_id": "org_demo_alpha",
  "unit_id": "UNIT-0008",
  "capture_id": "CAP-887123",
  "order_lines": "SKU-BOTTLE-750:1;SKU-PUZZLE-500:1",
  "observed_in_box": "SKU-BOTTLE-750:1;SKU-PUZZLE-500:1",
  "checks": {
    "all_items_present": {
      "result": "PASS",
      "reason_code": "ALL_ORDERED_ITEMS_DETECTED",
      "reason": "All 2 ordered SKUs observed with sufficient confidence.",
      "cause": null,
      "confidences": {
        "SKU-BOTTLE-750": 0.94,
        "SKU-PUZZLE-500": 0.89
      }
    },
    "quantities_correct": {
      "result": "PASS",
      "reason_code": "ALL_QUANTITIES_EXACT_MATCH",
      "reason": "Observed item quantities match order expectations exactly.",
      "cause": null,
      "expected_count": 2,
      "observed_count": 2
    },
    "nothing_extra": {
      "result": "PASS",
      "reason_code": "NO_EXTRA_ITEMS_DETECTED",
      "reason": "No unrecognised items or unauthorized catalog decoys detected.",
      "cause": null
    }
  },
  "verdict": "SEAL",
  "status": "completed",
  "model": "gemini-3-flash-preview",
  "model_latency_ms": 4210,
  "content_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "created_at": "2026-09-30T10:15:30Z",
  "overrides": []
}
```

### Example 2: Defective Pack Flagged with Missing Item (`STOP_AND_FIX`)

```json
{
  "id": "PCK-E5F6G7H8",
  "org_id": "org_demo_alpha",
  "unit_id": "UNIT-0012",
  "capture_id": "CAP-887124",
  "order_lines": "SKU-PROT-1KG:1;SKU-TOWEL-BLU:1",
  "observed_in_box": "SKU-PROT-1KG:1",
  "checks": {
    "all_items_present": {
      "result": "FAIL",
      "reason_code": "MISSING_ITEMS",
      "reason": "Missing 1 ordered SKU: SKU-TOWEL-BLU",
      "cause": "recognition",
      "confidences": {
        "SKU-PROT-1KG": 0.96
      }
    },
    "quantities_correct": {
      "result": "PASS",
      "reason_code": "PRESENT_ITEMS_COUNT_MATCH",
      "reason": "Present items match expected piece counts.",
      "cause": null,
      "expected_count": 1,
      "observed_count": 1
    },
    "nothing_extra": {
      "result": "PASS",
      "reason_code": "NO_EXTRA_ITEMS_DETECTED",
      "reason": "No extra items detected in box.",
      "cause": null
    }
  },
  "verdict": "STOP_AND_FIX",
  "status": "completed",
  "model": "gemini-3-flash-preview",
  "model_latency_ms": 3890,
  "content_hash": "8f434346648f6b96df89dda901c5176b10a6d83961dd3c1ac88b59b2dc327aa4",
  "created_at": "2026-09-30T10:18:45Z",
  "overrides": []
}
```

### Example 3: Occluded Pack Flagged for Human Check (`UNCERTAIN`)

```json
{
  "id": "PCK-J9K0L1M2",
  "org_id": "org_demo_bravo",
  "unit_id": "UNIT-0019",
  "capture_id": "CAP-887125",
  "order_lines": "SKU-SERUM-30:2;SKU-CABLE-USBC:1",
  "observed_in_box": "SKU-SERUM-30:1",
  "checks": {
    "all_items_present": {
      "result": "UNCERTAIN",
      "reason_code": "ITEM_OCCLUDED",
      "reason": "Missing SKU-CABLE-USBC suspected to be hidden under packing material.",
      "cause": "occlusion"
    },
    "quantities_correct": {
      "result": "UNCERTAIN",
      "reason_code": "COUNT_OCCLUDED",
      "reason": "SKU-SERUM-30 count (1 of 2) may be occluded by dunnage.",
      "cause": "occlusion"
    },
    "nothing_extra": {
      "result": "PASS",
      "reason_code": "NO_EXTRA_ITEMS_DETECTED",
      "reason": "No foreign items detected.",
      "cause": null
    }
  },
  "verdict": "UNCERTAIN",
  "status": "completed",
  "model": "gemini-3-flash-preview",
  "model_latency_ms": 4600,
  "content_hash": "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
  "created_at": "2026-09-30T10:22:10Z",
  "overrides": [
    {
      "id": "OVR-0001",
      "original_verdict": "UNCERTAIN",
      "new_verdict": "SEAL",
      "reason": "Manually verified second serum bottle and USB-C cable placed beneath tissue paper.",
      "operator_id": "op_marcus",
      "created_at": "2026-09-30T10:23:45Z"
    }
  ]
}
```

### Example 4: Fail-Open State on Model Timeout (`PENDING`)

```json
{
  "id": "PCK-P3Q4R5S6",
  "org_id": "org_demo_alpha",
  "unit_id": "UNIT-0033",
  "capture_id": "CAP-887126",
  "order_lines": "SKU-MUG-11:1",
  "observed_in_box": "",
  "checks": {},
  "verdict": null,
  "status": "pending",
  "model": "gemini-3-flash-preview",
  "model_latency_ms": 15000,
  "content_hash": "f0e1d2c3b4a5968778695a4b3c2d1e0ff0e1d2c3b4a5968778695a4b3c2d1e0f",
  "created_at": "2026-09-30T10:25:00Z",
  "overrides": []
}
```
