#!/usr/bin/env python3
"""Baseball Card Storage Recommendation Script Analyzes a photo of baseball
cards using GPT-5.2 Vision."""

import base64
import io
import os
import re
import shutil
import sys
from pathlib import Path

import pillow_heif
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

# Load environment variables from trading_cards_db/.env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

PROMPT = """I upload photos of baseball cards, usually arranged in grids. You identify each card individually and treat them one by one, not as a group. For each card, you determine what type of card it is (player card, prospect, checklist, stat card, Bowman paper vs Chrome, etc.). You consider the player, career outcome, era, brand, year, condition visible in the photo, and typical market value. You assume my default storage is cards stored in boxes in rows, out of light, protected, for long term value preservation.

For each card, you give a per-card storage recommendation, choosing only from:
    •    no protection
    •    penny sleeve
    •    top loader
    •    special storage (only for genuinely high-value cases)

You do not overprotect low-value commons, even if the player had a good career. Bowman paper and most base cards get penny sleeves at most. Chrome, refractors, rookies, stars, or higher-value inserts may get top loaders.

You do not identify people from images beyond what's printed on the card.

FORMAT YOUR RESPONSE AS ONE LINE PER CARD:
Card [number]: [player name, year, brand, card type] | Storage: [recommendation] | Reason: [brief explanation] | Price: [estimated market value]

Separate each card with a blank line."""


def encode_image(image_path: str) -> tuple[str, str]:
    """Encode image to base64 string, converting HEIC to JPEG if needed.

    Returns:
        tuple: (base64_string, mime_type)
    """
    path = Path(image_path)
    ext = path.suffix.lower()

    # Convert HEIC/HEIF to JPEG
    if ext in {'.heic', '.heif'}:
        pillow_heif.register_heif_opener()
        img = Image.open(image_path)

        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Save to bytes buffer as JPEG
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=95)
        buffer.seek(0)

        base64_string = base64.b64encode(buffer.read()).decode("utf-8")
        return base64_string, 'image/jpeg'

    # For other formats, encode directly
    with open(image_path, "rb") as image_file:
        base64_string = base64.b64encode(image_file.read()).decode("utf-8")

    mime_type = {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
    }.get(ext, 'image/jpeg')

    return base64_string, mime_type


def format_output(text: str) -> str:
    """Format output: wrap lines to 100 chars and bold storage types"""
    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        # Bold storage recommendations - more flexible regex
        line = re.sub(r'Storage:\s*(no protection|penny sleeve|top loader|special storage)',
                     r'Storage: **\1**', line, flags=re.IGNORECASE)

        # Wrap lines longer than 100 characters
        if len(line) > 100:
            # Try to break at pipe separator or space
            if ' | ' in line:
                parts = line.split(' | ')
                current_line = parts[0]
                for part in parts[1:]:
                    if len(current_line) + len(part) + 3 <= 100:
                        current_line += ' | ' + part
                    else:
                        formatted_lines.append(current_line)
                        current_line = part
                formatted_lines.append(current_line)
            else:
                # Break at last space before 100 chars
                while len(line) > 100:
                    break_point = line[:100].rfind(' ')
                    if break_point == -1:
                        break_point = 100
                    formatted_lines.append(line[:break_point])
                    line = line[break_point:].lstrip()
                if line:
                    formatted_lines.append(line)
        else:
            formatted_lines.append(line)

    result = '\n'.join(formatted_lines)

    # Remove excessive blank lines at the end (max one blank line between cards)
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result


def analyze_cards(image_path: str) -> str:
    """Send image to GPT-5.2 Vision and get storage recommendations."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Read and encode image (converts HEIC to JPEG if needed)
    base64_image, mime_type = encode_image(image_path)

    # Call GPT-5.2 Vision
    response = client.chat.completions.create(
        model="gpt-5.2-chat-latest",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        max_completion_tokens=4000
    )

    return response.choices[0].message.content


def main():
    downloads_dir = "/Users/harlan/Downloads"

    # Get image path from command line or find first image in Downloads
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        # Find image file with lowest number in Downloads
        image_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif'}
        downloads_path = Path(downloads_dir)

        image_files = [
            f for f in downloads_path.iterdir()
            if f.is_file() and f.suffix.lower() in image_extensions
        ]

        if not image_files:
            print(f"Error: No image files found in {downloads_dir}")
            sys.exit(1)

        # Extract numbers from filenames and sort by lowest number
        def get_number(filepath):
            numbers = re.findall(r'\d+', filepath.stem)
            return int(numbers[0]) if numbers else float('inf')

        image_path = str(sorted(image_files, key=get_number)[0])

    # Validate file exists
    if not os.path.exists(image_path):
        print(f"Error: File not found: {image_path}")
        sys.exit(1)

    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    print(f"\nAnalyzing: {image_path}")
    print("-" * 80)

    # Get recommendations
    result = analyze_cards(image_path)

    # Format output (add bold, enforce 100 char limit)
    formatted_result = format_output(result)

    # Save to txt file (overwrites previous run)
    output_file = Path(downloads_dir) / "baseball_card_storage.txt"

    with open(output_file, 'w') as f:
        f.write(f"Image: {Path(image_path).name}\n\n")
        f.write(formatted_result)

    # Display results
    print("\nSTORAGE RECOMMENDATIONS:\n")
    print(formatted_result)
    print("\n" + "-" * 80)
    print(f"\nSaved to: {output_file}")

    # Move processed image to unprocessed_bulk_back directory
    dest_dir = Path(__file__).parent.parent / "cards" / "unprocessed_bulk_back"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / Path(image_path).name

    shutil.move(image_path, dest_path)
    print(f"Moved processed image to: {dest_path}")


if __name__ == "__main__":
    main()
