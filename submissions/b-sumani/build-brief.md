# Technical Build Brief · Pack Manager

**Pod:** Stage 3 of 5 · Pack Manager  
**Author:** Sumani (`b-sumani`)  
**Pipeline:** Receiving (01) → Prep (02) → **Pack (03)** → Returns (04) → Recovery (05)

---

## 1. Domain & Operational Context

In merchant-fulfilled e-commerce and third-party logistics (3PL) warehouses, pickers assemble items into totes and deliver them to packing stations. At the pack station, an operator transfers the items into a corrugated shipping carton, inserts protective dunnage, tapes the box shut, and prints a carrier shipping label.

### The Mis-Ship Economic Reality
A packaging defect occurs when:
- An ordered item is omitted (short shipment).
- The wrong quantity of an ordered item is inserted (short or surplus).
- An unauthorized foreign object or adjacent order SKU is inserted (mis-pack).

When an outbound mis-pack reaches a customer:
1. **Replacement & Reshipping**: The seller absorbs return freight and outbound replacement shipping *(ASSUMPTION, unverified cost impact)*.
2. **Customer Support**: Handling missing item inquiries incurs support labor *(ASSUMPTION, unverified cost impact)*.
3. **Disputes & Buyer Claims**: Online marketplaces grant buyer refunds for claimed missing items. Without photographic proof of parcel contents immediately prior to box closure, sellers struggle to dispute claims *(ASSUMPTION, unverified marketplace claim)*.
4. **Account Performance**: High fulfillment defect rates risk marketplace penalties *(ASSUMPTION, unverified; no Amazon rules from memory)*.

Automated conveyor scanning systems exist for large distribution centers, but require fixed conveyors, overhead bar-code scanners, and substantial capital expenditures *(ASSUMPTION, unverified)*. Merchant sellers and mid-market 3PLs packing hundreds of parcels daily operate from flexible benches with manual packing processes and no dedicated automation budget *(ASSUMPTION, unverified)*.

---

## 2. Pack Station Physics & Constraints

- **Lighting & Glare**: Packing benches utilize overhead fluorescent or task LED lighting. Glossy polybags, bubble mailers, and plastic packaging produce specular reflections. The vision system must accommodate glare without classifying specular highlights as unrecognised items.
- **Occlusion**: Packing involves multi-item density and void fill (kraft paper, air pillows, tissue). Items placed at the bottom of a deep carton may be obscured by items above them. Top-down single-shot vision cannot verify what is physically concealed; acknowledging occlusion explicitly as `UNCERTAIN` (`cause='occlusion'`) prevents false alarms and false approvals.
- **Takt Time & Latency Budget**: A pack station operates at estimated bench takt times of 20 to 60 seconds per carton *(ASSUMPTION, unverified)*. A verification system taking more than 8–10 seconds risks becoming an operational bottleneck. When model latency spikes or rate limits occur, the system must fail open to avoid halting the packing conveyor.

---

## 3. Core Architectural Decisions

### Decision 1: Single Call Contract (Rule 2)
The system executes exactly **one** vision model call per unit carrying all checks. Separate model calls for presence, count, and decoys would multiply latency, cost, and rate-limit exposure by 3x. Transport retries are restricted to at most 2 backoff attempts inside a 15-second budget.

### Decision 2: Zero Quantity Leakage to Vision Model
The prompt sent to the vision model provides only the candidate SKU set (the order SKUs plus seller catalog decoys) and the photograph. The model reports what it physically observes in the box and its visual confidence per item. Verification of quantities is executed by deterministic Python code comparing observed counts to order expectations.

### Decision 3: Deterministic Rules Layer ("One Home Per Check")
Every failure mode maps to exactly one check:
- Missing items $\to$ `all_items_present`
- Count discrepancies $\to$ `quantities_correct`
- Decoys or foreign objects $\to$ `nothing_extra`
This guarantees that a single missing item does not trigger simultaneous failures across multiple checks.

### Decision 4: Multi-Tenant Row-Level Security
Multi-client 3PLs warehouse inventory for multiple competing merchants in the same physical facility. Pack Manager enforces Postgres RLS on every table. The application database user (`pack_app_user`) lacks superuser privileges and cannot bypass RLS. Tenant boundaries are established inside transactions using `SET LOCAL app.current_org_id`.

### Decision 5: Cross-Pod Integration Contract
Pack Manager emits evidence records keyed by `unit_id` (`UNIT-0001` through `UNIT-0100`). Returns Manager (Stage 4) and Recovery Manager (Stage 5) query these records to verify parcel contents at seal time.
