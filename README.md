# Trading Cards Database

A trading card digitization system that uses OpenAI vision models to extract structured data from scanned trading card images.

## Quick Start

### 1. Environment Setup
```bash
# Activate conda environment (recommended)
conda activate trading_cards_db

# Install Python dependencies (if needed)
pip install openai python-dotenv pillow-heif sqlalchemy pydantic opencv-python-headless

# Install Node.js dependencies for UI
cd app/ui && npm install
cd client && npm install
cd ../../..
```

### 2. Configuration
Create a `.env` file in the project root:
```
OPENAI_API_KEY=your-openai-api-key-here
# Choose the OpenAI model (defaults to gpt-4o); when available, set to gpt-5
OPENAI_MODEL=gpt-4o
# Speed/quality knobs (optional)
# Use fast heuristic price ranges during extraction (no extra API calls)
VALUE_ESTIMATE_MODE=heuristic   # gpt|heuristic|off
# Reduce reprocessing on strong first-pass results
FAST_MODE=true                  # true|false
# Limit front-image matching to cap API calls (per run)
FRONT_MATCH_MAX=60              # integer; omit to use default 60
```

### 3. Initialize Database
```bash
python -c "from app.database import init_db; init_db()"
```

## Core Workflow

### Process Trading Card Images
```bash
# Add images to cards/raw_scans/ directory first
# Then process them with the configured OpenAI model
python -m app.run --raw

# Undo last processing (if needed)
python -m app.run --undo
```

### Start Verification UI
```bash
# Single command to start both backend and frontend
cd app/ui
npm run dev
# Backend: http://localhost:3001
# Frontend: http://localhost:3000
```

### Backfill Price Estimates
```bash
# Populate value_estimate for existing rows (safe, fast heuristic by default)
python -m app.scripts.backfill_price_estimates

# Use GPT valuations instead (slower, higher quality)
VALUE_ESTIMATE_MODE=gpt python -m app.scripts.backfill_price_estimates
```

Notes:
- 3×3 back-grid photos placed in `cards/raw_scans/` are auto-detected and processed with the enhanced 3×3 pipeline.
- The JSON saved to `cards/pending_verification/` now uses the same basename as the source image so the UI associates them (e.g., `IMG_1234.jpg` → `IMG_1234.json`).
- TCDB lookups are used only to fill clear gaps (e.g., missing team/set) and are optional; set `DISABLE_TCDB_VERIFICATION=true` in `.env` to skip for maximum speed.

### Verification Process
1. Open http://localhost:3000 in your browser
2. Review extracted card data alongside the original image
3. Click "Edit Data" to modify any incorrect fields
4. Click "Pass" to approve and import to database
5. Click "Fail" to reject and delete files

## API Endpoints

### Get Pending Cards
```bash
curl http://localhost:3001/api/pending-cards
```

### Approve a Card
```bash
curl -X POST http://localhost:3001/api/pass/IMG_1795
```

### Reject a Card
```bash
curl -X POST http://localhost:3001/api/fail/IMG_1795
```

### Get Database Statistics
```bash
curl http://localhost:3001/api/database-stats
```

## Directory Structure
```
images/
├── raw_scans/          # Add new card images here
└── pending_verification/ # AI-extracted data awaiting review
```

## Features

### Core Features
- **Model-Configurable Vision Integration**: Automatic card data extraction (set `OPENAI_MODEL` to use newer models)
- **HEIC Support**: Full support for iPhone/Apple HEIC images with automatic conversion
- **Web UI**: Visual verification with editing capabilities
- **Duplicate Detection**: Automatically increments quantity for existing cards
- **Field Validation**: Dropdowns for conditions, boolean toggles for status
- **Undo Functionality**: Reverse last processing operation
- **Direct Database Import**: No intermediate verification steps

### Enhanced Extraction System (Active)
- **Multi-Pass Validation**: 2-pass GPT-4 extraction with confidence scoring
- **Checklist Validation**: 111 cards across 8 sets, validates against known checklists
- **Post-Extraction Learning**: Auto-corrects common mistakes from 201 previous corrections
- **Self-Improving**: Gets smarter with every verification session

See ENHANCED_EXTRACTION.md and CORRECTION_LEARNING.md for details.

## Development
- **Field Definitions**: All card fields defined in `app/fields.py`
- **Database Models**: SQLAlchemy models in `app/models.py`
- **API Schemas**: Pydantic validation in `app/schemas.py`
- **Processing Logic**: GPT integration in `app/utils.py`
