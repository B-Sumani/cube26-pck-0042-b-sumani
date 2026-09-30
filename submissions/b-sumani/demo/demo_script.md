# Pack Manager · 3-Minute Video Walkthrough Script

**Video Title:** Pack Manager: Single-Shot Outbound Packaging Verification Agent  
**Presenter:** Sumani (`b-sumani`)  
**Target Duration:** ~3 minutes (180 seconds)  
**Demo URL:** `http://localhost:8000` (or production deployment URL)

---

## Scene 1: Introduction & Operational Context (0:00 – 0:30)

- **Visual:** Open browser on the Pack Manager homepage (`http://localhost:8000`). Scroll through the Hero section, Check a Box form, and Audit Records log.
- **Audio Script:**
  > "Hi, I'm Sumani. This is Pack Manager, Stage 3 of the Cube Buildathon commerce pipeline.
  > 
  > In merchant-fulfilled and 3PL fulfillment, the packing station is a critical blind spot. Pickers scan items into totes, but once items are placed into a carton and taped shut, all documentation ends. When a customer claims a missing item or an Amazon buyer files an empty-box dispute, sellers have no proof of what was actually packed.
  > 
  > Pack Manager fixes this by performing a single-shot vision verification from a single open-box photo taken immediately before the parcel is sealed, creating an evidence record for downstream Returns and Recovery pods."

---

## Scene 2: The Clean Pack → GO / SEAL (0:30 – 1:15)

- **Visual:** 
  1. Point out active tenant: `org_demo_alpha`.
  2. Input Order ID: `ORD-DUMMY-50008`, Unit ID: `UNIT-0008`.
  3. Enter Order Lines: `SKU-BOTTLE-750:1`.
  4. Point out Candidate SKUs includes decoys: `SKU-BOTTLE-750, SKU-PUZZLE-500, SKU-CABLE-USBC`.
  5. Select photograph `UNIT-0001_open_box.jpg`.
  6. Click "Inspect Box". Observe loading feedback spinner and banner.
  7. Result renders via HTMX without page reload.
- **Audio Script:**
  > "Let's inspect a clean carton for unit `UNIT-0008`. Notice that we never send order quantities to the vision model—only the photo and candidate SKUs including catalog decoys.
  > 
  > In a single inspection call, the model returns observed counts and confidences, and our deterministic rules layer verifies them. 
  > 
  > The operator sees a green **GO** banner and the **SEAL** approval. Below, all three checks are broken down: items present, quantities correct, and nothing extra. We see an order vs model comparison table and the photograph with SVG bounding boxes drawn as visual evidence."

---

## Scene 3: The Defect Pack → STOP_AND_FIX (1:15 – 1:45)

- **Visual:** 
  1. Input order lines expecting two items: `SKU-CANDLE-3:1; SKU-PUZZLE-500:1`.
  2. Upload photograph with only the puzzle in the box.
  3. Click "Inspect Box".
  4. Result renders red **STOP** banner (`STOP_AND_FIX`).
- **Audio Script:**
  > "Now let's test a packing error: an order expecting a candle and a puzzle, but only the puzzle is present.
  > 
  > Pack Manager immediately halts the packing line with a red **STOP** banner. 
  > 
  > Notice our orthogonal check partitioning: `all_items_present` failed with reason code `MISSING_ITEMS`, but `quantities_correct` passed because the items that were present matched their expected counts. Each physical defect has exactly one home, preventing cascading errors."

---

## Scene 4: Occlusion, Fail-Open, and Operator Override (1:45 – 2:30)

- **Visual:** 
  1. Upload photo with items occluded under packing material.
  2. Result renders prominent amber **STOP** banner with `UNCERTAIN` verdict:
     *"The agent could not verify this box. Please check the photo manually."*
  3. Click "View Evidence Record ↗" to open the permalink `/pack/record/{record_id}`.
  4. Scroll down to Override History section. Enter Supervisor ID `op_supervisor`, select `SEAL`, enter Reason: *"Manually verified candle positioned beneath bubble wrap"*. Click Submit Override.
  5. Page updates showing the append-only override row added to the audit trail.
- **Audio Script:**
  > "What happens when an item is hidden under bubble wrap? A top-down camera cannot see through dunnage. Instead of guessing, Pack Manager flags `UNCERTAIN` with `cause = occlusion`.
  > 
  > The operator sees a prominent instruction: 'The agent could not verify this box. Please check the photo manually.'
  > 
  > Opening the evidence permalink, a supervisor can log an override. The database enforces an append-only trigger—prior records are never modified in place, maintaining a clean audit trail."

---

## Scene 5: Multi-Tenant Security & Downstream Integration (2:30 – 3:00)

- **Visual:** 
  1. Navigate to Audit Records section on main page.
  2. Demonstrate filtering by Verdict (`SEAL`, `STOP_AND_FIX`), Cause (`occlusion`, `recognition`), and Unit ID.
  3. Switch tenant from `org_demo_alpha` to `org_demo_bravo`—demonstrate that records are isolated.
  4. Briefly show `contract/evidence-record.schema.json`.
- **Audio Script:**
  > "Finally, let's look at the audit log. Operators and compliance teams can filter by verdict, failure cause, date, or unit ID.
  > 
  > Because multi-client 3PLs pack for competing merchants, every table enforces forced Row-Level Security in Postgres. Tenant Alpha can never see Tenant Bravo's data, and storage images use short-lived HMAC signed URLs.
  > 
  > Every record is keyed by `unit_id`, allowing Returns Manager and Recovery Manager to join on the exact carton contents at seal time to review customer dispute claims.
  > 
  > That is Pack Manager: practical, deterministic, and built for the physical reality of warehouse fulfillment."
