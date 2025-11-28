# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Core Processing Pipeline
- `python -m app.run --grid` - Process 3x3 grid card back images from `cards/unprocessed_bulk_back/` with single-pass GPT Vision extraction
- `python -m app.run --auto` - Auto-detect image types and process (recommended)
- `python -m app.run --undo` - Undo last processing operation
- `python -c "from app.database import init_db; init_db()"` - Initialize SQLite database with tables

### UI Server
- `cd app/ui && npm run dev` - Start both backend API and frontend concurrently
  - Backend API server: http://localhost:3001
  - React frontend: http://localhost:3000
- `cd app/ui && npm start` - Start backend API server only on port 3001
- `cd app/ui/client && npm start` - Start React frontend only on port 3000

## Architecture Overview

This is a trading card digitization system that uses GPT-4 Vision to extract structured data from scanned trading card images.

### Data Flow
1. **INPUT**: 3x3 Grid Backs in `cards/unprocessed_bulk_back/` - **ONLY RAW INPUT TO PIPELINE**
2. **PROCESSING**: Single-pass GPT-4 Vision extraction from grid back cards (9 cards per image)
3. **OUTPUT**: Structured JSON with extracted data → `cards/pending_verification/` + cropped individual back images
4. **VERIFICATION**: React UI for manual review and editing
5. **DATABASE**: Final import to SQLite database after verification

### Processing Approach
- **Single-Pass Extraction**: Each 3x3 grid is sent once to GPT-4 Vision with a simple, clear prompt
- **No Fallbacks**: No multi-tier processing, no enhanced/detailed modes, no learned corrections
- **No Front Matching**: Front images are not used for extraction or matching
- **Manual Verification**: UI displays cropped card backs for easy manual correction of any errors

### Verification UI Workflow
1. **View**: React UI displays card image alongside extracted data
2. **Edit**: Click "Edit Data" to modify any incorrect fields
3. **Verify**: Click "Pass" to approve and import to database, or "Fail" to reject
4. **Automatic Import**: Passed cards are immediately inserted into database with duplicate detection

### Key Components

**Simplified Image Processing Pipeline** (`app/run.py`, `app/grid_processor.py`)
- Uses OpenAI GPT-4o Vision API for single-pass extraction
- Simple, direct prompt asking for the database fields needed
- No image preprocessing, enhancement, or multi-pass validation
- No front-back matching, learned corrections, or checklist validation
- Cropped individual back images saved for UI verification
- Handles HEIC format conversion via pillow-heif
- Generates structured JSON with extracted data

**Database Layer** (`app/models.py`, `app/database.py`, `app/crud.py`)
- SQLAlchemy-based Card model with dynamic field injection
- SQLite backend with session management
- CRUD operations with upsert logic for duplicate detection

**Schema System** (`app/fields.py`, `app/schemas.py`)
- Shared field definitions between SQLAlchemy and Pydantic
- Separates creation fields from database-only fields (quantity, pricing, timestamps)
- Dynamic annotation system for consistent field handling

### Environment Requirements
- `OPENAI_API_KEY` environment variable required for GPT-4 Vision API
- `OPENAI_MODEL` (optional) - Model to use (default: "gpt-4o")
- Uses `.env` file for configuration loading