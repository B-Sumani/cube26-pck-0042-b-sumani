import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SCREENSHOT_DIR_LOCAL = Path("submissions/b-sumani/scratch/screenshots")
SCREENSHOT_DIR_ARTIFACT = Path(r"C:\Users\user\.gemini\antigravity\brain\40dec8f9-f67e-4f52-80d3-86829f07ed2a\screenshots")

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

def capture_mobile_and_record():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            headless=True
        )

        # 1. Mobile viewport (375x812)
        print("Capturing updated mobile screenshots after navbar fix...")
        context_m = browser.new_context(viewport={"width": 375, "height": 812})
        page_m = context_m.new_page()
        page_m.goto("http://127.0.0.1:8000")
        page_m.wait_for_selector("#hero")
        time.sleep(1)
        save_screenshot(page_m, "10_mobile_hero_form_fixed.png")
        save_screenshot(page_m, "11_mobile_records_fixed.png", page_m.locator("#records"))
        context_m.close()

        # 2. Desktop evidence record permalink for UNIT-0049 (with override)
        print("Capturing evidence record permalink...")
        context_d = browser.new_context(viewport={"width": 1280, "height": 950})
        page_d = context_d.new_page()
        # Find first record link from records table
        page_d.goto("http://127.0.0.1:8000#records")
        page_d.wait_for_selector("#records")
        rec_link = page_d.locator("#records table a[href^='/pack/record/']").first
        if rec_link.count() > 0:
            href = rec_link.get_attribute("href")
            print(f"Opening evidence record: {href}")
            page_d.goto(f"http://127.0.0.1:8000{href}")
            page_d.wait_for_selector("body")
            time.sleep(1)
            save_screenshot(page_d, "12_evidence_record_detail.png")

        context_d.close()
        browser.close()
        print("Mobile and record screenshots captured successfully!")

if __name__ == "__main__":
    capture_mobile_and_record()
