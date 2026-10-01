import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCREENSHOT_DIR_LOCAL = Path("submissions/b-sumani/scratch/screenshots")
SCREENSHOT_DIR_ARTIFACT = Path(r"C:\Users\user\.gemini\antigravity\brain\40dec8f9-f67e-4f52-80d3-86829f07ed2a\screenshots")

SCREENSHOT_DIR_LOCAL.mkdir(parents=True, exist_ok=True)
SCREENSHOT_DIR_ARTIFACT.mkdir(parents=True, exist_ok=True)

IMAGES_DIR = Path(r"C:\Users\user\Desktop\Pack Manager\images")

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
    print("Starting Playwright E2E with Demo Org Login & Interactive Catalogue Picker...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True
        )
        context = browser.new_context(viewport={"width": 1280, "height": 950})
        page = context.new_page()

        # Step 1: Navigating to http://127.0.0.1:8000 (expect redirect to /login)
        print("\n1. Navigating to http://127.0.0.1:8000...")
        page.goto("http://127.0.0.1:8000")
        page.wait_for_url("**/login")
        print("   Successfully redirected to /login.")
        time.sleep(0.5)

        # Capture Login Page screenshot
        save_screenshot(page, "15_login_page.png")

        # Step 2: Login as Alpha Demo Merchant
        print("\n2. Logging in as Alpha Demo Merchant...")
        page.click("button:has-text('Enter as Alpha Demo Merchant')")
        page.wait_for_selector("#hero")
        print("   Signed in as Alpha Demo Merchant.")

        # Capture Hero and Header
        hero = page.locator("#hero")
        save_screenshot(page, "01_hero.png", hero)

        # Expand Catalogue Candidate summary
        cat_details = page.locator("#check details")
        if cat_details.count() > 0:
            cat_details.click()
            time.sleep(0.5)

        # Capture Check form with catalogue info and empty picker
        check_form = page.locator("#check")
        save_screenshot(page, "02_check_a_box_form.png", check_form)

        # Capture Catalogue Management section (#catalogue)
        cat_section = page.locator("#catalogue")
        save_screenshot(page, "16_catalogue_section.png", cat_section)

        # Step 3: Verify UNIT-0017 (Correct Box -> SEAL) using Picker
        print("\n3. Verifying UNIT-0017 (Correct Box -> SEAL) via Picker...")
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector("#check")

        page.fill("#order_id", "ORD-DEV-0017")
        page.fill("#unit_id", "UNIT-0017")

        # Add Row 1: SKU-EARBUDS-BOAT, Qty 1
        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        row1_select = page.locator(".picker-row select.picker-sku").nth(0)
        row1_select.select_option("SKU-EARBUDS-BOAT")

        # Add Row 2: SKU-PHONE-M36, Qty 1
        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        row2_select = page.locator(".picker-row select.picker-sku").nth(1)
        row2_select.select_option("SKU-PHONE-M36")

        # Attach dev photo
        img_0017 = str((IMAGES_DIR / "UNIT-0017_open_box.jpeg").resolve())
        page.set_input_files("#photo", img_0017)

        # Verify serialized hidden input
        serialized_val = page.locator("#order_lines_serialized").input_value()
        print(f"   Serialized Order Lines: {serialized_val}")
        assert "SKU-EARBUDS-BOAT:1" in serialized_val and "SKU-PHONE-M36:1" in serialized_val

        # Submit verification
        page.click("button[type='submit']")
        print("   Waiting for model response on UNIT-0017...")
        page.wait_for_selector("#result-container strong:has-text('UNIT-0017')", timeout=45000)
        time.sleep(1)

        result_el = page.locator("#result-container")
        save_screenshot(page, "04_result_unit0017_correct.png", result_el)
        print("   UNIT-0017 verified and screenshot captured.")

        # Step 4: Verify UNIT-0029 (Wrong Box -> STOP_AND_FIX) using Picker
        print("\n4. Verifying UNIT-0029 (Wrong Box -> STOP_AND_FIX) via Picker...")
        time.sleep(5)  # Pace between requests for free-tier / preview model limits
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector("#check")

        page.fill("#order_id", "ORD-DEV-0029")
        page.fill("#unit_id", "UNIT-0029")

        # Add 4 order lines:
        # SKU-BODYMILK-NIVEA:1; SKU-TRIMMER-BOMBAY:1; SKU-EARBUDS-BOAT:1; SKU-PHONE-M36:1
        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(0).select_option("SKU-BODYMILK-NIVEA")

        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(1).select_option("SKU-TRIMMER-BOMBAY")

        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(2).select_option("SKU-EARBUDS-BOAT")

        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(3).select_option("SKU-PHONE-M36")

        img_0029 = str((IMAGES_DIR / "UNIT-0029_open_box.jpeg").resolve())
        page.set_input_files("#photo", img_0029)

        serialized_val_29 = page.locator("#order_lines_serialized").input_value()
        print(f"   Serialized Order Lines: {serialized_val_29}")

        page.click("button[type='submit']")
        print("   Waiting for model response on UNIT-0029...")
        page.wait_for_selector("#result-container strong:has-text('UNIT-0029')", timeout=45000)
        time.sleep(1)

        result_el = page.locator("#result-container")
        save_screenshot(page, "05_result_unit0029_wrong.png", result_el)
        print("   UNIT-0029 verified and screenshot captured.")

        # Step 5: Verify UNIT-0049 (Blurry Box -> UNCERTAIN) using Picker
        print("\n5. Verifying UNIT-0049 (Blurry Box -> UNCERTAIN) via Picker...")
        time.sleep(5)  # Pace between requests
        page.goto("http://127.0.0.1:8000")
        page.wait_for_selector("#check")

        page.fill("#order_id", "ORD-DEV-0049")
        page.fill("#unit_id", "UNIT-0049")

        # Add 4 order lines:
        # SKU-BOOK-GGBB:1; SKU-SUNSCREEN-DERMA:1; SKU-SOAP-MYSORE:1; SKU-STICKY-MRDIY:1
        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(0).select_option("SKU-BOOK-GGBB")

        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(1).select_option("SKU-SUNSCREEN-DERMA")

        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(2).select_option("SKU-SOAP-MYSORE")

        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(3).select_option("SKU-STICKY-MRDIY")

        img_0049 = str((IMAGES_DIR / "UNIT-0049_open_box.jpeg").resolve())
        page.set_input_files("#photo", img_0049)

        serialized_val_49 = page.locator("#order_lines_serialized").input_value()
        print(f"   Serialized Order Lines: {serialized_val_49}")

        page.click("button[type='submit']")
        print("   Waiting for model response on UNIT-0049...")
        page.wait_for_selector("#result-container strong:has-text('UNIT-0049')", timeout=45000)
        time.sleep(1)

        result_el = page.locator("#result-container")
        save_screenshot(page, "06_result_unit0049_blurry.png", result_el)
        print("   UNIT-0049 verified and screenshot captured.")

        # Step 6: Test Tenancy Isolation by switching to Bravo
        print("\n6. Testing Tenancy Isolation: Switching to Bravo Demo Merchant...")
        page.click("a:has-text('Switch organisation')")
        page.wait_for_url("**/login")
        print("   Logged out to /login.")

        page.click("button:has-text('Enter as Bravo Demo Merchant')")
        page.wait_for_selector("#hero")
        print("   Signed in as Bravo Demo Merchant.")

        # Check records table: Bravo must see 0 of Alpha's records
        page.goto("http://127.0.0.1:8000#records")
        page.wait_for_selector("#records")
        time.sleep(1)

        records_text = page.locator("#records").text_content()
        assert "UNIT-0017" not in records_text
        assert "UNIT-0029" not in records_text
        assert "UNIT-0049" not in records_text
        print("   Confirmed: Bravo sees 0 Alpha records. Tenancy isolation holds.")

        save_screenshot(page, "14_tenancy_bravo_isolated.png", page.locator("#records"))

        browser.close()
        print("\nAll E2E checks passed and screenshots captured successfully!")


if __name__ == "__main__":
    run_e2e()
