# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Core Processing Pipeline
- `python -m app.run --raw` - Process raw trading card images from `cards/raw_scans/` using GPT-4 Vision API
- `python -m app.run --grid` - Process 3x3 grid card back images from `cards/unprocessed_bulk_back/` with enhanced accuracy and front image matching from `cards/unprocessed_single_front/`
- `python -m app.run --auto` - Auto-detect image types and process with optimal methods (recommended)
- `python -m app.run --all` - Process all available images with appropriate methods
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
1. **INPUT**: 3x3 Grid Backs in `cards/unprocessed_bulk_back/` - **ONLY RAW INPUT TO PIPELINE**
2. **PROCESSING**: Enhanced GPT-4 Vision extraction from grid back cards (9 cards per image)
3. **AUTO-MATCHING**: System searches `cards/unprocessed_single_front/` for corresponding front images (read-only, no files moved)
4. **ENHANCEMENT**: Value estimation and TCDB verification
5. **OUTPUT**: Structured JSON with extracted data, matched front files, and value estimates → `cards/pending_verification/`
6. **VERIFICATION**: React UI for manual review and editing
7. **DATABASE**: Final import to SQLite database after verification

### Processing Priority System
1. **Primary Input**: Only 3x3 grid back images are processed as raw input
2. **Primary Data**: Card back text (name, team, number, stats, copyright year)
3. **Secondary Enhancement**: Front image matching (supplements missing data, no files moved)
4. **Tertiary Verification**: TCDB confirmation (validates accuracy)

### Verification UI Workflow
1. **View**: React UI displays card image alongside extracted data
2. **Edit**: Click "Edit Data" to modify any incorrect fields
3. **Verify**: Click "Pass" to approve and import to database, or "Fail" to reject
4. **Automatic Import**: Passed cards are immediately inserted into database with duplicate detection

### Key Components

**Advanced Image Processing Pipeline** (`app/run.py`, `app/utils.py`, `app/grid_processor.py`, `app/detailed_grid_processor.py`, `app/value_estimator.py`)
- Uses OpenAI GPT-4o with vision capabilities to extract maximum detail from card backs (primary)
- **Detailed Individual Card Processing**: 
  - Detects and extracts each of 9 cards individually from 3x3 grid
  - Applies single-card-level enhancement to each extracted card
  - Advanced contrast enhancement, noise reduction, and text sharpening
  - Optimal resizing for GPT-4 Vision analysis
  - Each card analyzed separately for maximum detail extraction
- **Multi-tier Processing Fallback**: Detailed → Enhanced → Standard processing with automatic fallback
- **Front-Back Matching**: Automatically matches individual front images with grid back cards (supplemental only)
- **GPT-Powered Value Estimation**: Real-time market value estimates using GPT-4's knowledge of current trading card markets
- **Multi-source Verification**: Integrates TCDB, Baseball Reference, and Sports Reference (tertiary verification)
- **Data Prioritization**: Individual card back analysis is primary source, front images supplement missing data only
- Handles HEIC format conversion via pillow-heif
- Generates structured JSON with enhanced accuracy, confidence scoring, and value estimates
- Optional cropped individual back image extraction

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