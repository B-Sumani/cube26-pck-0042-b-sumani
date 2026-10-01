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


def capture_confidence():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True
        )
        context = browser.new_context(viewport={"width": 1280, "height": 950})
        page = context.new_page()

        # Step 1: Login as Alpha
        page.goto("http://127.0.0.1:8000/login")
        page.click("button:has-text('Enter as Alpha Demo Merchant')")
        page.wait_for_selector("#hero")

        # Step 2: Verify UNIT-0017
        page.fill("#order_id", "ORD-DEV-0017")
        page.fill("#unit_id", "UNIT-0017")

        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(0).select_option("SKU-EARBUDS-BOAT")

        page.click("#btn-add-picker-item")
        time.sleep(0.2)
        page.locator(".picker-row select.picker-sku").nth(1).select_option("SKU-PHONE-M36")

        img_0017 = str((IMAGES_DIR / "UNIT-0017_open_box.jpeg").resolve())
        page.set_input_files("#photo", img_0017)

        page.click("button[type='submit']")
        page.wait_for_selector("#result-container strong:has-text('UNIT-0017')", timeout=45000)
        time.sleep(1)

        result_el = page.locator("#result-container")
        save_screenshot(page, "17_result_corrected_confidence.png", result_el)
        # Also overwrite 04_result_unit0017_correct.png so all artifacts are in sync
        save_screenshot(page, "04_result_unit0017_correct.png", result_el)
        print("Captured updated result page with raw two-decimal confidence display.")
        browser.close()

if __name__ == "__main__":
    capture_confidence()
