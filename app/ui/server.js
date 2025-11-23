const express = require('express');
const cors = require('cors');
const fs = require('fs').promises;
const fsSync = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const multer = require('multer');

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json());

// Canonicalize team names (JS side) for reprocess normalization
const TEAM_CANON = {
  // MLB
  'indians': 'cleveland indians', 'guardians': 'cleveland guardians', 'rangers': 'texas rangers', 'twins': 'minnesota twins',
  'athletics': 'oakland athletics', "a's": 'oakland athletics', 'angels': 'california angels', 'royals': 'kansas city royals',
  'yankees': 'new york yankees', 'mets': 'new york mets', 'dodgers': 'los angeles dodgers', 'giants': 'san francisco giants',
  'padres': 'san diego padres', 'phillies': 'philadelphia phillies', 'pirates': 'pittsburgh pirates', 'cardinals': 'st. louis cardinals',
  'cubs': 'chicago cubs', 'white sox': 'chicago white sox', 'red sox': 'boston red sox', 'brewers': 'milwaukee brewers',
  'braves': 'atlanta braves', 'reds': 'cincinnati reds', 'orioles': 'baltimore orioles', 'mariners': 'seattle mariners',
  'blue jays': 'toronto blue jays', 'expos': 'montreal expos', 'nationals': 'washington nationals', 'rockies': 'colorado rockies',
  'diamondbacks': 'arizona diamondbacks', 'tigers': 'detroit tigers', 'marlins': 'miami marlins', 'rays': 'tampa bay rays',
  // NBA
  'lakers': 'los angeles lakers', 'clippers': 'los angeles clippers', 'celtics': 'boston celtics', 'knicks': 'new york knicks',
  'bulls': 'chicago bulls', 'warriors': 'golden state warriors',
  // NFL
  'patriots': 'new england patriots', 'giants': 'new york giants', 'jets': 'new york jets', 'cowboys': 'dallas cowboys',
  'packers': 'green bay packers', 'browns': 'cleveland browns',
  // NHL
  'canadiens': 'montreal canadiens', 'maple leafs': 'toronto maple leafs', 'red wings': 'detroit red wings', 'bruins': 'boston bruins',
  'rangers_nhl': 'new york rangers'
};

function canonicalizeTeamJS(team, sport) {
  if (!team || typeof team !== 'string') return team;
  let t = team.trim().toLowerCase().replace('st.louis', 'st. louis');
  if (t.includes(' ')) return t; // already city + team form
  // NHL rangers disambiguation is limited; prefer MLB by default
  if (t === 'rangers' && sport && sport.toLowerCase() === 'hockey') return TEAM_CANON['rangers_nhl'];
  return TEAM_CANON[t] || t;
}

function normalizeCardJS(card) {
  const out = { ...card };
  const lower = (v) => typeof v === 'string' ? v.toLowerCase().trim() : v;
  for (const k of ['name','sport','brand','team','card_set','condition']) {
    if (out[k] != null) out[k] = lower(out[k]);
  }
  if (out.team) out.team = canonicalizeTeamJS(out.team, out.sport);
  if (typeof out.features === 'string') {
    const feats = out.features.split(',').map(s => s.trim().toLowerCase().replace('_',' ')).filter(Boolean);
    out.features = feats.length ? Array.from(new Set(feats)).join(',') : 'none';
  }
  // card_set: set to 'n/a' if it only contains brand/year tokens
  try {
    const cs = (out.card_set || '').toLowerCase();
    const br = (out.brand || '').toLowerCase();
    if (cs) {
      let leftovers = cs.replace(br, '');
      leftovers = leftovers.replace(/\b(19\d{2}|20\d{2})\b/g, '');
      leftovers = leftovers.replace(/[^a-z]+/g, ' ').trim();
      if (leftovers === '') out.card_set = 'n/a';
    }
  } catch (_) {}
  return out;
}

// ============================================================================
// Verification History System - Persistent Save & Undo
// ============================================================================
const VERIFICATION_HISTORY_DIR = path.join(__dirname, '../../data/verification_history');

// Ensure history directory exists
(async () => {
  try {
    await fs.mkdir(VERIFICATION_HISTORY_DIR, { recursive: true });
  } catch (e) {}
})();

// Record a verification action to history (enables undo)
async function recordVerificationAction(fileId, action, beforeData, afterData, cardIndex = null) {
  const historyFile = path.join(VERIFICATION_HISTORY_DIR, `${fileId}_history.json`);
  let history = [];

  try {
    const existing = await fs.readFile(historyFile, 'utf8');
    history = JSON.parse(existing);
  } catch (e) {
    // File doesn't exist yet, start fresh
  }

  const entry = {
    timestamp: new Date().toISOString(),
    action, // 'edit', 'pass_card', 'pass_all', 'fail_card', 'fail_all'
    cardIndex,
    beforeData: JSON.parse(JSON.stringify(beforeData)),
    afterData: afterData ? JSON.parse(JSON.stringify(afterData)) : null
  };

  history.push(entry);

  // Keep last 50 actions per file
  if (history.length > 50) {
    history = history.slice(-50);
  }

  await fs.writeFile(historyFile, JSON.stringify(history, null, 2));
  console.log(`[history] Recorded ${action} for ${fileId}, ${history.length} total actions`);
  return entry;
}

// Get verification history for a file
async function getVerificationHistory(fileId) {
  const historyFile = path.join(VERIFICATION_HISTORY_DIR, `${fileId}_history.json`);
  try {
    const data = await fs.readFile(historyFile, 'utf8');
    return JSON.parse(data);
  } catch (e) {
    return [];
  }
}

// Undo last action for a file (restores beforeData)
async function undoLastAction(fileId) {
  const historyFile = path.join(VERIFICATION_HISTORY_DIR, `${fileId}_history.json`);
  let history = [];

  try {
    const data = await fs.readFile(historyFile, 'utf8');
    history = JSON.parse(data);
  } catch (e) {
    return { success: false, error: 'No history found' };
  }

  if (history.length === 0) {
    return { success: false, error: 'No actions to undo' };
  }

  const lastAction = history.pop();

  // Save updated history (without the undone action)
  await fs.writeFile(historyFile, JSON.stringify(history, null, 2));

  return {
    success: true,
    undoneAction: lastAction,
    remainingActions: history.length
  };
}

// Record corrections for learning system
async function recordCorrections(originalCard, modifiedCard) {
  // Fields to track corrections for
  const trackFields = ['name', 'brand', 'team', 'card_set', 'copyright_year', 'number', 'condition', 'sport'];
  const corrections = [];

  // Use _original_extraction if available (captures what AI actually extracted)
  // Otherwise fall back to comparing originalCard directly
  const aiExtraction = originalCard._original_extraction || originalCard;

  for (const field of trackFields) {
    const orig = aiExtraction[field];
    const modified = modifiedCard[field];
    // Normalize for comparison (lowercase, trim)
    const origNorm = orig?.toString().toLowerCase().trim() || '';
    const modNorm = modified?.toString().toLowerCase().trim() || '';
    if (origNorm !== modNorm && modNorm !== '') {
      corrections.push({ field, original: orig, corrected: modified });
    }
  }

  if (corrections.length === 0) return;

  // Build context for the correction
  const context = {
    brand: modifiedCard.brand || originalCard.brand,
    copyright_year: modifiedCard.copyright_year || originalCard.copyright_year,
    sport: modifiedCard.sport || originalCard.sport,
    card_set: modifiedCard.card_set || originalCard.card_set
  };

  // Call Python to record corrections
  const pythonCode = `
import sys, json
from app.accuracy_boost import record_correction
data = json.loads(sys.stdin.read())
for corr in data['corrections']:
    record_correction(corr['field'], corr['original'], corr['corrected'], data['context'])
print(f"Recorded {len(data['corrections'])} corrections")
`;

  return new Promise((resolve) => {
    const pythonProcess = spawn('python', ['-c', pythonCode], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });
    pythonProcess.stdin.write(JSON.stringify({ corrections, context }));
    pythonProcess.stdin.end();
    pythonProcess.on('close', () => resolve());
    pythonProcess.on('error', () => resolve());
  });
}

// Configure multer for file uploads
const storage = multer.diskStorage({
  destination: function (req, file, cb) {
    const rawScansPath = path.join(__dirname, '../../cards/raw_scans');
    cb(null, rawScansPath);
  },
  filename: function (req, file, cb) {
    // Keep original filename with timestamp prefix to avoid conflicts
    // Remove problematic characters from timestamp and filename
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
    const sanitizedFilename = file.originalname.replace(/['"\\]/g, '_');
    cb(null, `${timestamp}_${sanitizedFilename}`);
  }
});

// Reprocess status endpoint
app.get('/api/reprocess-status/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const active = REPROCESS_JOBS.has(id);
    res.json({ active });
  } catch (e) {
    res.status(500).json({ active: false, error: 'Failed to get reprocess status' });
  }
});

// Cancel active reprocess
app.post('/api/cancel-reprocess/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const child = REPROCESS_JOBS.get(id);
    if (!child) return res.status(400).json({ error: 'No active reprocess for this id' });
    let terminated = false;
    try { process.kill(-child.pid, 'SIGTERM'); terminated = true; } catch (e1) {
      try { process.kill(child.pid, 'SIGTERM'); terminated = true; } catch (e2) {
        try { process.kill(child.pid, 'SIGKILL'); terminated = true; } catch (_) {}
      }
    }
    try { REPROCESS_JOBS.delete(id); } catch (_) {}
    res.json({ success: true, terminated });
  } catch (e) {
    res.status(500).json({ error: 'Failed to cancel reprocess' });
  }
});

const upload = multer({ 
  storage: storage,
  limits: {
    fileSize: 50 * 1024 * 1024, // 50MB limit
  },
  fileFilter: function (req, file, cb) {
    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/heic', 'image/heif', 'image/webp', 'image/tiff', 'image/bmp'];
    const allowedExtensions = ['.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp', '.tiff', '.tif', '.bmp'];
    
    const hasValidType = allowedTypes.includes(file.mimetype);
    const hasValidExtension = allowedExtensions.some(ext => 
      file.originalname.toLowerCase().endsWith(ext)
    );
    
    if (hasValidType || hasValidExtension) {
      cb(null, true);
    } else {
      cb(new Error(`Unsupported file type: ${file.originalname}`), false);
    }
  }
});

// Serve static images with HEIC conversion
app.get('/cards/*', async (req, res) => {
  try {
    const imagePath = path.join(__dirname, '../../cards', req.params[0]);
    const fileExtension = path.extname(imagePath).toLowerCase();
    
    // Check if file exists
    try {
      await fs.access(imagePath);
    } catch {
      return res.status(404).send('Image not found');
    }
    
    if (fileExtension === '.heic') {
      // Convert HEIC to JPEG for browser display
      const pythonProcess = spawn('python', ['-c', `
import sys
from PIL import Image
from pillow_heif import register_heif_opener
import io

register_heif_opener()

try:
    image = Image.open("${imagePath}")
    output_buffer = io.BytesIO()
    image.convert('RGB').save(output_buffer, format='JPEG', quality=100, optimize=False)
    sys.stdout.buffer.write(output_buffer.getvalue())
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    sys.exit(1)
      `], {
        cwd: path.join(__dirname, '../..'),
        stdio: ['pipe', 'pipe', 'pipe']
      });
      
      res.setHeader('Content-Type', 'image/jpeg');
      pythonProcess.stdout.pipe(res);
      
      pythonProcess.stderr.on('data', (data) => {
        console.error('HEIC conversion error:', data.toString());
      });
      
      pythonProcess.on('close', (code) => {
        if (code !== 0) {
          res.status(500).send('Error converting HEIC image');
        }
      });
    } else {
      // Serve other image formats normally
      res.sendFile(imagePath);
    }
  } catch (error) {
    console.error('Error serving image:', error);
    res.status(500).send('Error serving image');
  }
});

// Base paths
const PENDING_VERIFICATION_DIR = path.join(__dirname, '../../cards/pending_verification');
const PENDING_BULK_BACK_DIR = path.join(PENDING_VERIFICATION_DIR, 'pending_verification_bulk_back');
// Standardized verified directories
const VERIFIED_ROOT_DIR = path.join(__dirname, '../../cards/verified');
const VERIFIED_IMAGES_DIR = path.join(VERIFIED_ROOT_DIR, 'verified_bulk_back');
const UNPROCESSED_BULK_BACK_DIR = path.join(__dirname, '../../cards/unprocessed_bulk_back');
const AUDIT_LOG = path.join(__dirname, '../../logs/audit.log');

// Helper to create verified filename: strips timestamp prefix and adds "verified_" prefix
// e.g., "2025-08-31T02-36-26-430Z_IMG_2068.HEIC" -> "verified_IMG_2068.HEIC"
function getVerifiedFilename(originalFilename) {
  // Match timestamp prefix pattern: YYYY-MM-DDTHH-MM-SS-MMMZ_
  const timestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z_/;
  const stripped = originalFilename.replace(timestampPattern, '');
  return `verified_${stripped}`;
}

// Ensure directories exist
async function ensureDirectories() {
  try {
    await fs.mkdir(PENDING_VERIFICATION_DIR, { recursive: true });
    await fs.mkdir(PENDING_BULK_BACK_DIR, { recursive: true });
    await fs.mkdir(VERIFIED_ROOT_DIR, { recursive: true });
    await fs.mkdir(VERIFIED_IMAGES_DIR, { recursive: true });
    await fs.mkdir(path.dirname(AUDIT_LOG), { recursive: true });
  } catch (error) {
    console.error('Error creating directories:', error);
  }
}

// Lightweight audit logger (JSON Lines)
async function audit(action, payload = {}) {
  try {
    const entry = {
      ts: new Date().toISOString(),
      action,
      ...payload,
    };
    await fs.appendFile(AUDIT_LOG, JSON.stringify(entry) + '\n');
  } catch (e) {
    // avoid failing API for audit errors
  }
}

// Get all pending cards with their images and JSON data
app.get('/api/pending-cards', async (req, res) => {
  try {
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    const jsonFiles = pendingFiles.filter(file => file.endsWith('.json'));

    // Get image files from bulk back subdirectory
    let imageFiles = [];
    try {
      imageFiles = await fs.readdir(PENDING_BULK_BACK_DIR);
    } catch (e) {
      // Directory may not exist yet
    }

    const cards = [];

    for (const jsonFile of jsonFiles) {
      const baseName = path.parse(jsonFile).name;

      // Look for corresponding image file in bulk back directory
      const imageFile = imageFiles.find(file => {
        const imgBaseName = path.parse(file).name;
        const imgExt = path.parse(file).ext.toLowerCase();
        return imgBaseName === baseName && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
      });

      if (imageFile) {
        // Read JSON data
        const jsonPath = path.join(PENDING_VERIFICATION_DIR, jsonFile);
        const jsonData = JSON.parse(await fs.readFile(jsonPath, 'utf8'));

        cards.push({
          id: baseName,
          jsonFile,
          imageFile,
          data: jsonData
        });
      }
    }

    res.json(cards);
  } catch (error) {
    console.error('Error fetching pending cards:', error);
    res.status(500).json({ error: 'Failed to fetch pending cards' });
  }
});

// Upload raw scan images endpoint
app.post('/api/upload-raw-scans', async (req, res) => {
  // Ensure raw_scans directory exists BEFORE multer processes files
  const rawScansPath = path.join(__dirname, '../../cards/raw_scans');
  try {
    await fs.access(rawScansPath);
  } catch {
    await fs.mkdir(rawScansPath, { recursive: true });
  }

  upload.array('images')(req, res, async (err) => {
    if (err) {
      console.error('Multer upload error:', err);
      return res.status(400).json({ 
        error: 'Upload failed: ' + err.message 
      });
    }
    
    try {
      if (!req.files || req.files.length === 0) {
        return res.status(400).json({ error: 'No files uploaded' });
      }

    const uploadedFiles = req.files.map(file => ({
      originalName: file.originalname,
      filename: file.filename,
      path: file.path,
      size: file.size
    }));

    // Log each upload into UploadHistory + system logs
    try {
      const pythonCode = `
import sys, json
from app.logging_system import logger
files = json.loads(sys.stdin.read())
for f in files:
    try:
        logger.log_upload(
            filename=f.get('filename') or f.get('originalName'),
            original_path=f.get('path'),
            file_size=f.get('size'),
            file_type=(f.get('filename') or '').split('.')[-1]
        )
    except Exception as e:
        print(f"Upload log failed: {e}", file=sys.stderr)
print("OK")
      `;
      const pythonProcess = spawn('python', ['-c', pythonCode], {
        cwd: path.join(__dirname, '../..'),
        stdio: ['pipe', 'pipe', 'pipe']
      });
      pythonProcess.stdin.write(JSON.stringify(uploadedFiles));
      pythonProcess.stdin.end();
      pythonProcess.stderr.on('data', (d) => console.error('upload log err:', d.toString()));
    } catch (logError) {
      console.error('Error logging upload action:', logError);
    }

    // Audit
    try { await audit('upload_raw_scans', { count: req.files.length }); } catch {}
    res.json({
      success: true,
      message: `Successfully uploaded ${req.files.length} file(s)`,
      files: uploadedFiles
    });

    } catch (error) {
      console.error('Upload error:', error);
      res.status(500).json({ 
        error: error.message || 'Failed to upload files'
      });
    }
  });
});

// Handle Pass action for single card
app.post('/api/pass-card/:id/:cardIndex', async (req, res) => {
  try {
    const { id, cardIndex } = req.params;
    const { modifiedData } = req.body;

    // Find the files - JSONs in pending root, images in bulk back subdirectory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    let bulkBackFiles = [];
    try { bulkBackFiles = await fs.readdir(PENDING_BULK_BACK_DIR); } catch (e) {}

    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    // Find corresponding image file early so we can pass it to learning process
    const imageFileEarly = bulkBackFiles.find(file => {
      const imgBaseName = path.parse(file).name;
      const imgExt = path.parse(file).ext.toLowerCase();
      return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
    });

    if (!jsonFile) {
      return res.status(404).json({ error: 'Card data file not found' });
    }

    // Get the current card data
    const jsonPath = path.join(PENDING_VERIFICATION_DIR, jsonFile);
    let allCardData = JSON.parse(await fs.readFile(jsonPath, 'utf8'));
    console.log(`[pass-card] Loaded JSON ${jsonFile}: ${allCardData.length} cards, verifying index ${cardIndex}`);

    // Record history BEFORE making changes (enables undo)
    await recordVerificationAction(id, 'pass_card', allCardData, null, parseInt(cardIndex));

    // Use modified data for the specific card if provided, and record corrections for learning
    const originalCardData = allCardData[parseInt(cardIndex)];
    if (modifiedData) {
      allCardData[parseInt(cardIndex)] = modifiedData;
      // Record corrections for learning system (async, non-blocking)
      recordCorrections(originalCardData, modifiedData).catch(() => {});
    }

    // Import only the specific card to database
    const cardToImport = [allCardData[parseInt(cardIndex)]];

    // Get the image file for source tracking
    const imageFile = bulkBackFiles.find(file => {
      const imgBaseName = path.parse(file).name;
      const imgExt = path.parse(file).ext.toLowerCase();
      return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
    });
    console.log(`[pass-card] Looking for image with id=${id}, found: ${imageFile || 'NONE'}, bulkBackFiles: ${JSON.stringify(bulkBackFiles)}`);

    // Find the cropped back image for this specific card
    const CROPPED_BACKS_PENDING = path.join(PENDING_VERIFICATION_DIR, 'pending_verification_cropped_backs');
    const CROPPED_BACKS_VERIFIED = path.join(VERIFIED_ROOT_DIR, 'verified_cropped_backs');
    let croppedBackFile = null;
    try {
      const card = cardToImport[0];
      const gridMeta = card._grid_metadata || {};
      const pos = gridMeta.position !== undefined ? gridMeta.position : cardIndex;
      const croppedFiles = await fs.readdir(CROPPED_BACKS_PENDING);
      // Match by base name and position
      const searchPattern = `${id}_pos${pos}_`;
      croppedBackFile = croppedFiles.find(f => f.startsWith(searchPattern));
      // If not found by position, try by name/number
      if (!croppedBackFile && card.name && card.number) {
        const namePart = card.name.replace(/\s+/g, '_').replace(/[^a-zA-Z0-9_]/g, '');
        croppedBackFile = croppedFiles.find(f =>
          f.includes(`_${namePart}_`) && f.includes(`_${card.number}.`)
        );
      }
    } catch (err) {
      console.log(`[pass-card] No cropped_backs dir or error: ${err.message}`);
    }

    // Convert selected text fields to lowercase for consistency (include 'name')
    // Also inject source_file and cropped_back_file
    const processedCardData = cardToImport.map(card => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      // Ensure source_file is set from the image filename
      if (!processedCard.source_file && imageFile) {
        processedCard.source_file = imageFile;
      }
      if (!processedCard.original_filename && imageFile) {
        processedCard.original_filename = imageFile;
      }
      // Add cropped_back_file if found
      if (croppedBackFile) {
        processedCard.cropped_back_file = croppedBackFile;
      }
      return processedCard;
    });
    
    // Import card directly to database
    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card, CardComplete
from app.schemas import CardCreate
from app.db_backup import backup_database
import os

# Read card data from stdin
card_data = json.loads(sys.stdin.read())

# Before writing, create a timestamped DB backup for safety
try:
    backup_path = backup_database(os.getenv('DB_PATH', 'trading_cards.db'), os.getenv('DB_BACKUP_DIR', 'backups'))
    print(f"DB backup created: {backup_path}", file=sys.stderr)
except Exception as e:
    print(f"Warning: DB backup failed: {e}", file=sys.stderr)

# Convert selected text fields to lowercase for consistency
text_fields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition']
for card_info in card_data:
    for field in text_fields:
        if field in card_info and isinstance(card_info[field], str):
            card_info[field] = card_info[field].lower()

with get_session() as session:
    for card_info in card_data:
        try:
            # Create CardCreate instance for validation
            card_create = CardCreate(**card_info)

            # Check for existing card (duplicate detection)
            existing = session.query(Card).filter(
                Card.brand == card_info.get("brand"),
                Card.number == card_info.get("number"),
                Card.name == card_info.get("name"),
                Card.copyright_year == card_info.get("copyright_year")
            ).first()

            if existing:
                # Update quantity for duplicate
                existing.quantity += 1
                card_id = existing.id
                print(f"Updated quantity for existing card: {card_info.get('name')}")
            else:
                # Create new card
                new_card = Card(**card_create.model_dump())
                session.add(new_card)
                session.flush()  # Get the new card's ID
                card_id = new_card.id
                print(f"Added new card: {card_info.get('name')}")

            # Always create CardComplete record for each physical card copy
            grid_meta = card_info.get('_grid_metadata', {})
            card_complete = CardComplete(
                card_id=card_id,
                source_file=card_info.get('source_file') or card_info.get('original_filename'),
                source_position=grid_meta.get('position') or card_info.get('grid_position'),
                grid_position=str(grid_meta.get('position') or card_info.get('grid_position', '')),
                original_filename=card_info.get('original_filename'),
                condition_at_scan=card_info.get('condition'),
                notes=card_info.get('notes'),
                name=card_info.get('name'),
                sport=card_info.get('sport'),
                brand=card_info.get('brand'),
                number=card_info.get('number'),
                copyright_year=card_info.get('copyright_year'),
                team=card_info.get('team'),
                card_set=card_info.get('card_set'),
                condition=card_info.get('condition'),
                value_estimate=card_info.get('value_estimate'),
                features=card_info.get('features'),
                matched_front_file=card_info.get('matched_front_file')
            )
            session.add(card_complete)
            print(f"Added card_complete record for: {card_info.get('name')}")

        except Exception as e:
            print(f"Error processing card {card_info.get('name', 'n/a')}: {e}")
            continue

    session.commit()
print("Database import completed successfully")
    `], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });
    try { REPROCESS_JOBS.set(id, pythonProcess); } catch (_) {}

    // Send card data to Python process
    pythonProcess.stdin.write(JSON.stringify(processedCardData));
    pythonProcess.stdin.end();
    
    let output = '';
    let error = '';
    
    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });
    
    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });
    
    pythonProcess.on('close', async (code) => {
      try { REPROCESS_JOBS.delete(id); } catch (_) {}
      console.log(`[pass-card] Python exited with code ${code}, allCardData had ${allCardData.length} cards, splicing index ${cardIndex}`);
      if (code === 0) {
        // Remove the imported card from the array FIRST, before any async operations
        const cardIdx = parseInt(cardIndex);
        allCardData.splice(cardIdx, 1);
        console.log(`[pass-card] After splice: ${allCardData.length} cards remaining`);

        // Update the JSON file with remaining cards - THIS MUST SUCCEED
        if (allCardData.length > 0) {
          try {
            await fs.writeFile(jsonPath, JSON.stringify(allCardData, null, 2));
            console.log(`[pass-card] JSON updated successfully: ${jsonPath}`);
          } catch (writeErr) {
            console.error(`[pass-card] CRITICAL: Failed to update JSON file: ${writeErr.message}`);
            // Card is already in DB but JSON wasn't updated - try again
            try {
              await fs.writeFile(jsonPath, JSON.stringify(allCardData, null, 2));
              console.log(`[pass-card] JSON retry succeeded`);
            } catch (retryErr) {
              console.error(`[pass-card] CRITICAL: JSON retry failed: ${retryErr.message}`);
              return res.status(500).json({
                error: 'Card added to database but failed to update pending list. Please refresh.',
                details: retryErr.message
              });
            }
          }

          // Partial verification: copy image to verified_images
          try {
            const verifiedImageName = getVerifiedFilename(imageFile);
            const verifiedImagePath = path.join(VERIFIED_IMAGES_DIR, verifiedImageName);

            // Copy image to verified_images if not already there
            try {
              await fs.access(verifiedImagePath);
            } catch {
              await fs.copyFile(path.join(PENDING_BULK_BACK_DIR, imageFile), verifiedImagePath);
              console.log(`[pass-card] Copied image to verified: ${verifiedImageName}`);
            }
          } catch (partialErr) {
            console.error(`[pass-card] Warning: Failed to copy image to verified: ${partialErr.message}`);
          }

          // Move cropped back to verified/cropped_backs
          if (croppedBackFile) {
            try {
              await fs.mkdir(CROPPED_BACKS_VERIFIED, { recursive: true });
              await fs.rename(
                path.join(CROPPED_BACKS_PENDING, croppedBackFile),
                path.join(CROPPED_BACKS_VERIFIED, croppedBackFile)
              );
              console.log(`[pass-card] Moved cropped back to verified: ${croppedBackFile}`);
            } catch (cropErr) {
              console.error(`[pass-card] Warning: Failed to move cropped back: ${cropErr.message}`);
            }
          }

          // Log verification action (single card) - non-critical
          try {
            const py = `from app.logging_system import logger\nlogger.log_verification_action(filename='${(imageFileEarly||'').replace(/'/g,"\'")}', action='pass', card_index=${cardIdx})`;
            const p = spawn('python', ['-c', py], { cwd: path.join(__dirname, '../..') });
            p.on('error', ()=>{});
          } catch(_) {}
          try { await audit('verify_card_passed', { id, scope: 'single', remaining: allCardData.length }); } catch {}
          res.json({
            success: true,
            message: 'Card verified and imported to database successfully. Remaining cards updated.',
            remainingCards: allCardData.length,
            output: output.trim()
          });
        } else {
          // No cards left, move files to verified folder
          const imageFile = bulkBackFiles.find(file => {
            const imgBaseName = path.parse(file).name;
            const imgExt = path.parse(file).ext.toLowerCase();
            return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
          });
          
          try {
            // Delete grouped JSON file (data is now in database)
            await fs.unlink(jsonPath);

            // Copy image file to verified folder with verified_ prefix (keep original in pending)
            if (imageFile) {
              const verifiedImageName = getVerifiedFilename(imageFile);
              const verifiedImagePath = path.join(VERIFIED_IMAGES_DIR, verifiedImageName);

              // Copy to verified if not already there
              try {
                await fs.access(verifiedImagePath);
                console.log(`[pass-card] Image already in verified: ${verifiedImageName}`);
              } catch {
                // Not in verified yet, copy it
                await fs.copyFile(
                  path.join(PENDING_BULK_BACK_DIR, imageFile),
                  verifiedImagePath
                );
                console.log(`[pass-card] Copied image to verified: ${verifiedImageName}`);
              }
            }

            // Log verification action (all from this image processed)
            try {
              const py = `from app.logging_system import logger\nlogger.log_verification_action(filename='${(imageFileEarly||'').replace(/'/g,"\'")}', action='pass')`;
              const p = spawn('python', ['-c', py], { cwd: path.join(__dirname, '../..') });
              p.on('error', ()=>{});
            } catch(_) {}
            res.json({
              success: true,
              message: 'Last card verified and imported. All cards from this image processed and archived.',
              remainingCards: 0,
              output: output.trim()
            });
            try { await audit('verify_image_archived', { id, scope: 'all' }); } catch {}
          } catch (moveError) {
            console.error('Error moving files to verified folder:', moveError);
            res.json({
              success: true,
              message: 'Card imported but file archiving failed',
              remainingCards: 0,
              output: output.trim()
            });
          }
        }
      } else {
        res.status(500).json({ 
          error: 'Failed to import card to database', 
          details: error.trim() 
        });
      }
    });
    
  } catch (error) {
    console.error('Error processing single card pass action:', error);
    res.status(500).json({ error: 'Failed to process single card pass action' });
  }
});

// Handle Pass action for entire photo
app.post('/api/pass/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const { modifiedData } = req.body;

    // Find the files - JSONs in pending root, images in bulk back subdirectory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    let bulkBackFiles = [];
    try { bulkBackFiles = await fs.readdir(PENDING_BULK_BACK_DIR); } catch (e) {}

    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    const imageFile = bulkBackFiles.find(file => {
      const imgBaseName = path.parse(file).name;
      const imgExt = path.parse(file).ext.toLowerCase();
      return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
    });

    if (!jsonFile || !imageFile) {
      return res.status(404).json({ error: 'Files not found' });
    }
    
    // Get the card data to import
    const originalData = JSON.parse(await fs.readFile(path.join(PENDING_VERIFICATION_DIR, jsonFile), 'utf8'));
    let cardData = modifiedData || originalData;

    // Record corrections for any modified cards (for learning system)
    if (modifiedData) {
      for (let i = 0; i < modifiedData.length; i++) {
        if (i < originalData.length) {
          recordCorrections(originalData[i], modifiedData[i]).catch(() => {});
        }
      }
    }

    // Convert text fields to lowercase for consistency and inject source_file
    cardData = cardData.map(card => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      // Ensure source_file is set from the image filename
      if (!processedCard.source_file && imageFile) {
        processedCard.source_file = imageFile;
      }
      if (!processedCard.original_filename && imageFile) {
        processedCard.original_filename = imageFile;
      }
      return processedCard;
    });
    
    // Import cards directly to database and create cards_complete records
    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card, CardComplete
from app.schemas import CardCreate

# Read card data from stdin
input_data = json.loads(sys.stdin.read())
card_data = input_data.get('cards', input_data) if isinstance(input_data, dict) else input_data
source_file = input_data.get('source_file', '') if isinstance(input_data, dict) else ''

# Convert text fields to lowercase for consistency
text_fields = ['name', 'sport', 'brand', 'team', 'card_set']
for card_info in card_data:
    for field in text_fields:
        if field in card_info and isinstance(card_info[field], str):
            card_info[field] = card_info[field].lower()

with get_session() as session:
    for idx, card_info in enumerate(card_data):
        try:
            # Create CardCreate instance for validation
            card_create = CardCreate(**card_info)

            # Check for existing card (duplicate detection)
            existing = session.query(Card).filter(
                Card.brand == card_info.get("brand"),
                Card.number == card_info.get("number"),
                Card.name == card_info.get("name"),
                Card.copyright_year == card_info.get("copyright_year")
            ).first()

            if existing:
                # Update quantity for duplicate
                existing.quantity += 1
                card_id = existing.id
                print(f"Updated quantity for existing card: {card_info.get('name')}")
            else:
                # Create new card
                new_card = Card(**card_create.model_dump())
                session.add(new_card)
                session.flush()  # Get the new card ID
                card_id = new_card.id
                print(f"Added new card: {card_info.get('name')}")

            # Create CardComplete record with full card data for each physical copy
            grid_meta = card_info.get('_grid_metadata', {})
            card_complete = CardComplete(
                card_id=card_id,
                source_file=source_file,
                source_position=grid_meta.get('position') or card_info.get('grid_position') or idx,
                grid_position=str(grid_meta.get('position') or card_info.get('grid_position', idx)),
                original_filename=source_file,
                condition_at_scan=card_info.get('condition'),
                notes=card_info.get('notes'),
                meta_data=json.dumps({k: v for k, v in card_info.items() if k not in text_fields}),
                # Card data (denormalized)
                name=card_info.get('name'),
                sport=card_info.get('sport'),
                brand=card_info.get('brand'),
                number=card_info.get('number'),
                copyright_year=card_info.get('copyright_year'),
                team=card_info.get('team'),
                card_set=card_info.get('card_set'),
                condition=card_info.get('condition'),
                value_estimate=card_info.get('value_estimate'),
                features=card_info.get('features'),
                matched_front_file=card_info.get('matched_front_file')
            )
            session.add(card_complete)
            print(f"Added card_complete record for: {card_info.get('name')}")

        except Exception as e:
            print(f"Error processing card {card_info.get('name', 'n/a')}: {e}")
            continue

    session.commit()
print("Database import completed successfully")
    `], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });

    // Send card data to Python process with source file info
    pythonProcess.stdin.write(JSON.stringify({
      cards: cardData,
      source_file: imageFile || id
    }));
    pythonProcess.stdin.end();
    
    let output = '';
    let error = '';
    
    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });
    
    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });
    
    pythonProcess.on('close', async (code) => {
      console.log(`[pass-all] Python exited with code ${code} for ${id}`);
      if (code === 0) {
        // Database import successful, now move files to verified folder
        try {
          // Delete grouped JSON file (per-card JSON in verified_final is canonical)
          await fs.unlink(path.join(PENDING_VERIFICATION_DIR, jsonFile));
          console.log(`[pass-all] Deleted JSON: ${jsonFile}`);

          // Move image file to verified/verified_images folder with verified_ prefix
          const verifiedImageName = getVerifiedFilename(imageFile);
          await fs.rename(
            path.join(PENDING_BULK_BACK_DIR, imageFile),
            path.join(VERIFIED_IMAGES_DIR, verifiedImageName)
          );
          console.log(`[pass-all] Moved image to verified: ${verifiedImageName}`);

          // Log verification action (pass all)
          try {
            const py = `from app.logging_system import logger\nlogger.log_verification_action(filename='${(imageFile||'').replace(/'/g,"\'")}', action='pass')`;
            const p = spawn('python', ['-c', py], { cwd: path.join(__dirname, '../..') });
            p.on('error', ()=>{});
          } catch(_) {}

          res.json({
            success: true,
            message: 'Cards verified, imported to database, and archived successfully',
            output: output.trim()
          });
        } catch (moveError) {
          console.error('[pass-all] Error moving files to verified folder:', moveError);
          res.json({
            success: true,
            message: 'Cards imported to database but file archiving failed',
            output: output.trim()
          });
        }
      } else {
        console.error(`[pass-all] Python failed with code ${code}: ${error.trim()}`);
        res.status(500).json({
          error: 'Failed to import card to database',
          details: error.trim()
        });
      }
    });
    
  } catch (error) {
    console.error('Error processing pass action:', error);
    res.status(500).json({ error: 'Failed to process pass action' });
  }
});

// Save partial progress for card verification
app.post('/api/save-progress/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const { data, cardIndex } = req.body;

    // Find the JSON file in pending verification directory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));

    if (!jsonFile) {
      return res.status(404).json({ error: 'Card data file not found' });
    }

    const jsonPath = path.join(PENDING_VERIFICATION_DIR, jsonFile);

    // Read existing data to preserve other cards
    let existingData = [];
    try {
      existingData = JSON.parse(await fs.readFile(jsonPath, 'utf8'));
    } catch (e) {
      console.error('[save-progress] Could not read existing JSON:', e.message);
    }

    // Record history for edit action (enables undo) - only for manual saves, not auto-saves
    // We record this before making changes so we can restore
    if (data && data.length > 0) {
      recordVerificationAction(id, 'edit', existingData, null, cardIndex).catch(() => {});
    }

    // Convert selected text fields to lowercase for consistency (include 'name')
    const processData = (card) => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      return processedCard;
    };

    let finalData;

    // If cardIndex is provided, only update that specific card (single card mode)
    if (cardIndex !== undefined && data.length === 1) {
      finalData = [...existingData];
      if (cardIndex >= 0 && cardIndex < finalData.length) {
        finalData[cardIndex] = processData(data[0]);
      }
      console.log(`[save-progress] Single card mode: updated card ${cardIndex}, total cards: ${finalData.length}`);
    } else {
      // Full array update (entire photo mode) - but merge by grid_position to be safe
      if (data.length === existingData.length) {
        // Same length, safe to replace entirely
        finalData = data.map(processData);
      } else {
        // Different lengths - merge by grid_position
        finalData = [...existingData];
        for (const incomingCard of data) {
          const pos = incomingCard.grid_position ?? incomingCard._grid_metadata?.position;
          if (pos !== undefined) {
            const idx = finalData.findIndex(c =>
              (c.grid_position ?? c._grid_metadata?.position) === pos
            );
            if (idx !== -1) {
              finalData[idx] = processData(incomingCard);
            }
          }
        }
      }
      console.log(`[save-progress] Full mode: ${data.length} incoming, ${existingData.length} existing, ${finalData.length} final`);
    }

    // Save merged data to JSON file
    await fs.writeFile(jsonPath, JSON.stringify(finalData, null, 2));

    res.json({
      success: true,
      message: 'Progress saved successfully',
      timestamp: new Date().toISOString()
    });

  } catch (error) {
    console.error('Error saving progress:', error);
    res.status(500).json({ error: 'Failed to save progress' });
  }
});

// Handle Re-process action
// mode: 'remaining' (default) = only reprocess cards still pending, 'all' = reprocess all 9 positions
app.post('/api/reprocess/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const { mode = 'remaining' } = req.body || {};

    // Find the files - JSONs in pending root, images in bulk back subdirectory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    let bulkBackFiles = [];
    try { bulkBackFiles = await fs.readdir(PENDING_BULK_BACK_DIR); } catch (e) {}

    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    const imageFile = bulkBackFiles.find(file => {
      const imgBaseName = path.parse(file).name;
      const imgExt = path.parse(file).ext.toLowerCase();
      return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
    });

    if (!jsonFile || !imageFile) {
      return res.status(404).json({ error: 'Files not found' });
    }

    const imagePath = path.join(PENDING_BULK_BACK_DIR, imageFile);

    // Get previous data for context
    const jsonPath = path.join(PENDING_VERIFICATION_DIR, jsonFile);
    const previousData = JSON.parse(await fs.readFile(jsonPath, 'utf8'));

    // Get positions to reprocess based on mode
    const positionsToProcess = mode === 'all'
      ? [0, 1, 2, 3, 4, 5, 6, 7, 8]  // All 9 grid positions
      : previousData.map(card => card._grid_metadata?.position ?? card.grid_position).filter(p => p !== undefined);

    console.log(`[reprocess] Mode: ${mode}, positions to process: ${positionsToProcess}`);
    
    // Re-run extraction with grid-aware logic: detect 3x3 grid and use GridProcessor when appropriate
    const pythonProcess = spawn('python', ['-c', `
import sys
import json
import os
sys.path.append("${path.join(__dirname, '../..')}")
from app.utils import gpt_extract_cards_from_image, save_cards_to_verification
from pathlib import Path
from app.run import _is_probable_3x3_grid
from app.grid_processor import GridProcessor

try:
    image_path = "${imagePath.replace(/\\/g, '\\\\')}"
    positions_to_process = ${JSON.stringify(positionsToProcess)}
    input_data = json.loads(sys.stdin.read())
    previous_data = input_data

    print(f"Re-processing image: {image_path}", file=sys.stderr)
    print(f"Mode: positions to process = {positions_to_process}", file=sys.stderr)
    print(f"Previous data had {len(previous_data)} cards", file=sys.stderr)
    
    # Debug: Show what the previous data looks like
    for i, card in enumerate(previous_data[:3]):  # Show first 3 cards
        print(f"Previous card {i+1}: {card.get('name', 'unknown')} ({card.get('copyright_year', 'unknown')}) - {card.get('team', 'unknown')}", file=sys.stderr)
    
    # Verify image exists and is readable
    if not os.path.exists(image_path):
        print(f"ERROR: Image file not found: {image_path}", file=sys.stderr)
        sys.exit(1)
    
    # DIAGNOSTIC: First ask the AI what it sees to debug the identical results issue
    from app.utils import convert_image_to_supported_format
    from openai import OpenAI
    import os
    
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
    encoded_image, mime_type = convert_image_to_supported_format(image_path, apply_preprocessing=False)
    
    diagnostic_messages = [
        {
            "role": "system", 
            "content": "You are analyzing a trading card image. Describe what you see briefly."
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "How many cards do you see in this image? Briefly describe each card you can identify (don't extract data, just describe what you see)."
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
                }
            ],
        },
    ]
    
    try:
        diagnostic_response = client.chat.completions.create(
            model=MODEL, messages=diagnostic_messages, max_tokens=500, temperature=0.1
        )
        diagnostic_result = diagnostic_response.choices[0].message.content.strip()
        print(f"AI DIAGNOSTIC - What it sees: {diagnostic_result}", file=sys.stderr)
    except Exception as e:
        print(f"Diagnostic failed: {e}", file=sys.stderr)
    
    # Decide processing path
    is_grid = False
    try:
        is_grid = _is_probable_3x3_grid(Path(image_path))
        print(f"Grid detection: {is_grid}", file=sys.stderr)
    except Exception as e:
        print(f"Grid detection failed (continuing with standard): {e}", file=sys.stderr)

    if is_grid:
        print("Detected probable 3x3 grid. Using GridProcessor for 9-card extraction...", file=sys.stderr)
        gp = GridProcessor()
        grid_cards, raw = gp.process_3x3_grid(image_path)
        
        # Convert GridCard objects to plain dicts
        parsed_cards = []
        for gc in grid_cards:
            d = gc.data.copy() if isinstance(gc.data, dict) else dict(gc.data)
            d.setdefault('_grid_metadata', {"position": gc.position, "row": gc.row, "col": gc.col, "confidence": getattr(gc, 'confidence', None)})
            parsed_cards.append(d)
        print(f"Grid processing completed: {len(parsed_cards)} cards extracted", file=sys.stderr)
    else:
        # Extract cards using enhanced reprocessing prompt with previous data context
        print(f"Starting GPT extraction with reprocessing context...", file=sys.stderr)
        parsed_cards, validated_cards = gpt_extract_cards_from_image(image_path, previous_data)
        
        print(f"Re-processing completed: {len(parsed_cards)} cards extracted", file=sys.stderr)
    
    # Debug: Check if we're getting the same data back
    names = [card.get('name', 'unknown') for card in parsed_cards]
    years = [card.get('copyright_year', 'unknown') for card in parsed_cards]
    teams = [card.get('team', 'unknown') for card in parsed_cards]
    
    print(f"Names extracted: {set(names)}", file=sys.stderr)
    print(f"Years extracted: {set(years)}", file=sys.stderr)
    print(f"Teams extracted: {set(teams)}", file=sys.stderr)
    
    # Check if all cards are identical (which would indicate a problem)
    if len(parsed_cards) > 1:
        first_card = parsed_cards[0]
        all_identical = all(
            card.get('name') == first_card.get('name') and
            card.get('team') == first_card.get('team') and
            card.get('copyright_year') == first_card.get('copyright_year')
            for card in parsed_cards[1:]
        )
        if all_identical:
            print(f"WARNING: All {len(parsed_cards)} cards appear identical - this suggests an AI analysis problem", file=sys.stderr)
    
    # Debug: Check what we got from the AI
    for i, card in enumerate(parsed_cards):
        print(f"Card {i+1}: {card.get('name', 'unknown')} - has confidence: {'_confidence' in card}", file=sys.stderr)
        if '_confidence' in card:
            print(f"  Confidence keys: {list(card['_confidence'].keys())}", file=sys.stderr)

    # Filter cards to only positions being reprocessed and merge with kept cards
    if positions_to_process and len(positions_to_process) < 9:
        # Get positions of all extracted cards
        def get_position(card):
            if '_grid_metadata' in card and 'position' in card['_grid_metadata']:
                return card['_grid_metadata']['position']
            return card.get('grid_position')

        # Filter newly extracted cards to only those at requested positions
        reprocessed_cards = [c for c in parsed_cards if get_position(c) in positions_to_process]
        print(f"Filtered to {len(reprocessed_cards)} cards at positions {positions_to_process}", file=sys.stderr)

        # Keep cards from previous data that are NOT being reprocessed (already verified)
        kept_cards = [c for c in previous_data if get_position(c) not in positions_to_process]
        print(f"Keeping {len(kept_cards)} cards from previous data (not reprocessed)", file=sys.stderr)

        # Merge: kept cards + reprocessed cards, sorted by position
        parsed_cards = kept_cards + reprocessed_cards
        parsed_cards.sort(key=lambda c: get_position(c) if get_position(c) is not None else 999)
        print(f"Final merged result: {len(parsed_cards)} cards", file=sys.stderr)

    # Return the parsed cards directly with all their metadata
    # Convert to JSON-safe format while preserving all data
    result_cards = []
    for card in parsed_cards:
        if isinstance(card, dict):
            # Ensure all values are JSON serializable
            safe_card = {}
            for key, value in card.items():
                try:
                    # Test if value is JSON serializable
                    json.dumps(value)
                    safe_card[key] = value
                except (TypeError, ValueError):
                    # If not serializable, convert to string
                    safe_card[key] = str(value)
            result_cards.append(safe_card)
        else:
            # Handle CardCreate objects
            if hasattr(card, 'model_dump'):
                result_cards.append(card.model_dump())
            else:
                result_cards.append(dict(card))
    
    print(f"Returning {len(result_cards)} cards with full metadata", file=sys.stderr)
    print(json.dumps(result_cards, indent=2))

except Exception as e:
    print(f"Re-processing error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
    `], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });
    
    // Send previous data to Python process for context
    pythonProcess.stdin.write(JSON.stringify(previousData));
    pythonProcess.stdin.end();
    
    let output = '';
    let error = '';
    
    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });
    
    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });
    
    pythonProcess.on('close', async (code) => {
      if (code === 0) {
        try {
          const trimmedOutput = output.trim();
          console.log('Re-processing Python exit code:', code);
          console.log('Raw output length:', trimmedOutput.length);
          console.log('First 300 chars of output:', trimmedOutput.substring(0, 300));
          console.log('Error output:', error.trim());
          
          // Try to find JSON in the output (skip any non-JSON lines)
          const lines = trimmedOutput.split('\n');
          let jsonOutput = '';
          let jsonStarted = false;
          
          for (const line of lines) {
            if (line.trim().startsWith('[') || line.trim().startsWith('{')) {
              jsonStarted = true;
            }
            if (jsonStarted) {
              jsonOutput += line + '\n';
            }
          }
          
          if (!jsonOutput.trim()) {
            throw new Error('No JSON output found in Python response');
          }
          
          let newCardData = JSON.parse(jsonOutput.trim());
          
          if (!Array.isArray(newCardData)) {
            throw new Error('Expected array of cards, got: ' + typeof newCardData);
          }
          
          console.log('Successfully parsed', newCardData.length, 'cards from re-processing');
          
          // Update the JSON file with new extraction
          newCardData = newCardData.map(normalizeCardJS);
          const jsonPath = path.join(PENDING_VERIFICATION_DIR, jsonFile);
          await fs.writeFile(jsonPath, JSON.stringify(newCardData, null, 2));
          
          res.json({ 
            success: true, 
            message: 'Card data re-processed successfully',
            data: newCardData
          });
        } catch (parseError) {
          console.error('JSON parse error:', parseError.message);
          console.error('Trimmed output was:', output.substring(0, 1000));
          console.error('Error output was:', error);
          res.status(500).json({ 
            error: 'Failed to parse re-processed data',
            details: parseError.message,
            rawOutput: output.substring(0, 500),
            errorOutput: error.substring(0, 500)
          });
        }
      } else {
        console.error('Python process failed with exit code:', code);
        console.error('Error output:', error);
        console.error('Standard output:', output);
        res.status(500).json({ 
          error: 'Re-processing failed', 
          details: error.trim() || 'Python process exited with code ' + code,
          rawOutput: output.substring(0, 500)
        });
      }
    });
    
  } catch (error) {
    console.error('Error processing reprocess action:', error);
    res.status(500).json({ error: 'Failed to process reprocess action' });
  }
});

// Handle Fail action for single card
app.post('/api/fail-card/:id/:cardIndex', async (req, res) => {
  try {
    const { id, cardIndex } = req.params;

    // Find the files - JSONs in pending root, images in bulk back subdirectory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    let bulkBackFiles = [];
    try { bulkBackFiles = await fs.readdir(PENDING_BULK_BACK_DIR); } catch (e) {}

    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));

    if (!jsonFile) {
      return res.status(404).json({ error: 'Card data file not found' });
    }
    
    // Get the current card data
    const jsonPath = path.join(PENDING_VERIFICATION_DIR, jsonFile);
    let allCardData = JSON.parse(await fs.readFile(jsonPath, 'utf8'));

    // Find and delete the cropped back image for this specific card before removing from array
    const CROPPED_BACKS_PENDING = path.join(PENDING_VERIFICATION_DIR, 'pending_verification_cropped_backs');
    try {
      const cardIdx = parseInt(cardIndex);
      const card = allCardData[cardIdx];
      if (card) {
        const gridMeta = card._grid_metadata || {};
        const pos = gridMeta.position !== undefined ? gridMeta.position : cardIdx;
        const croppedFiles = await fs.readdir(CROPPED_BACKS_PENDING);
        // Match by base name and position
        const searchPattern = `${id}_pos${pos}_`;
        let croppedBackFile = croppedFiles.find(f => f.startsWith(searchPattern));
        // If not found by position, try by name/number
        if (!croppedBackFile && card.name && card.number) {
          const namePart = card.name.replace(/\s+/g, '_').replace(/[^a-zA-Z0-9_]/g, '');
          croppedBackFile = croppedFiles.find(f =>
            f.includes(`_${namePart}_`) && f.includes(`_${card.number}.`)
          );
        }
        // Delete the cropped back if found
        if (croppedBackFile) {
          await fs.unlink(path.join(CROPPED_BACKS_PENDING, croppedBackFile));
          console.log(`[fail-card] Deleted cropped back: ${croppedBackFile}`);
        }
      }
    } catch (cropErr) {
      console.log(`[fail-card] No cropped_backs dir or error: ${cropErr.message}`);
    }

    // Remove the rejected card from the array
    allCardData.splice(parseInt(cardIndex), 1);
    
    // Update the JSON file with remaining cards
    if (allCardData.length > 0) {
      await fs.writeFile(jsonPath, JSON.stringify(allCardData, null, 2));
      res.json({ 
        success: true, 
        message: 'Card rejected and removed. Remaining cards updated.',
        remainingCards: allCardData.length
      });
    } else {
      // No cards left, move image back to unprocessed_bulk_back for reprocessing
      const imageFile = bulkBackFiles.find(file => {
        const imgBaseName = path.parse(file).name;
        const imgExt = path.parse(file).ext.toLowerCase();
        return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
      });

      try {
        await fs.unlink(jsonPath);
        if (imageFile) {
          // Move image back to unprocessed_bulk_back instead of deleting
          await fs.rename(
            path.join(PENDING_BULK_BACK_DIR, imageFile),
            path.join(UNPROCESSED_BULK_BACK_DIR, imageFile)
          );
          console.log(`[fail-card] Moved image back to unprocessed: ${imageFile}`);
        }

        res.json({
          success: true,
          message: 'Last card rejected. Image moved back to unprocessed for reprocessing.',
          remainingCards: 0
        });
      } catch (cleanupError) {
        console.error('[fail-card] Error moving files:', cleanupError);
        res.json({
          success: true,
          message: 'Card rejected but file cleanup failed',
          remainingCards: 0
        });
      }
    }
    
  } catch (error) {
    console.error('Error processing single card fail action:', error);
    res.status(500).json({ error: 'Failed to process single card fail action' });
  }
});

// Handle Fail action for entire photo
app.post('/api/fail/:id', async (req, res) => {
  try {
    const { id } = req.params;

    // Find the files - JSONs in pending root, images in bulk back subdirectory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    let bulkBackFiles = [];
    try { bulkBackFiles = await fs.readdir(PENDING_BULK_BACK_DIR); } catch (e) {}

    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    const imageFile = bulkBackFiles.find(file => {
      const imgBaseName = path.parse(file).name;
      const imgExt = path.parse(file).ext.toLowerCase();
      return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
    });

    if (!jsonFile || !imageFile) {
      return res.status(404).json({ error: 'Files not found' });
    }

    // Delete JSON and move image back to unprocessed_bulk_back for reprocessing
    await fs.unlink(path.join(PENDING_VERIFICATION_DIR, jsonFile));
    await fs.rename(
      path.join(PENDING_BULK_BACK_DIR, imageFile),
      path.join(UNPROCESSED_BULK_BACK_DIR, imageFile)
    );
    console.log(`[fail-all] Moved image back to unprocessed: ${imageFile}`);

    res.json({ success: true, message: 'Cards rejected. Image moved back to unprocessed for reprocessing.' });
  } catch (error) {
    console.error('Error processing fail action:', error);
    res.status(500).json({ error: 'Failed to process fail action' });
  }
});

// Get all cards from database with pagination and filtering
app.get('/api/cards', async (req, res) => {
  try {
    const { page = 1, limit = 20, search = '', sport = '', brand = '', condition = '', sortBy = '', sortDir = 'asc' } = req.query;
    
    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card
from sqlalchemy import func, or_, and_, asc, desc

page = ${parseInt(page)}
limit = ${parseInt(limit)}
search = "${search}"
sport = "${sport}"
brand = "${brand}"
condition = "${condition}"
sort_by = "${(req.query.sortBy || '').toString()}"
sort_dir = "${(req.query.sortDir || 'asc').toString()}".lower()

with get_session() as session:
    query = session.query(Card)
    
    # Apply filters
    filters = []
    if search:
        filters.append(or_(
            Card.name.ilike(f"%{search}%"),
            Card.team.ilike(f"%{search}%"),
            Card.card_set.ilike(f"%{search}%")
        ))
    if sport:
        filters.append(Card.sport.ilike(f"%{sport}%"))
    if brand:
        filters.append(Card.brand.ilike(f"%{brand}%"))
    if condition:
        filters.append(Card.condition == condition)
    
    if filters:
        query = query.filter(and_(*filters))

    # Sorting (whitelist columns)
    valid_cols = {
        'name': Card.name,
        'sport': Card.sport,
        'brand': Card.brand,
        'number': Card.number,
        'copyright_year': Card.copyright_year,
        'team': Card.team,
        'card_set': Card.card_set,
        'condition': Card.condition,
        'is_player_card': Card.is_player_card,
        'features': Card.features,
        'value_estimate': Card.value_estimate,
        'quantity': Card.quantity,
        'date_added': Card.date_added,
    }
    col = valid_cols.get(sort_by)
    if col is not None:
        if sort_dir == 'desc':
            query = query.order_by(desc(col))
        else:
            query = query.order_by(asc(col))
    
    # Get total count
    total = query.count()
    
    # Apply pagination
    offset = (page - 1) * limit
    cards = query.offset(offset).limit(limit).all()
    
    # Convert to dict
    result = {
        "cards": [
            {
                "id": card.id,
                "name": card.name,
                "sport": card.sport,
                "brand": card.brand,
                "number": card.number,
                "copyright_year": card.copyright_year,
                "team": card.team,
                "card_set": card.card_set,
                "condition": card.condition,
                "is_player_card": card.is_player_card,
                "features": card.features,
                "value_estimate": card.value_estimate,
                "quantity": card.quantity,
                "date_added": card.date_added.isoformat() if card.date_added else None
            }
            for card in cards
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    }
    
    print(json.dumps(result))
    `], {
      cwd: path.join(__dirname, '../..')
    });
    
    let output = '';
    let error = '';
    
    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });
    
    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });
    
    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          res.json(result);
        } catch (parseError) {
          res.status(500).json({ error: 'Failed to parse database response' });
        }
      } else {
        res.status(500).json({ 
          error: 'Failed to query database', 
          details: error.trim() 
        });
      }
    });
    
  } catch (error) {
    console.error('Error querying cards:', error);
    res.status(500).json({ error: 'Failed to query cards' });
  }
});

// Update a card in the database (DB is single source of truth)
app.put('/api/cards/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const cardData = req.body;

    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card

card_id = ${parseInt(id)}
card_data = json.loads(sys.stdin.read())

# Convert text fields to lowercase for consistency
text_fields = ['name', 'sport', 'brand', 'team', 'card_set']
for field in text_fields:
    if field in card_data and isinstance(card_data[field], str):
        card_data[field] = card_data[field].lower()

with get_session() as session:
    card = session.query(Card).filter(Card.id == card_id).first()
    if not card:
        print("Card not found", file=sys.stderr)
        sys.exit(1)

    # Update fields
    for key, value in card_data.items():
        if hasattr(card, key) and key != 'id':
            setattr(card, key, value)

    session.commit()
    print("Card updated successfully")
    `], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });

    pythonProcess.stdin.write(JSON.stringify(cardData));
    pythonProcess.stdin.end();

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });

    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });

    pythonProcess.on('close', (code) => {
      if (code === 0) {
        res.json({ success: true, message: 'Card updated successfully' });
      } else {
        res.status(500).json({
          error: 'Failed to update card',
          details: error.trim()
        });
      }
    });

  } catch (error) {
    console.error('Error updating card:', error);
    res.status(500).json({ error: 'Failed to update card' });
  }
});

// Delete a card from the database (DB is single source of truth)
app.delete('/api/cards/:id', async (req, res) => {
  try {
    const { id } = req.params;

    const pythonProcess = spawn('python', ['-c', `
import sys
from app.database import get_session
from app.models import Card

card_id = ${parseInt(id)}

with get_session() as session:
    card = session.query(Card).filter(Card.id == card_id).first()
    if not card:
        print("Card not found", file=sys.stderr)
        sys.exit(1)

    # Delete from database (source of truth)
    session.delete(card)
    session.commit()
    print("Card deleted successfully")
    `], {
      cwd: path.join(__dirname, '../..')
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });

    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });

    pythonProcess.on('close', (code) => {
      if (code === 0) {
        res.json({ success: true, message: 'Card deleted successfully' });
      } else {
        res.status(500).json({
          error: 'Failed to delete card',
          details: error.trim()
        });
      }
    });

  } catch (error) {
    console.error('Error deleting card:', error);
    res.status(500).json({ error: 'Failed to delete card' });
  }
});

// Trigger raw scan processing
const STATUS_FILE = path.join(__dirname, '../../logs/processing_status.json');
const PYTHON_PROGRESS_FILE = path.join(__dirname, '../../logs/processing_progress.json');
// Track active reprocess jobs in-memory by pending verification id
const REPROCESS_JOBS = new Map();

function writeStatus(status) {
  try {
    fsSync.mkdirSync(path.dirname(STATUS_FILE), { recursive: true });
    fsSync.writeFileSync(STATUS_FILE, JSON.stringify(status, null, 2));
  } catch (e) {
    console.error('Failed to write status file:', e);
  }
}

function readStatus() {
  try {
    if (fsSync.existsSync(STATUS_FILE)) {
      return JSON.parse(fsSync.readFileSync(STATUS_FILE, 'utf8'));
    }
  } catch {}
  return { active: false };
}

function readPythonProgress() {
  try {
    if (fsSync.existsSync(PYTHON_PROGRESS_FILE)) {
      return JSON.parse(fsSync.readFileSync(PYTHON_PROGRESS_FILE, 'utf8'));
    }
  } catch {}
  return null;
}

// Process status endpoint
app.get('/api/processing-status', async (req, res) => {
  try {
    const status = readStatus();
    // If a PID exists, check if it's still alive
    if (status.pid) {
      try {
        process.kill(status.pid, 0);
        status.active = true;
      } catch {
        status.active = false;
      }
    }

    // Read Python progress file for real-time updates
    const pythonProgress = readPythonProgress();
    if (pythonProgress && status.active) {
      // Use Python progress if available (note: typeof check handles 0 correctly)
      status.progress = typeof pythonProgress.percent === 'number' ? pythonProgress.percent : status.progress;
      status.current = pythonProgress.current;
      status.total = pythonProgress.total;
      status.currentFile = pythonProgress.current_file;
      status.pythonStatus = pythonProgress.status;
      status.substep = pythonProgress.substep || '';
      status.substepDetail = pythonProgress.detail || '';
    }

    res.json(status);
  } catch (e) {
    res.status(500).json({ active: false, error: 'Failed to read status' });
  }
});

// Cancel background raw scan processing
app.post('/api/cancel-processing', async (req, res) => {
  try {
    const status = readStatus();
    if (!status || !status.active || !status.pid) {
      return res.status(400).json({ error: 'No active processing to cancel' });
    }

    const pid = parseInt(status.pid, 10);
    let terminated = false;
    try {
      // Kill the entire process group if possible (child was spawned detached)
      process.kill(-pid, 'SIGTERM');
      terminated = true;
    } catch (e1) {
      try {
        process.kill(pid, 'SIGTERM');
        terminated = true;
      } catch (e2) {
        // last resort
        try { process.kill(pid, 'SIGKILL'); terminated = true; } catch (_) {}
      }
    }

    // Update status file
    const newStatus = {
      ...status,
      active: false,
      canceled: true,
      progress: status.progress ?? 0,
      finishedAt: new Date().toISOString(),
    };
    writeStatus(newStatus);

    return res.json({ success: true, terminated });
  } catch (error) {
    console.error('Error cancelling processing:', error);
    return res.status(500).json({ error: 'Failed to cancel processing' });
  }
});

app.post('/api/process-raw-scans', async (req, res) => {
  try {
    const { count } = req.body || {};
    const BULK_BACK_DIR = path.join(__dirname, '../../cards/unprocessed_bulk_back');

    // Ensure logs directory exists and create a per-run log file
    const logsDir = path.join(__dirname, '../../logs');
    try { await fs.mkdir(logsDir, { recursive: true }); } catch {}
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const logFile = path.join(logsDir, `process_bulk_back_${stamp}.log`);
    const logStream = fsSync.createWriteStream(logFile, { flags: 'a' });

    // Get files sorted by filename (natural sort for IMG_2088 before IMG_2098)
    let allFiles = [];
    try {
      const files = await fs.readdir(BULK_BACK_DIR);
      const imageFiles = files.filter((f) => ['.jpg', '.jpeg', '.png', '.heic'].includes(path.extname(f).toLowerCase()));
      // Natural sort by filename (handles numbers properly)
      imageFiles.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
      allFiles = imageFiles;
    } catch {}

    // Determine how many to process
    const totalAvailable = allFiles.length;
    const toProcess = count && count > 0 ? Math.min(count, totalAvailable) : totalAvailable;

    if (toProcess === 0) {
      return res.status(400).json({ error: 'No images to process', count: 0 });
    }

    // Get the specific files to process (oldest first)
    const filesToProcess = allFiles.slice(0, toProcess);

    // Write the file list to a temp file for Python to read
    const fileListPath = path.join(logsDir, `process_list_${stamp}.json`);
    await fs.writeFile(fileListPath, JSON.stringify(filesToProcess));

    const child = spawn('python', ['-m', 'app.run', '--grid', '--file-list', fileListPath], {
      cwd: path.join(__dirname, '../..'),
      detached: true,
      stdio: ['ignore', 'pipe', 'pipe']
    });

    // Pipe output to the log file so we don't block or lose diagnostics
    child.stdout.pipe(logStream);
    child.stderr.pipe(logStream);

    const status = { active: true, pid: child.pid, logFile: logFile.replace(/\\/g, '/'), startedAt: new Date().toISOString(), total: toProcess, remaining: toProcess, progress: toProcess === 0 ? 100 : 10 };
    writeStatus(status);

    // Periodically update remaining count and computed progress while process is active
    const progressTimer = setInterval(async () => {
      try {
        const files = await fs.readdir(BULK_BACK_DIR).catch(() => []);
        const currentCount = files.filter((f) => ['.jpg', '.jpeg', '.png', '.heic'].includes(path.extname(f).toLowerCase())).length;
        const remaining = Math.max(0, currentCount - (totalAvailable - toProcess));
        const done = Math.max(0, toProcess - remaining);
        const pct = Math.min(99, Math.max(10, Math.round((done / Math.max(toProcess, 1)) * 100)));
        writeStatus({ ...status, active: true, remaining, progress: pct });
      } catch {}
    }, 4000);

    child.on('close', (code, signal) => {
      clearInterval(progressTimer);
      // Finalize progress to 100%
      const finished = { ...status, active: false, remaining: 0, progress: 100, finishedAt: new Date().toISOString(), exitCode: code ?? null, signal: signal ?? null };
      writeStatus(finished);
      // Clean up the file list
      fs.unlink(fileListPath).catch(() => {});
    });

    child.unref();

    res.status(202).json({
      success: true,
      message: `Processing ${toProcess} image(s) from bulk back directory`,
      pid: child.pid,
      logFile: logFile.replace(/\\/g, '/'),
      count: toProcess,
      totalAvailable
    });
  } catch (error) {
    console.error('Error triggering bulk back processing:', error);
    res.status(500).json({ error: 'Failed to trigger bulk back processing', details: String(error) });
  }
});

// Get count of bulk back images waiting to be processed
app.get('/api/raw-scan-count', async (req, res) => {
  try {
    const BULK_BACK_DIR = path.join(__dirname, '../../cards/unprocessed_bulk_back');

    try {
      const files = await fs.readdir(BULK_BACK_DIR);
      const imageFiles = files.filter(file => {
        const ext = path.extname(file).toLowerCase();
        return ['.jpg', '.jpeg', '.png', '.heic'].includes(ext);
      });

      res.json({ count: imageFiles.length, files: imageFiles });
    } catch (dirError) {
      // Directory doesn't exist or is empty
      res.json({ count: 0, files: [] });
    }

  } catch (error) {
    console.error('Error getting bulk back count:', error);
    res.status(500).json({ error: 'Failed to get bulk back count' });
  }
});

// List bulk back images with basic metadata (for preview before processing)
app.get('/api/raw-scans', async (req, res) => {
  try {
    const BULK_BACK_DIR = path.join(__dirname, '../../cards/unprocessed_bulk_back');
    let files;
    try {
      files = await fs.readdir(BULK_BACK_DIR);
    } catch {
      return res.json({ files: [], count: 0 });
    }

    const imageFiles = files.filter((file) => ['.jpg', '.jpeg', '.png', '.heic', '.heif'].includes(path.extname(file).toLowerCase()));
    const enriched = await Promise.all(
      imageFiles.map(async (name) => {
        const p = path.join(BULK_BACK_DIR, name);
        try {
          const st = await fs.stat(p);
          return {
            name,
            size: st.size,
            mtime: st.mtime,
            url: `/cards/unprocessed_bulk_back/${name}`
          };
        } catch {
          return { name, size: null, mtime: null, url: `/cards/unprocessed_bulk_back/${name}` };
        }
      })
    );
    // Sort oldest first (for processing order)
    enriched.sort((a, b) => new Date(a.mtime) - new Date(b.mtime));
    res.json({ files: enriched, count: enriched.length });
  } catch (error) {
    console.error('Error listing bulk back images:', error);
    res.status(500).json({ error: 'Failed to list bulk back images' });
  }
});

// Get field options from existing database records
app.get('/api/field-options', async (req, res) => {
  try {
    const pythonProcess = spawn('python', ['-c', `
from app.database import get_session
from app.models import Card
from sqlalchemy import func, distinct
import json

with get_session() as session:
    # Get distinct values for dropdown fields
    sports = session.query(distinct(Card.sport)).filter(Card.sport.isnot(None)).all()
    brands = session.query(distinct(Card.brand)).filter(Card.brand.isnot(None)).all()
    teams = session.query(distinct(Card.team)).filter(Card.team.isnot(None)).all()
    conditions = session.query(distinct(Card.condition)).filter(Card.condition.isnot(None)).all()
    sets = session.query(distinct(Card.card_set)).filter(Card.card_set.isnot(None)).all()
    
    # Get all features and split them
    features_raw = session.query(Card.features).filter(Card.features.isnot(None)).all()
    all_features = set()
    for (features_str,) in features_raw:
        if features_str and features_str != 'none':
            for feature in features_str.split(','):
                all_features.add(feature.strip())
    
    result = {
        "sports": sorted([s[0] for s in sports if s[0]]),
        "brands": sorted([b[0] for b in brands if b[0]]),
        "teams": sorted([t[0] for t in teams if t[0]]),
        "conditions": sorted([c[0] for c in conditions if c[0]]),
        "card_sets": sorted([s[0] for s in sets if s[0]]),
        "features": sorted(list(all_features))
    }
    
    print(json.dumps(result))
    `], {
      cwd: path.join(__dirname, '../..')
    });
    
    let output = '';
    let error = '';
    
    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });
    
    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });
    
    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          res.json(result);
        } catch (parseError) {
          res.status(500).json({ error: 'Failed to parse field options response' });
        }
      } else {
        res.status(500).json({ 
          error: 'Failed to get field options', 
          details: error.trim() 
        });
      }
    });
    
  } catch (error) {
    console.error('Error getting field options:', error);
    res.status(500).json({ error: 'Failed to get field options' });
  }
});

// Get card suggestions based on partial match for autofill
app.post('/api/card-suggestions', async (req, res) => {
  try {
    const { name, brand, number, copyright_year, sport } = req.body;

    const pythonProcess = spawn('python', ['-c', `
import json
from app.database import get_session
from app.models import Card
from sqlalchemy import or_, func

search_name = ${JSON.stringify(name || '')}
search_brand = ${JSON.stringify(brand || '')}
search_number = ${JSON.stringify(number || '')}
search_year = ${JSON.stringify(copyright_year || '')}
search_sport = ${JSON.stringify(sport || '')}

with get_session() as session:
    query = session.query(Card)

    # Build filters based on provided criteria
    filters = []

    # Name matching (fuzzy with LIKE)
    if search_name and len(search_name) >= 2:
        filters.append(func.lower(Card.name).like(f"%{search_name.lower()}%"))

    # Brand exact match
    if search_brand:
        filters.append(func.lower(Card.brand) == search_brand.lower())

    # Number exact match
    if search_number:
        filters.append(Card.number == search_number)

    # Year match
    if search_year:
        filters.append(Card.copyright_year == search_year)

    # Sport match
    if search_sport:
        filters.append(func.lower(Card.sport) == search_sport.lower())

    if filters:
        query = query.filter(*filters)

    # Limit results
    cards = query.limit(10).all()

    suggestions = []
    for card in cards:
        suggestions.append({
            "id": card.id,
            "name": card.name,
            "brand": card.brand,
            "number": card.number,
            "copyright_year": card.copyright_year,
            "team": card.team,
            "card_set": card.card_set,
            "sport": card.sport,
            "condition": card.condition,
            "features": card.features,
            "is_player_card": card.is_player_card
        })

    print(json.dumps({"suggestions": suggestions}))
`], {
      cwd: path.join(__dirname, '../..')
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });

    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });

    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          res.json(result);
        } catch (parseError) {
          res.status(500).json({ error: 'Failed to parse card suggestions' });
        }
      } else {
        res.status(500).json({
          error: 'Failed to get card suggestions',
          details: error.trim()
        });
      }
    });

  } catch (error) {
    console.error('Error getting card suggestions:', error);
    res.status(500).json({ error: 'Failed to get card suggestions' });
  }
});

// Look up team for a player based on existing cards in database
app.post('/api/team-lookup', async (req, res) => {
  try {
    const { name, copyright_year, sport } = req.body;

    if (!name || name.length < 2) {
      return res.json({ team: null, source: null });
    }

    const pythonProcess = spawn('python', ['-c', `
import json
from app.database import get_session
from app.models import Card
from sqlalchemy import func

search_name = ${JSON.stringify(name || '')}
search_year = ${JSON.stringify(copyright_year || '')}
search_sport = ${JSON.stringify(sport || 'baseball')}

result = {"team": None, "source": None, "teams_found": []}

with get_session() as session:
    # Look for cards with same player name
    query = session.query(Card.team, Card.copyright_year).filter(
        func.lower(Card.name) == search_name.lower(),
        Card.team.isnot(None),
        Card.team != 'unknown',
        Card.team != ''
    )

    if search_sport:
        query = query.filter(func.lower(Card.sport) == search_sport.lower())

    matches = query.all()

    if matches:
        # Get unique teams
        teams = list(set(t[0] for t in matches if t[0]))
        result["teams_found"] = teams

        # Try to find team for specific year
        if search_year:
            year_matches = [t for t in matches if str(t[1]) == str(search_year)]
            if year_matches:
                result["team"] = year_matches[0][0]
                result["source"] = "database_year_match"

        # If no year match, use most common team
        if not result["team"] and teams:
            result["team"] = teams[0]
            result["source"] = "database_name_match"

print(json.dumps(result))
`], {
      cwd: path.join(__dirname, '../..')
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });

    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });

    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          res.json(result);
        } catch (parseError) {
          res.json({ team: null, source: null });
        }
      } else {
        res.json({ team: null, source: null });
      }
    });

  } catch (error) {
    console.error('Error looking up team:', error);
    res.json({ team: null, source: null });
  }
});

// Get learning insights from corrections database
app.get('/api/learning-insights', async (req, res) => {
  try {
    const pythonProcess = spawn('python', ['-c', `
import json
import sqlite3
from pathlib import Path
import os

# Use relative path from working directory
CORRECTIONS_DB = Path("data/corrections.db")

result = {
    "total_corrections": 0,
    "corrections_by_field": {},
    "top_patterns": [],
    "recent_corrections": []
}

if CORRECTIONS_DB.exists():
    conn = sqlite3.connect(str(CORRECTIONS_DB))
    cursor = conn.cursor()

    # Total corrections
    cursor.execute("SELECT COUNT(*) FROM corrections")
    result["total_corrections"] = cursor.fetchone()[0]

    # Corrections by field
    cursor.execute("""
        SELECT field, COUNT(*) as cnt FROM corrections
        GROUP BY field ORDER BY cnt DESC
    """)
    result["corrections_by_field"] = {row[0]: row[1] for row in cursor.fetchall()}

    # Top learned patterns (high confidence)
    cursor.execute("""
        SELECT pattern_key, pattern_value, confidence, occurrence_count
        FROM learned_patterns
        WHERE pattern_type = 'correction'
        ORDER BY confidence DESC, occurrence_count DESC
        LIMIT 20
    """)
    result["top_patterns"] = [
        {"pattern": row[0], "correction": row[1], "confidence": row[2], "count": row[3]}
        for row in cursor.fetchall()
    ]

    # Recent corrections (last 20)
    cursor.execute("""
        SELECT field, original_value, corrected_value, brand, year, created_at
        FROM corrections
        ORDER BY created_at DESC
        LIMIT 20
    """)
    result["recent_corrections"] = [
        {"field": row[0], "original": row[1], "corrected": row[2], "brand": row[3], "year": row[4], "date": row[5]}
        for row in cursor.fetchall()
    ]

    conn.close()

print(json.dumps(result))
    `], {
      cwd: path.join(__dirname, '../..')
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });

    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });

    pythonProcess.on('close', (code) => {
      if (code === 0 && output.trim()) {
        try {
          res.json(JSON.parse(output.trim()));
        } catch (e) {
          res.json({ total_corrections: 0, error: 'Failed to parse response' });
        }
      } else {
        res.json({ total_corrections: 0, error: error || 'Failed to get insights' });
      }
    });
  } catch (error) {
    console.error('[learning-insights] Error:', error);
    res.json({ total_corrections: 0, error: error.message });
  }
});

// Get database stats
app.get('/api/database-stats', async (req, res) => {
  try {
    const pythonProcess = spawn('python', ['-c', `
from app.database import get_session
from app.models import Card
from sqlalchemy import func, distinct
import json

with get_session() as session:
    total_cards = session.query(func.count(Card.id)).scalar()
    total_quantity = session.query(func.sum(Card.quantity)).scalar() or 0
    unique_players = session.query(func.count(func.distinct(Card.name))).scalar()
    unique_years = session.query(func.count(func.distinct(Card.copyright_year))).scalar()
    unique_brands = session.query(func.count(func.distinct(Card.brand))).scalar()
    unique_sports = session.query(func.count(func.distinct(Card.sport))).scalar()
    
    # Compute total value from value_estimate only (last_price removed)
    cards = session.query(Card.name, Card.quantity, Card.value_estimate).all()
    def parse_estimate(s: str):
        try:
            import re
            nums = [float(x) for x in re.findall(r"\\d+(?:\\.\\d+)?", s or '')]
            if nums:
                return sum(nums)/len(nums)
        except Exception:
            pass
        return 0.0
    total_value = 0.0
    for name, qty, ve in cards:
        v = parse_estimate(ve)
        q = qty or 1
        total_value += float(v) * float(q)
    
    # Summaries for tooltips (top 10)
    years_counts = session.query(Card.copyright_year, func.count(Card.id)).group_by(Card.copyright_year).all()
    brands_counts = session.query(Card.brand, func.count(Card.id)).group_by(Card.brand).all()
    sports_counts = session.query(Card.sport, func.count(Card.id)).group_by(Card.sport).all()
    years_summary = [
        {"year": str(y or ''), "count": int(c)} for (y, c) in sorted(years_counts, key=lambda t: (t[0] or '')) if y is not None
    ]
    brands_summary = [
        {"brand": (b or ''), "count": int(c)} for (b, c) in sorted(brands_counts, key=lambda t: (t[1]), reverse=True)
    ]
    sports_summary = [
        {"sport": (s or ''), "count": int(c)} for (s, c) in sorted(sports_counts, key=lambda t: (t[1]), reverse=True)
    ]
    years_summary = years_summary[:10]
    brands_summary = brands_summary[:10]
    sports_summary = sports_summary[:10]
    
    result = {
        "total_cards": total_cards,
        "total_quantity": total_quantity,
        "unique_players": unique_players,
        "unique_years": unique_years,
        "unique_brands": unique_brands,
        "unique_sports": unique_sports,
        "total_value": round(total_value, 2),
        "years_summary": years_summary,
        "brands_summary": brands_summary,
        "sports_summary": sports_summary
    }
    
    print(json.dumps(result))
    `], {
      cwd: path.join(__dirname, '../..')
    });
    
    let output = '';
    let error = '';
    
    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });
    
    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });
    
    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          res.json(result);
        } catch (parseError) {
          res.status(500).json({ error: 'Failed to parse database stats response' });
        }
      } else {
        res.status(500).json({ 
          error: 'Failed to get database stats', 
          details: error.trim() 
        });
      }
    });
    
  } catch (error) {
    console.error('Error getting database stats:', error);
    res.status(500).json({ error: 'Failed to get database stats' });
  }
});

// Serve bulk back images from pending_verification
app.use('/api/bulk-back-image', express.static(PENDING_BULK_BACK_DIR));

// Serve front images from unprocessed_single_front
const FRONT_IMAGES_DIR = path.join(__dirname, '../../cards/unprocessed_single_front');
app.use('/api/front-image', express.static(FRONT_IMAGES_DIR));

// Serve cropped back images from the pending_verification and verified directories
const CROPPED_BACKS_DIR = path.join(__dirname, '../../cards/pending_verification/pending_verification_cropped_backs');
const VERIFIED_CROPPED_BACKS_DIR = path.join(__dirname, '../../cards/verified/verified_cropped_backs');

// Smart cropped back image endpoint with position-based fallback
app.get('/api/cropped-back-image/:filename', async (req, res) => {
  const { filename } = req.params;
  const exactPath = path.join(CROPPED_BACKS_DIR, filename);

  try {
    // First try exact match
    await fs.access(exactPath);
    return res.sendFile(exactPath);
  } catch (e) {
    // Exact file not found - try fallbacks
    // filename format: stem_posN_Name_Number.png
    const posMatch = filename.match(/^(.+)_pos(\d+)_.+\.png$/);
    if (posMatch) {
      const stem = posMatch[1];
      const pos = posMatch[2];

      try {
        const files = await fs.readdir(CROPPED_BACKS_DIR);

        // Fallback 1: Same stem and position
        let fallback = files.find(f => f.startsWith(stem) && f.includes(`_pos${pos}_`));
        if (fallback) {
          return res.sendFile(path.join(CROPPED_BACKS_DIR, fallback));
        }

        // Fallback 2: Same stem, ANY position (when cropped images don't match JSON positions)
        fallback = files.find(f => f.startsWith(stem) && f.includes('_pos'));
        if (fallback) {
          console.log(`[cropped-back] Using fallback image: ${fallback} for requested: ${filename}`);
          return res.sendFile(path.join(CROPPED_BACKS_DIR, fallback));
        }
      } catch (readErr) {
        // Directory doesn't exist
      }
    }

    // No fallback found
    res.status(404).send('Cropped image not found');
  }
});

app.use('/api/verified-cropped-back-image', express.static(VERIFIED_CROPPED_BACKS_DIR));

// Get individual cards (physical instances) for a card ID - includes images and dates
app.get('/api/card-cropped-back/:id', async (req, res) => {
  try {
    const { id } = req.params;

    const pythonProcess = spawn('python', ['-c', `
import json
import sys
import os
from app.database import get_session
from app.models import Card, CardComplete

card_id = ${parseInt(id)}
cropped_backs_dirs = [
    "${CROPPED_BACKS_DIR.replace(/\\/g, '/')}",
    "${VERIFIED_CROPPED_BACKS_DIR.replace(/\\/g, '/')}"
]

def find_cropped_back(name, number):
    """Search for cropped back image in pending and verified directories"""
    if not name or not number:
        return None
    name_parts = name.replace(' ', '_').title()
    search_suffix = f"_{name_parts}_{number}.".lower()

    for dir_path in cropped_backs_dirs:
        try:
            if not os.path.exists(dir_path):
                continue
            for f in os.listdir(dir_path):
                if search_suffix in f.lower():
                    return f
        except Exception:
            pass
    return None

with get_session() as session:
    # Get the main card
    card = session.query(Card).filter(Card.id == card_id).first()
    if not card:
        print(json.dumps({"found": False, "error": "Card not found"}))
        sys.exit(0)

    # Get all complete card copies for this card ID
    complete_cards = session.query(CardComplete).filter(
        CardComplete.card_id == card_id
    ).order_by(CardComplete.verification_date.desc()).all()

    individuals = []
    for ic in complete_cards:
        # Use stored cropped_back_file or search for it
        cropped_back_file = ic.cropped_back_file or find_cropped_back(ic.name, ic.number)

        individuals.append({
            "id": ic.id,
            "source_file": ic.source_file,
            "grid_position": ic.grid_position,
            "original_filename": ic.original_filename,
            "verification_date": ic.verification_date.isoformat() if ic.verification_date else None,
            "verified_by": ic.verified_by,
            "condition": ic.condition,
            "value_estimate": ic.value_estimate,
            "features": getattr(ic, 'features', None),
            "condition_at_scan": ic.condition_at_scan,
            "scan_quality": ic.scan_quality,
            "notes": ic.notes,
            "matched_front_file": ic.matched_front_file,
            "name": ic.name,
            "number": ic.number,
            "copyright_year": ic.copyright_year,
            "cropped_back_file": cropped_back_file
        })

    result = {
        "found": True,
        "quantity": card.quantity,
        "individualCards": individuals
    }

    print(json.dumps(result))
    `], {
      cwd: path.join(__dirname, '../..')
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });

    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });

    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          res.json(result);
        } catch (parseError) {
          res.status(500).json({ found: false, error: 'Failed to parse response' });
        }
      } else {
        res.status(500).json({ found: false, error: error.trim() });
      }
    });

  } catch (error) {
    console.error('Error fetching individual cards:', error);
    res.status(500).json({ found: false, error: 'Failed to fetch individual cards' });
  }
});

// Update an individual copy (cards_complete record)
app.put('/api/individual-card/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const updates = req.body;

    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import CardComplete

copy_id = ${parseInt(id)}
updates = json.loads('''${JSON.stringify(updates).replace(/'/g, "\\'")}''')

with get_session() as session:
    copy = session.query(CardComplete).filter(CardComplete.id == copy_id).first()
    if not copy:
        print(json.dumps({"success": False, "error": "Individual card not found"}))
        sys.exit(0)

    # Update allowed fields
    allowed_fields = ['condition', 'value_estimate', 'features', 'notes']
    for field in allowed_fields:
        if field in updates:
            setattr(copy, field, updates[field])

    session.commit()
    print(json.dumps({"success": True, "id": copy.id}))
    `], {
      cwd: path.join(__dirname, '../..')
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });

    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });

    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          res.json(result);
        } catch (parseError) {
          res.status(500).json({ success: false, error: 'Failed to parse response' });
        }
      } else {
        res.status(500).json({ success: false, error: error.trim() });
      }
    });

  } catch (error) {
    console.error('Error updating individual card:', error);
    res.status(500).json({ success: false, error: 'Failed to update individual card' });
  }
});

// Delete an individual copy (cards_complete record) and update quantity
app.delete('/api/individual-card/:id', async (req, res) => {
  try {
    const { id } = req.params;

    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card, CardComplete

copy_id = ${parseInt(id)}

with get_session() as session:
    copy = session.query(CardComplete).filter(CardComplete.id == copy_id).first()
    if not copy:
        print(json.dumps({"success": False, "error": "Individual card not found"}))
        sys.exit(0)

    card_id = copy.card_id
    cropped_back_file = copy.cropped_back_file

    # Delete the individual copy
    session.delete(copy)

    # Update the quantity on the main card
    card = session.query(Card).filter(Card.id == card_id).first()
    if card:
        remaining_copies = session.query(CardComplete).filter(CardComplete.card_id == card_id).count()
        if remaining_copies == 0:
            # No copies left, delete the main card too
            session.delete(card)
            print(json.dumps({"success": True, "id": copy_id, "cardDeleted": True, "cropped_back_file": cropped_back_file}))
        else:
            card.quantity = remaining_copies
            print(json.dumps({"success": True, "id": copy_id, "newQuantity": remaining_copies, "cropped_back_file": cropped_back_file}))

    session.commit()
    `], {
      cwd: path.join(__dirname, '../..')
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (data) => {
      output += data.toString();
    });

    pythonProcess.stderr.on('data', (data) => {
      error += data.toString();
    });

    pythonProcess.on('close', async (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          // Delete the cropped back file if it exists
          if (result.success && result.cropped_back_file) {
            try {
              const pendingPath = path.join(PENDING_VERIFICATION_DIR, 'pending_verification_cropped_backs', result.cropped_back_file);
              const verifiedPath = path.join(VERIFIED_ROOT_DIR, 'verified_cropped_backs', result.cropped_back_file);
              try { await fs.unlink(pendingPath); } catch (e) {}
              try { await fs.unlink(verifiedPath); } catch (e) {}
            } catch (e) {}
          }
          res.json(result);
        } catch (parseError) {
          res.status(500).json({ success: false, error: 'Failed to parse response' });
        }
      } else {
        res.status(500).json({ success: false, error: error.trim() });
      }
    });

  } catch (error) {
    console.error('Error deleting individual card:', error);
    res.status(500).json({ success: false, error: 'Failed to delete individual card' });
  }
});

// Backfill price estimates for existing cards
app.post('/api/backfill-price-estimates', async (req, res) => {
  try {
    const { dryRun = false } = req.body || {};
    const pythonProcess = spawn('python', ['-c', `
from app.scripts.backfill_price_estimates import backfill
import json
result = backfill(dry_run=${dryRun ? 'True' : 'False'})
print(json.dumps(result))
    `], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (d) => output += d.toString());
    pythonProcess.stderr.on('data', (d) => error += d.toString());
    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          res.json({ success: true, ...result });
        } catch (e) {
          res.json({ success: true, message: output.trim() });
        }
      } else {
        res.status(500).json({ error: 'Backfill failed', details: error.trim() });
      }
    });
  } catch (e) {
    res.status(500).json({ error: 'Failed to start backfill', details: String(e) });
  }
});

// Token-efficient batch refresh of price estimates using GPT
app.post('/api/refresh-prices', async (req, res) => {
  try {
    const { batchSize = 25, forceAll = false } = req.body || {};
    const pythonProcess = spawn('python', ['-c', `
from app.scripts.batch_price_refresh import refresh_prices
import json
result = refresh_prices(batch_size=${batchSize}, force_all=${forceAll ? 'True' : 'False'})
print(json.dumps(result))
    `], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (d) => output += d.toString());
    pythonProcess.stderr.on('data', (d) => error += d.toString());
    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output);
          res.json({ success: true, ...result });
        } catch (e) {
          res.json({ success: true, message: output.trim() });
        }
      } else {
        res.status(500).json({ error: 'Price refresh failed', details: error.trim() });
      }
    });
  } catch (e) {
    res.status(500).json({ error: 'Failed to start price refresh', details: String(e) });
  }
});

// ============================================================================
// Verification History & Undo Endpoints
// ============================================================================

// Get verification history for a file
app.get('/api/verification-history/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const history = await getVerificationHistory(id);
    res.json({ fileId: id, history, count: history.length });
  } catch (error) {
    console.error('[verification-history] Error:', error);
    res.status(500).json({ error: error.message });
  }
});

// Undo last verification action and restore previous state
app.post('/api/undo/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const result = await undoLastAction(id);

    if (!result.success) {
      return res.status(400).json({ error: result.error });
    }

    const undoneAction = result.undoneAction;

    // Restore the beforeData to the JSON file
    if (undoneAction.beforeData) {
      const jsonPath = path.join(PENDING_VERIFICATION_DIR, `${id}.json`);

      // Check if JSON still exists (might have been deleted on pass/fail all)
      try {
        await fs.access(jsonPath);
        // File exists, write beforeData back
        await fs.writeFile(jsonPath, JSON.stringify(undoneAction.beforeData, null, 2));
        console.log(`[undo] Restored ${id}.json to state before ${undoneAction.action}`);
      } catch (e) {
        // File doesn't exist, recreate it
        await fs.writeFile(jsonPath, JSON.stringify(undoneAction.beforeData, null, 2));
        console.log(`[undo] Recreated ${id}.json from history`);
      }
    }

    // If the action was a pass_card or pass_all, we may need to remove from database
    // For now, we just restore the JSON - database undo is more complex

    res.json({
      success: true,
      undoneAction: undoneAction.action,
      timestamp: undoneAction.timestamp,
      cardIndex: undoneAction.cardIndex,
      remainingUndos: result.remainingActions
    });
  } catch (error) {
    console.error('[undo] Error:', error);
    res.status(500).json({ error: error.message });
  }
});

// Get all files with pending undo history (for session recovery)
app.get('/api/verification-sessions', async (req, res) => {
  try {
    const files = await fs.readdir(VERIFICATION_HISTORY_DIR);
    const sessions = [];

    for (const file of files) {
      if (file.endsWith('_history.json')) {
        const fileId = file.replace('_history.json', '');
        const history = await getVerificationHistory(fileId);
        if (history.length > 0) {
          const lastAction = history[history.length - 1];
          sessions.push({
            fileId,
            actionCount: history.length,
            lastAction: lastAction.action,
            lastTimestamp: lastAction.timestamp
          });
        }
      }
    }

    // Sort by most recent
    sessions.sort((a, b) => new Date(b.lastTimestamp) - new Date(a.lastTimestamp));

    res.json({ sessions });
  } catch (error) {
    console.error('[verification-sessions] Error:', error);
    res.json({ sessions: [] });
  }
});

// System logs: uses separate logs database
app.get('/api/system-logs', async (req, res) => {
  try {
    const { limit = 200 } = req.query;
    const python = `
from app.logging_system import logger, init_logging_tables, UploadHistory, get_logs_session
from app.database import get_session
from app.models import Card
import json
from datetime import datetime, timezone

try:
    # Ensure tables exist in logs database
    init_logging_tables()
except Exception:
    pass

def norm(ts: str) -> str:
    try:
        if ts.endswith('Z'):
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(ts)
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    except Exception:
        return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

logs = logger.get_recent_logs(limit=${parseInt(limit)})
for log in logs:
    if 'timestamp' in log and isinstance(log['timestamp'], str):
        log['timestamp'] = norm(log['timestamp'])

# Compute totals from logs database
uploads_total = 0
uploads_verified = 0
uploads_failed = 0
uploads_pending = 0
try:
    with get_logs_session() as session:
        uploads_total = session.query(UploadHistory).count()
        uploads_verified = session.query(UploadHistory).filter(UploadHistory.status=='verified').count()
        uploads_failed = session.query(UploadHistory).filter(UploadHistory.status=='failed').count()
        uploads_pending = session.query(UploadHistory).filter(UploadHistory.status=='pending_verification').count()
except Exception:
    pass

# Get card count from main database
cards_total = 0
try:
    with get_session() as session:
        cards_total = session.query(Card).count()
except Exception:
    pass

print(json.dumps({
    'logs': logs,
    'totalLogs': len(logs),
    'timestamp': norm(datetime.utcnow().isoformat()),
    'totals': {
        'uploadsTotal': uploads_total,
        'uploadsVerified': uploads_verified,
        'uploadsFailed': uploads_failed,
        'uploadsPending': uploads_pending,
        'cardsTotal': cards_total
    }
}))
`;

    const pythonProcess = spawn('python', ['-c', python], {
      cwd: path.join(__dirname, '../..')
    });

    let output = '';
    let error = '';

    pythonProcess.stdout.on('data', (d) => (output += d.toString()));
    pythonProcess.stderr.on('data', (d) => (error += d.toString()));
    pythonProcess.on('close', (code) => {
      if (code === 0) {
        try {
          const result = JSON.parse(output || '{}');
          res.json(result);
        } catch (e) {
          res.status(500).json({ error: 'Failed to parse system logs', details: e.message });
        }
      } else {
        res.status(500).json({ error: 'Failed to fetch system logs', details: error.trim() });
      }
    });
  } catch (e) {
    res.status(500).json({ error: 'Failed to fetch system logs', details: String(e) });
  }
});

// Upload history endpoint removed

// Initialize and start server
ensureDirectories().then(() => {
  app.listen(PORT, () => {
    console.log(`🚀 API Server running on http://localhost:${PORT}`);
    console.log(`📁 Frontend available at http://localhost:3000`);
  });
});
