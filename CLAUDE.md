# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Core Processing Pipeline
- `python -m app.run --raw` - Process raw trading card images from `images/raw_scans/` using GPT-4 Vision API
- `python -m app.run --undo` - Undo last processing operation (moves image back to raw_scans)
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
1. **Raw Scans** → `images/raw_scans/` - Original card images (JPG, PNG, HEIC)
2. **GPT Processing** → `images/pending_verification/` - AI-extracted card data as JSON + images
3. **Manual Verification** → React UI for reviewing and editing card data
4. **Database Storage** → Direct import to SQLite database when cards pass verification

### Verification UI Workflow
1. **View**: React UI displays card image alongside extracted data
2. **Edit**: Click "Edit Data" to modify any incorrect fields
3. **Verify**: Click "Pass" to approve and import to database, or "Fail" to reject
4. **Automatic Import**: Passed cards are immediately inserted into database with duplicate detection

### Key Components

**Image Processing Pipeline** (`app/run.py`, `app/utils.py`)
- Uses OpenAI GPT-4o with vision capabilities to extract card details
- Handles HEIC format conversion via pillow-heif
- Generates structured JSON for each detected card

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
- `DISABLE_TCDB_VERIFICATION` (optional) - Set to "true" to disable TCDB verification when the site is blocked
- Uses `.env` file for configuration loading