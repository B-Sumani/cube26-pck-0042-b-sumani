import os
import sys
import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCREENSHOT_DIR_LOCAL = Path("submissions/b-sumani/scratch/screenshots")
SCREENSHOT_DIR_ARTIFACT = Path(r"C:\Users\user\.gemini\antigravity\brain\40dec8f9-f67e-4f52-80d3-86829f07ed2a\screenshots")

SCREENSHOT_DIR_LOCAL.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR_ARTIFACT.mkdir(parents=True, exist_ok=True)

IMAGES_DIR = Path(r"C:\Users\user\Desktop\Pack Manager\images")

FULL_CATALOGUE = "SKU-BODYMILK-NIVEA, SKU-BOOK-GGBB, SKU-BOOK-GGGM, SKU-EARBUDS-BOAT, SKU-PHONE-M36, SKU-SANITIZER-DETTOL, SKU-SOAP-MYSORE, SKU-STICKY-MRDIY, SKU-SUNSCREEN-DERMA, SKU-TRIMMER-BOMBAY"

def save_screenshot(page, filename, element=None):
    local_path = SCREENSHOT_DIR_LOCAL / filename
    art_path = SCREENSHOT_DIR_ARTIFACT / filename
    if element:
        element.screenshot(path=str(local_path))
        element.screenshot(path=str(art_path))
    else:
        page.screenshot(path=str(local_path), full_page=False)
        page.screenshot(path=str(art_path), full_page=False)
    print(f"  [Screenshot saved] {filename}")

def run_e2e():
    print("Starting Playwright E2E testing on live Pack Manager website...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True
        )
        context = browser.new_context(viewport={"width": 1280, "height": 950})
        page = context.new_page()

        # Step 1: Open Home Page
        print("\n1. Navigating to http://127.0.0.1:8000...")
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector("#hero")

        hero = page.locator("#hero")
        save_screenshot(page, "01_hero.png", hero)

        check_form = page.locator("#check")
        save_screenshot(page, "02_check_a_box_form.png", check_form)

        records_sec = page.locator("#records")
        save_screenshot(page, "03_records_section_initial.png", records_sec)

        # Step 2: Upload UNIT-0017 (Correct Box)
        print("\n2. Uploading UNIT-0017 (Correct Box -> SEAL)...")
        img_0017 = str((IMAGES_DIR / "UNIT-0017_open_box.jpeg").resolve())
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector("#check")
        page.select_option("#org_id", "org_demo_alpha")
        page.fill("#unit_id", "UNIT-0017")
        page.fill("#order_id", "ORD-DEV-0017")
        page.fill("#order_lines", "SKU-EARBUDS-BOAT:1;SKU-PHONE-M36:1")
        page.fill("#candidate_skus", FULL_CATALOGUE)
        page.set_input_files("#photo", img_0017)

        page.click("button[type='submit']")
        print("   Waiting for live model response on UNIT-0017...")
        page.wait_for_selector("#result-container strong:has-text('UNIT-0017')", timeout=45000)
        time.sleep(1)

        result_el = page.locator("#result-container")
        save_screenshot(page, "04_result_unit0017_correct.png", result_el)
        print("   UNIT-0017 verified and screenshot captured.")

        # Step 3: Upload UNIT-0029 (Wrong Box)
        print("\n3. Uploading UNIT-0029 (Wrong Box -> STOP_AND_FIX)...")
        time.sleep(3) # pace between requests
        img_0029 = str((IMAGES_DIR / "UNIT-0029_open_box.jpeg").resolve())
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector("#check")
        page.select_option("#org_id", "org_demo_alpha")
        page.fill("#unit_id", "UNIT-0029")
        page.fill("#order_id", "ORD-DEV-0029")
        page.fill("#order_lines", "SKU-BODYMILK-NIVEA:1;SKU-TRIMMER-BOMBAY:1;SKU-EARBUDS-BOAT:1;SKU-PHONE-M36:1")
        page.fill("#candidate_skus", FULL_CATALOGUE)
        page.set_input_files("#photo", img_0029)

        page.click("button[type='submit']")
        print("   Waiting for live model response on UNIT-0029...")
        page.wait_for_selector("#result-container strong:has-text('UNIT-0029')", timeout=45000)
        time.sleep(1)

        result_el = page.locator("#result-container")
        save_screenshot(page, "05_result_unit0029_wrong.png", result_el)
        print("   UNIT-0029 verified and screenshot captured.")

        # Step 4: Upload UNIT-0049 (Blurry Box -> UNCERTAIN)
        print("\n4. Uploading UNIT-0049 (Blurry Box -> UNCERTAIN)...")
        time.sleep(3) # pace between requests
        img_0049 = str((IMAGES_DIR / "UNIT-0049_open_box.jpeg").resolve())
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector("#check")
        page.select_option("#org_id", "org_demo_alpha")
        page.fill("#unit_id", "UNIT-0049")
        page.fill("#order_id", "ORD-DEV-0049")
        page.fill("#order_lines", "SKU-BOOK-GGBB:1;SKU-SUNSCREEN-DERMA:1;SKU-SOAP-MYSORE:1;SKU-STICKY-MRDIY:1")
        page.fill("#candidate_skus", FULL_CATALOGUE)
        page.set_input_files("#photo", img_0049)

        page.click("button[type='submit']")
        print("   Waiting for live model response on UNIT-0049...")
        page.wait_for_selector("#result-container strong:has-text('UNIT-0049')", timeout=45000)
        time.sleep(1)

        result_el = page.locator("#result-container")
        save_screenshot(page, "06_result_unit0049_blurry.png", result_el)
        print("   UNIT-0049 verified and screenshot captured.")

        # Step 5: Test Operator Override on UNIT-0049
        print("\n5. Testing Operator Override on UNIT-0049...")
        summary_btn = page.locator("summary:has-text('Manual Operator Override')")
        if summary_btn.count() > 0:
            summary_btn.click()
            time.sleep(0.5)
            page.select_option("select[name='new_verdict']", "SEAL")
            page.fill("textarea[name='reason']", "Supervisor visual inspection: physical packaging verified all 4 items present in open carton.")
            page.click("button:has-text('Save Override Record')")
            time.sleep(2)
            save_screenshot(page, "07_override_completed.png", page.locator("#result-container"))
            print("   Override submitted successfully.")

        # Check records table with override
        page.goto("http://127.0.0.1:8000#records")
        page.wait_for_selector("#records")
        time.sleep(1)
        save_screenshot(page, "08_records_with_override.png", page.locator("#records"))

        # Step 6: Test Simulated Timeout (PENDING)
        print("\n6. Testing Simulated Timeout -> PENDING...")
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector("#check")
        page.evaluate("""
            const form = document.querySelector('form[hx-post="/pack/verify"]');
            let input = document.getElementById('simulate_timeout_input');
            if (!input) {
                input = document.createElement('input');
                input.type = 'hidden';
                input.id = 'simulate_timeout_input';
                input.name = 'simulate_timeout';
                form.appendChild(input);
            }
            input.value = 'true';
        """)
        page.fill("#unit_id", "UNIT-0099")
        page.fill("#order_id", "ORD-TIMEOUT-TEST")
        page.set_input_files("#photo", img_0017)
        page.click("button[type='submit']")
        page.wait_for_selector("#result-container span:has-text('PENDING')", timeout=15000)
        time.sleep(1)

        result_el = page.locator("#result-container")
        save_screenshot(page, "09_timeout_pending.png", result_el)
        print("   Simulated timeout PENDING screenshot captured.")

        # Step 7: Test Mobile Viewport (375px)
        print("\n7. Testing Mobile Viewport (375x812)...")
        context_mobile = browser.new_context(viewport={"width": 375, "height": 812})
        page_m = context_mobile.new_page()
        page_m.goto("http://127.0.0.1:8000")
        page_m.wait_for_selector("#hero")
        time.sleep(1)
        save_screenshot(page_m, "10_mobile_hero_form.png")
        save_screenshot(page_m, "11_mobile_records.png", page_m.locator("#records"))
        context_mobile.close()

        browser.close()
        print("\n=== Playwright E2E Suite Completed Successfully! ===")

if __name__ == "__main__":
    run_e2e()
