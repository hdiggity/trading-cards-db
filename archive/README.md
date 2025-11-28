# Archive

This directory contains old/unused scripts that have been archived from the trading cards database project.

## Archived Scripts

### app_scripts/
Scripts that were part of the old complex extraction pipeline that has been simplified:

- **accuracy_boost.py** - Learning corrections system (replaced by manual verification)
- **auto_retrain.py** - Automatic model retraining
- **backfill_price_estimates.py** - Batch price estimation backfill
- **batch_price_refresh.py** - Batch price refresh functionality
- **checklist_importer.py** - Card checklist import (relied on card_set_database)
- **condition_model_trainer.py** - ML-based condition prediction training
- **condition_predictor.py** - ML-based condition prediction
- **image_enhancement.py** - Image preprocessing (not needed for GPT-4 Vision)
- **learning.py** - Learning prompt enhancements system
- **migrate_remove_columns.py** - Database migration script
- **populate_checklists.py** - Checklist population
- **tcdb_scraper.py** - TCDB web scraping
- **update_conditions_with_model.py** - Update conditions using ML model

### scripts/
Utility scripts:

- **export_unique_cards.py** - Export unique cards
- **split_verified_json.py** - Split verified JSON files
- **standardize_verified_files.py** - Standardize verified files

### physical_storage_scripts/
Physical storage analysis scripts:

- **bulk_back_analysis.py** - Bulk back analysis
- **single_card_analysis.py** - Single card analysis

### tests/
Test files for archived functionality:

- **test_enhanced_extraction.py** - Tests for multi-pass extraction
- **test_validation.py** - Validation tests

## Why These Were Archived

The project was simplified to use a single-pass GPT-4 Vision extraction instead of the complex multi-tier system with:
- Multi-pass extraction and validation
- Learned corrections
- Checklist validation
- Image preprocessing
- Front-back matching
- ML-based condition prediction

The new simplified approach:
1. Send 3x3 grid to GPT-4 Vision once
2. Get JSON with 9 cards
3. Crop individual backs for UI verification
4. Manual verification in UI catches any errors

## Restoration

If any of these scripts are needed in the future, they can be moved back from this archive directory.

### Additional Archived Files:

- **utils_old.py** (1275 lines) - Original complex utils.py with multi-pass extraction, image enhancement, TCDB scraping, and value estimation. Replaced with minimal 14-line version that only provides OpenAI client.

## Current Active Files

After simplification, only these files remain active:

### Core Pipeline:
- `app/grid_processor.py` - Single-pass GPT Vision extraction (280 lines)
- `app/run.py` - Entry point for processing
- `app/utils.py` - Minimal utilities (14 lines, just OpenAI client)

### Database:
- `app/database.py` - DB connection
- `app/models.py` - SQLAlchemy models
- `app/schemas.py` - Pydantic schemas
- `app/fields.py` - Field definitions
- `app/crud.py` - CRUD operations

### Supporting:
- `app/logging_system.py` - Logging
- `app/team_map.py` - Team name canonicalization
- `app/db_backup.py` - Database backup
- `app/per_card_export.py` - Per-card file export (stub)

### Compatibility Stubs:
- `app/accuracy_boost.py` - Stub for server.js
- `app/scripts/backfill_price_estimates.py` - Stub endpoint
- `app/scripts/batch_price_refresh.py` - Stub endpoint

Date archived: 2025-11-28
