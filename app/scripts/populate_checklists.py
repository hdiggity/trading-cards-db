"""Populate checklists.db with full Topps baseball set data 1970-2000.

Uses GPT-4 to generate accurate checklist data for vintage Topps sets.
Run with: python -m app.scripts.populate_checklists
"""

import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

CHECKLISTS_DB = Path(__file__).parent.parent.parent / "data" / "checklists.db"


def get_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    return OpenAI(api_key=api_key)


def get_set_id(conn, year, brand="topps"):
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM card_sets WHERE year = ? AND brand = ?",
        (year, brand)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def count_cards_in_set(conn, set_id):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM set_cards WHERE set_id = ?", (set_id,))
    return cursor.fetchone()[0]


def fetch_checklist_from_gpt(client, year, total_cards, start_num=1, batch_size=100, max_retries=3):
    """Fetch a batch of checklist entries from GPT with retry logic."""
    import time
    end_num = min(start_num + batch_size - 1, total_cards)

    prompt = f"""List the {year} Topps Baseball cards from #{start_num} to #{end_num}.
For each card, provide the card number, player name, and team.

Return ONLY a JSON array with this exact format (no markdown, no explanation):
[
  {{"number": "1", "name": "Player Name", "team": "Team Name"}},
  ...
]

Important:
- Use official player names as they appeared on the cards
- Use team names as abbreviated on the cards (e.g., "Yankees", "Red Sox")
- For multi-player cards, list the primary name
- For special cards (league leaders, checklists, etc.), use descriptive names
- Include ALL cards in the range, including checklists and special cards"""

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a baseball card expert with encyclopedic knowledge of vintage Topps sets. Provide accurate checklist data."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=4000,
                temperature=0.1
            )

            text = response.choices[0].message.content.strip()

            # Clean JSON if wrapped in markdown
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            return json.loads(text)
        except Exception as e:
            print(f"Error fetching cards {start_num}-{end_num} for {year} (attempt {attempt+1}/{max_retries}): {e}", file=sys.stderr)
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                return []
    return []


def populate_year(conn, client, year, total_cards, batch_size=100):
    """Populate all cards for a given year."""
    set_id = get_set_id(conn, year)
    if not set_id:
        print(f"No set found for {year} Topps", file=sys.stderr)
        return

    existing = count_cards_in_set(conn, set_id)
    if existing >= total_cards * 0.99:  # Only skip if essentially complete
        print(f"{year} Topps already has {existing}/{total_cards} cards - skipping")
        return

    # Clear existing partial data
    cursor = conn.cursor()
    cursor.execute("DELETE FROM set_cards WHERE set_id = ?", (set_id,))
    conn.commit()

    print(f"Populating {year} Topps ({total_cards} cards)...")

    all_cards = []
    for start in range(1, total_cards + 1, batch_size):
        cards = fetch_checklist_from_gpt(client, year, total_cards, start, batch_size)
        all_cards.extend(cards)
        print(f"  Fetched cards {start}-{min(start+batch_size-1, total_cards)}: {len(cards)} cards")

    # Insert into database
    for card in all_cards:
        try:
            cursor.execute(
                "INSERT INTO set_cards (set_id, card_number, player_name, team) VALUES (?, ?, ?, ?)",
                (set_id, str(card.get("number", "")), card.get("name", ""), card.get("team", ""))
            )
        except Exception as e:
            print(f"  Error inserting card {card}: {e}", file=sys.stderr)

    conn.commit()
    final_count = count_cards_in_set(conn, set_id)
    print(f"  Inserted {final_count} cards for {year} Topps")


def add_missing_sets(conn):
    """Add missing sets for 1991-2000."""
    cursor = conn.cursor()

    sets_to_add = [
        (1991, "topps", "1991 Topps", 792),
        (1992, "topps", "1992 Topps", 792),
        (1993, "topps", "1993 Topps", 825),
        (1994, "topps", "1994 Topps", 792),
        (1995, "topps", "1995 Topps", 660),
        (1996, "topps", "1996 Topps", 440),
        (1997, "topps", "1997 Topps", 495),
        (1998, "topps", "1998 Topps", 504),
        (1999, "topps", "1999 Topps", 462),
        (2000, "topps", "2000 Topps", 478),
    ]

    for year, brand, name, total in sets_to_add:
        cursor.execute(
            "SELECT id FROM card_sets WHERE year = ? AND brand = ?",
            (year, brand)
        )
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO card_sets (year, brand, set_name, sport, total_cards, source) VALUES (?, ?, ?, ?, ?, ?)",
                (year, brand, name, "baseball", total, "seed")
            )
            print(f"Added set: {name}")

    conn.commit()


def main():
    if not CHECKLISTS_DB.exists():
        print(f"Database not found: {CHECKLISTS_DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(CHECKLISTS_DB))
    client = get_client()

    # Add missing sets first
    add_missing_sets(conn)

    # Get all sets that need populating
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cs.year, cs.total_cards, COUNT(sc.id) as card_count
        FROM card_sets cs
        LEFT JOIN set_cards sc ON cs.id = sc.set_id
        WHERE cs.brand = 'topps' AND cs.year BETWEEN 1970 AND 2000
        GROUP BY cs.id
        ORDER BY cs.year
    """)

    sets = cursor.fetchall()

    for year, total_cards, existing_count in sets:
        if existing_count < total_cards * 0.9:
            populate_year(conn, client, year, total_cards)
        else:
            print(f"{year} Topps: {existing_count}/{total_cards} cards - OK")

    conn.close()
    print("\nDone!")


if __name__ == "__main__":
    main()
