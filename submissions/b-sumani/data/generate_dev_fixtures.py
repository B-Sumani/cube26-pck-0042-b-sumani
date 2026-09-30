"""Fixture generator for the 15 dev-set units.

Generates synthetic open-box test images in data/fixtures/dev/.
Labelled as synthetic test fixtures per context.md Section 7.
"""

import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


def generate_dev_fixtures():
    fixtures_dir = Path(__file__).parent / "fixtures" / "dev"
    fixtures_dir.mkdir(parents=True, exist_ok=True)

    # 15 dev cases
    for i in range(1, 16):
        unit_id = f"UNIT-{i:04d}"
        img_path = fixtures_dir / f"{unit_id}_open_box.jpg"
        
        # Base image: Open cardboard box background
        img = Image.new("RGB", (640, 480), color=(198, 168, 133))
        draw = ImageDraw.Draw(img)

        # Draw box interior and inner flaps
        draw.rectangle([40, 40, 600, 440], outline=(120, 90, 60), width=6)
        draw.line([40, 40, 100, 100], fill=(100, 75, 50), width=3)
        draw.line([600, 40, 540, 100], fill=(100, 75, 50), width=3)
        draw.line([40, 440, 100, 380], fill=(100, 75, 50), width=3)
        draw.line([600, 440, 540, 380], fill=(100, 75, 50), width=3)
        draw.rectangle([100, 100, 540, 380], fill=(185, 155, 120), outline=(140, 110, 80), width=2)

        # Case-specific objects
        if i == 1:
            # 1x SKU-BOTTLE-750 (Blue cylinder)
            draw.rectangle([250, 160, 350, 340], fill=(45, 90, 160), outline=(20, 50, 110), width=2)
            draw.text((260, 240), "BOTTLE-750", fill=(255, 255, 255))
        elif i == 2:
            # 1x SKU-PUZZLE-500 + 1x SKU-BOTTLE-750
            draw.rectangle([140, 160, 280, 320], fill=(180, 70, 70), outline=(120, 40, 40), width=2)
            draw.text((160, 230), "PUZZLE-500", fill=(255, 255, 255))
            draw.rectangle([340, 160, 440, 340], fill=(45, 90, 160), outline=(20, 50, 110), width=2)
            draw.text((350, 240), "BOTTLE-750", fill=(255, 255, 255))
        elif i == 3:
            # 2x SKU-TOWEL-BLU
            draw.rectangle([160, 180, 300, 300], fill=(80, 140, 180), outline=(50, 90, 130), width=2)
            draw.text((180, 230), "TOWEL-1", fill=(255, 255, 255))
            draw.rectangle([340, 180, 480, 300], fill=(80, 140, 180), outline=(50, 90, 130), width=2)
            draw.text((360, 230), "TOWEL-2", fill=(255, 255, 255))
        elif i == 4:
            # Missing candle: only puzzle present
            draw.rectangle([200, 160, 360, 320], fill=(180, 70, 70), outline=(120, 40, 40), width=2)
            draw.text((230, 230), "PUZZLE-500", fill=(255, 255, 255))
        elif i == 5:
            # Short quantity: 1 protein powder instead of 2
            draw.rectangle([240, 160, 380, 340], fill=(40, 40, 40), outline=(10, 10, 10), width=2)
            draw.text((255, 240), "PROT-1KG", fill=(255, 255, 255))
        elif i == 6:
            # Surplus quantity: 2 bottles instead of 1
            draw.rectangle([180, 160, 280, 340], fill=(45, 90, 160), outline=(20, 50, 110), width=2)
            draw.text((190, 240), "BOTTLE 1", fill=(255, 255, 255))
            draw.rectangle([340, 160, 440, 340], fill=(45, 90, 160), outline=(20, 50, 110), width=2)
            draw.text((350, 240), "BOTTLE 2", fill=(255, 255, 255))
        elif i == 7:
            # Decoy item: 1 mug + 1 decoy cable
            draw.rectangle([160, 180, 280, 320], fill=(220, 220, 220), outline=(160, 160, 160), width=2)
            draw.text((180, 240), "MUG-11", fill=(50, 50, 50))
            draw.rectangle([340, 200, 480, 300], fill=(30, 30, 30), outline=(0, 0, 0), width=2)
            draw.text((360, 240), "CABLE-USBC (DECOY)", fill=(255, 255, 255))
        elif i == 8:
            # Unrecognised item: 1 serum + 1 foreign wrench/tool
            draw.rectangle([180, 180, 280, 320], fill=(230, 190, 150), outline=(180, 140, 100), width=2)
            draw.text((200, 240), "SERUM-30", fill=(50, 50, 50))
            draw.rectangle([340, 220, 480, 260], fill=(120, 130, 140), outline=(70, 80, 90), width=2)
            draw.text((360, 235), "FOREIGN TOOL", fill=(255, 255, 255))
        elif i == 9:
            # Occluded puzzle under flap
            draw.rectangle([200, 160, 360, 320], fill=(180, 70, 70), outline=(120, 40, 40), width=2)
            draw.polygon([(160, 140), (280, 140), (240, 280), (140, 260)], fill=(150, 120, 90))
            draw.text((240, 240), "OCCLUDED", fill=(255, 255, 255))
        elif i == 11:
            # Blurry image
            draw.rectangle([250, 160, 350, 340], fill=(45, 90, 160), outline=(20, 50, 110), width=2)
            draw.text((260, 240), "BOTTLE-750", fill=(255, 255, 255))
            img = img.filter(ImageFilter.GaussianBlur(radius=8))
        elif i == 12:
            # Glare / overexposed
            draw.rectangle([250, 160, 350, 340], fill=(80, 140, 180), outline=(50, 90, 130), width=2)
            draw.ellipse([200, 140, 400, 340], fill=(255, 255, 255))
        else:
            # Generic valid pack representation
            draw.rectangle([220, 160, 400, 320], fill=(90, 130, 90), outline=(50, 90, 50), width=2)
            draw.text((250, 230), f"ITEM {i}", fill=(255, 255, 255))

        img.save(img_path, format="JPEG", quality=85)

    print(f"Generated 15 dev fixtures in {fixtures_dir}")


if __name__ == "__main__":
    generate_dev_fixtures()
