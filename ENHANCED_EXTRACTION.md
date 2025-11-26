# Enhanced Card Extraction System

## Overview

The enhanced extraction system uses multi-pass GPT-4 validation and confidence scoring to vastly improve name extraction accuracy without relying on external card set databases.

## Status: IMPLEMENTED AND ACTIVE

The enhanced extraction system with checklist validation is now fully integrated and active in the processing pipeline.

## Key Improvements

### 1. Multi-Pass Extraction
- **Pass 1**: Visual analysis with explicit location identification
  - Asks GPT-4 to describe WHERE it sees the player name
  - Forces the model to think about what it's reading
  - Includes confidence scoring for each field

- **Pass 2**: Focused verification
  - Challenges the first result
  - Asks: "Could this be a team name instead?"
  - Verifies the extraction makes sense as a player name
  - Can correct mistakes from Pass 1

- **Pass 3**: Ensemble voting
  - Combines results from multiple passes
  - Higher confidence results get more weight
  - Reduces random errors

### 2. Error Prevention
The system explicitly prevents common mistakes:
- Reading team names as player names (Cleveland Indians → not a player)
- Reading positions as names (Third Base → not a player)
- Reading biographical text as names
- Reading stats headers as names

### 3. Visual Grounding
Forces GPT-4 to describe what it sees before extracting:
- "At the top center, I see large text that says..."
- Ensures the model is actually reading the correct text
- Helps catch mistakes early

### 4. Confidence Scoring
Every extraction includes confidence scores (0-100):
- Name confidence
- Number confidence
- Team confidence
- Year confidence
- Overall confidence

Low confidence fields are flagged for manual review.

### 5. Checklist Validation
Validates extracted names against card set checklists:
- Exact matches get +20% confidence boost
- Fuzzy matches (OCR errors) show suggestions for correction
- Mismatches get -30% confidence penalty and flag for review
- Uses your existing verified cards to build partial checklists
- Currently has 111 cards across 8 different sets (1970-1989 Topps)

Validation statuses:
- verified_exact: Perfect match with checklist
- verified_fuzzy: Similar match (>80% similarity), shows suggestion
- mismatch: Wrong name extracted, shows expected name
- no_checklist: Card set not in database yet

### 6. Post-Extraction Correction Learning
Automatically corrects common mistakes AFTER extraction:
- Applies learned corrections from 201 manual fixes
- GPT works naturally without pre-loaded patterns
- Corrections applied post-extraction based on high-confidence patterns
- Self-improving with every verification session
- No configuration required - fully automatic

Current learning:
- Corrections that occurred 2+ times are auto-applied
- Applied after GPT extraction, before validation
- Logged in _auto_corrections field when applied
- Zero API cost increase

See CORRECTION_LEARNING.md for full details.

## Usage

### Enable Enhanced Extraction
Set environment variable:
```bash
export USE_ENHANCED_EXTRACTION=true
```

Or in .env file:
```
USE_ENHANCED_EXTRACTION=true
```

### Process Cards
The enhanced extraction is now the default first attempt in the pipeline:
```python
python -m app.run --grid
```

The system will:
1. Try enhanced multi-pass extraction (NEW)
2. Fall back to simple GPT extraction if needed
3. Fall back to detailed processing if needed
4. Fall back to enhanced grid processing if needed
5. Fall back to standard processing as last resort

### Disable Enhanced Extraction
To use the original extraction method:
```bash
export USE_ENHANCED_EXTRACTION=false
```

## Performance

### Expected Improvements
- **Name accuracy**: 70% → 90%+
- **Reduced false positives**: Fewer team names extracted as player names
- **Better confidence**: Know which extractions are uncertain
- **Fewer manual corrections**: More cards pass verification on first try

### Cost Considerations
Enhanced extraction uses 2 GPT-4 calls per grid instead of 1:
- Pass 1: Visual analysis (~800 tokens)
- Pass 2: Verification (~600 tokens)
- Total: ~1400 tokens per grid vs ~700 for simple extraction

Approximately 2x cost but significantly higher accuracy.

## Implementation Details

### Files
- `app/enhanced_extraction.py` - Multi-pass extraction logic
- `app/grid_processor.py` - Integration into main pipeline

### Prompting Strategy

**Pass 1 - Visual Analysis**:
```
1. LOCATE THE PLAYER NAME:
   - Scan the card from TOP to BOTTOM
   - The player name is usually the LARGEST TEXT or in ALL CAPS
   - Describe what you see: "At the top center, I see large text that says..."

2. AVOID COMMON MISTAKES:
   - DO NOT read team names as player names
   - DO NOT read positions as names
   - DO NOT read biographical text as names
```

**Pass 2 - Verification**:
```
1. WHERE exactly on the card do you see this name?
2. WHAT ELSE is near this text?
3. CHALLENGE: Could this actually be something else?
4. VERIFICATION: Does this sound like a person's name?
```

### Confidence Scoring
- Visual description quality: Higher confidence if model describes location clearly
- Name verification: Higher confidence if verification pass agrees
- Ensemble voting: Higher confidence if multiple passes agree
- Overall: Average of all field confidences

## Checklist Database

### Current Status
- 111 cards across 8 sets
- Sets: 1970-1989 Topps Baseball
- Bootstrapped from your existing verified cards

### Managing Checklists

Import from existing cards:
```bash
python -m app.checklist_importer
# Select option 1: Import from existing verified cards
```

Import from CSV:
```bash
python -m app.checklist_importer
# Select option 2: Import from CSV file
```

CSV format:
```csv
brand,year,card_number,player_name,team,card_type,subset
topps,1984,1,tony gwynn,san diego padres,player,
topps,1984,2,steve garvey,san diego padres,player,
```

Check available sets:
```bash
PYTHONPATH=. python -c "
from app.card_set_database import CardSetDatabase
db = CardSetDatabase()
sets = db.get_available_sets()
for brand, year, set_name, total in sets:
    print(f'{year} {brand} {set_name}: {len(db.get_set_checklist(brand, year, set_name))} cards')
db.close()
"
```

### Growing the Database
The checklist database automatically grows as you verify more cards. Each time you process and verify a new card, it gets added to the checklist for future validation.

## Future Enhancements

### Phase 2 (Future)
- Individual card extraction from grid (more accurate, slower)
- Grid-based cross-validation
- Learning from manual corrections
- Set-specific prompting when year/brand identified

### Phase 3 (Future)
- Card set database integration for validation
- Historical correction patterns
- Automated reprocessing of low-confidence cards

## Testing

Test on a single grid:
```bash
PYTHONPATH=. python -c "
from app.enhanced_extraction import enhanced_extract_grid
result = enhanced_extract_grid('path/to/grid.jpg')
for card in result:
    print(f'{card[\"grid_position\"]}: {card[\"name\"]} (conf: {card.get(\"_confidence\", {}).get(\"name\", 0):.1f})')
"
```

Compare old vs new:
```bash
# Old method
export USE_ENHANCED_EXTRACTION=false
python -m app.run --grid

# New method
export USE_ENHANCED_EXTRACTION=true
python -m app.run --grid
```

## Troubleshooting

### Enhanced extraction taking too long
- Disable for faster processing: `USE_ENHANCED_EXTRACTION=false`
- Trade-off: Speed vs accuracy

### Still getting incorrect names
- Check confidence scores in output
- Low confidence (<60) likely needs manual review
- Consider enabling individual card extraction (future feature)

### All extractions showing unknown
- Enhanced extraction automatically falls back to simple method
- Check if simple extraction is also failing
- May need better image quality or different approach
