# Trading Cards Database

A trading card digitization system that uses GPT-4 Vision to extract structured data from scanned trading card images.

## Quick Start

### 1. Environment Setup
```bash
# Activate conda environment
conda activate trading_cards_db

# Install Python dependencies (if needed)
pip install openai python-dotenv pillow-heif sqlalchemy pydantic

# Install Node.js dependencies for UI
cd app/ui && npm install
cd client && npm install
cd ../../..
```

### 2. Configuration
Create a `.env` file in the project root:
```
OPENAI_API_KEY=your-openai-api-key-here
```

### 3. Initialize Database
```bash
python -c "from app.database import init_db; init_db()"
```

## Core Workflow

### Process Trading Card Images
```bash
# Add images to images/raw_scans/ directory first
# Then process them with GPT-4 Vision
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
- **GPT-4 Vision Integration**: Automatic card data extraction
- **HEIC Support**: Full support for iPhone/Apple HEIC images with automatic conversion
- **Web UI**: Visual verification with editing capabilities  
- **Duplicate Detection**: Automatically increments quantity for existing cards
- **Field Validation**: Dropdowns for conditions, boolean toggles for status
- **Undo Functionality**: Reverse last processing operation
- **Direct Database Import**: No intermediate verification steps

## Development
- **Field Definitions**: All card fields defined in `app/fields.py`
- **Database Models**: SQLAlchemy models in `app/models.py`
- **API Schemas**: Pydantic validation in `app/schemas.py`
- **Processing Logic**: GPT integration in `app/utils.py`
