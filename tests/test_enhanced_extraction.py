#!/usr/bin/env python3
"""
Test script to compare standard vs enhanced extraction methods
"""

import os
import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.enhanced_extraction import enhanced_extract_grid
from app.grid_processor import GridProcessor


def test_single_grid(image_path: str):
    """Test both extraction methods on a single grid"""

    print(f"\n{'='*80}")
    print(f"Testing: {Path(image_path).name}")
    print('='*80)

    # Method 1: Enhanced extraction
    print("\n[ENHANCED EXTRACTION]")
    print("-" * 40)
    try:
        enhanced_results = enhanced_extract_grid(image_path, extract_individual=False)

        print(f"\nExtracted {len(enhanced_results)} cards:")
        for card in enhanced_results:
            pos = card.get('grid_position', '?')
            name = card.get('name', 'UNKNOWN')
            conf = card.get('_confidence', {})
            name_conf = conf.get('name', 0) if isinstance(conf, dict) else conf

            print(f"  [{pos}] {name:30s} (confidence: {name_conf:.0f}%)")

        # Show any low confidence cards
        low_conf = [c for c in enhanced_results if (c.get('_confidence', {}).get('name', 100) if isinstance(c.get('_confidence'), dict) else c.get('_confidence', 100)) < 60]
        if low_conf:
            print(f"\n⚠️  Low confidence cards ({len(low_conf)}):")
            for card in low_conf:
                pos = card.get('grid_position', '?')
                name = card.get('name', 'UNKNOWN')
                print(f"  [{pos}] {name}")

    except Exception as e:
        print(f"❌ Enhanced extraction failed: {e}")
        enhanced_results = None

    # Method 2: Standard extraction (for comparison)
    print("\n\n[STANDARD EXTRACTION]")
    print("-" * 40)
    try:
        # Temporarily disable enhanced extraction
        os.environ['USE_ENHANCED_EXTRACTION'] = 'false'

        processor = GridProcessor()
        grid_cards, raw_data = processor.process_3x3_grid(image_path)

        print(f"\nExtracted {len(raw_data)} cards:")
        for card in raw_data:
            pos = card.get('grid_position', '?')
            name = card.get('name', 'UNKNOWN')
            print(f"  [{pos}] {name:30s}")

    except Exception as e:
        print(f"❌ Standard extraction failed: {e}")
        raw_data = None
    finally:
        # Re-enable enhanced extraction
        os.environ['USE_ENHANCED_EXTRACTION'] = 'true'

    # Compare results
    if enhanced_results and raw_data:
        print("\n\n[COMPARISON]")
        print("-" * 40)

        differences = 0
        for i in range(min(len(enhanced_results), len(raw_data))):
            enh_name = enhanced_results[i].get('name', 'UNKNOWN')
            std_name = raw_data[i].get('name', 'UNKNOWN')

            if enh_name.lower() != std_name.lower():
                differences += 1
                print(f"  [{i}] DIFFERENT:")
                print(f"      Enhanced: {enh_name}")
                print(f"      Standard: {std_name}")

        if differences == 0:
            print("  ✓ All names match!")
        else:
            print(f"\n  {differences} differences found")

    print("\n" + "="*80 + "\n")

    return enhanced_results, raw_data


def main():
    """Test enhanced extraction on sample images"""

    # Find test images
    test_dir = Path("/Users/harlan/Documents/personal/code/programs/trading_cards_db/cards/unprocessed_bulk_back")

    if not test_dir.exists():
        print(f"Test directory not found: {test_dir}")
        return

    # Get first 2 images for testing
    images = list(test_dir.glob("*.HEIC"))[:2]

    if not images:
        print("No HEIC images found in test directory")
        return

    print(f"\nTesting enhanced extraction on {len(images)} images...")
    print(f"This will use ~{len(images) * 2} GPT-4 API calls")
    print(f"Estimated cost: ~${len(images) * 0.02:.2f}")

    response = input("\nContinue? (y/n): ")
    if response.lower() != 'y':
        print("Cancelled")
        return

    results = []
    for img_path in images:
        result = test_single_grid(str(img_path))
        results.append(result)

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    total_enhanced = sum(1 for r in results if r[0] is not None)
    total_standard = sum(1 for r in results if r[1] is not None)

    print(f"Enhanced extraction: {total_enhanced}/{len(images)} succeeded")
    print(f"Standard extraction: {total_standard}/{len(images)} succeeded")

    if total_enhanced > 0:
        # Calculate average confidence
        all_confidences = []
        for enhanced_result, _ in results:
            if enhanced_result:
                for card in enhanced_result:
                    conf = card.get('_confidence', {})
                    if isinstance(conf, dict):
                        name_conf = conf.get('name', 0)
                    else:
                        name_conf = conf
                    all_confidences.append(name_conf)

        if all_confidences:
            avg_conf = sum(all_confidences) / len(all_confidences)
            print(f"Average confidence: {avg_conf:.1f}%")

            low_conf_count = sum(1 for c in all_confidences if c < 60)
            print(f"Low confidence cards: {low_conf_count}/{len(all_confidences)} ({low_conf_count/len(all_confidences)*100:.1f}%)")

    print("\nNext steps:")
    print("1. Review the extraction results above")
    print("2. If accuracy is good, enable enhanced extraction for all processing")
    print("3. Process full batch with: export USE_ENHANCED_EXTRACTION=true && python -m app.run --grid")


if __name__ == "__main__":
    main()
