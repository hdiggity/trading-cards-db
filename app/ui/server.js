// load environment variables first
const path = require('path');
require('dotenv').config({ path: path.join(__dirname, '../../.env') });

const express = require('express');
const cors = require('cors');
const fs = require('fs').promises;
const fsSync = require('fs');
const { spawn } = require('child_process');
const multer = require('multer');

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json());

// Import routes
const healthRoutes = require('./routes/health');
const authRoutes = require('./routes/auth');

// Register routes
app.use('/', healthRoutes);  // /health, /health/readiness, /health/liveness
app.use('/api/auth', authRoutes);  // /api/auth/login, /api/auth/register, etc.

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
  // card_set: set to 'n/a' if it only contains brand/year tokens or descriptive back text
  try {
    const cs = (out.card_set || '').toLowerCase();
    const br = (out.brand || '').toLowerCase();
    if (cs) {
      let leftovers = cs.replace(br, '');
      leftovers = leftovers.replace(/\b(19\d{2}|20\d{2})\b/g, '');
      // Remove common descriptive terms that aren't card sets (using word boundaries and partial matches)
      leftovers = leftovers.replace(/(mexican|venezuelan|opc|o-pee-chee|chewing|gum)/gi, '');
      leftovers = leftovers.replace(/\bback(s|ookie)?\b/gi, ''); // Handles "back", "backs", "backookie"
      leftovers = leftovers.replace(/\b(rookie|card)s?\b/gi, ''); // Handles singular and plural
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

  console.log('[recordCorrections] Comparing cards - has _original_extraction:', !!originalCard._original_extraction);
  console.log('[recordCorrections] Sample original name:', aiExtraction.name);
  console.log('[recordCorrections] Sample modified name:', modifiedCard.name);

  for (const field of trackFields) {
    const orig = aiExtraction[field];
    const modified = modifiedCard[field];
    // Normalize for comparison (lowercase, trim)
    const origNorm = orig?.toString().toLowerCase().trim() || '';
    const modNorm = modified?.toString().toLowerCase().trim() || '';
    if (origNorm !== modNorm && modNorm !== '') {
      console.log(`[recordCorrections] Field ${field} changed: "${origNorm}" -> "${modNorm}"`);
      corrections.push({ field, original: orig, corrected: modified });
    }
  }

  if (corrections.length === 0) {
    console.log('[recordCorrections] No corrections detected');
    return;
  }

  console.log(`[recordCorrections] Detected ${corrections.length} corrections:`, JSON.stringify(corrections));

  // Build context for the correction
  const context = {
    brand: modifiedCard.brand || originalCard.brand,
    copyright_year: modifiedCard.copyright_year || originalCard.copyright_year,
    sport: modifiedCard.sport || originalCard.sport,
    card_set: modifiedCard.card_set || originalCard.card_set
  };

  // Call Python to record corrections using CorrectionTracker
  const pythonCode = `
import sys, json
from app.correction_tracker import CorrectionTracker

tracker = CorrectionTracker(db_path="data/corrections.db")
data = json.loads(sys.stdin.read())

for corr in data['corrections']:
    tracker.log_correction(
        field_name=corr['field'],
        gpt_value=corr['original'],
        corrected_value=corr['corrected'],
        card_name=data['context'].get('card_name'),
        image_filename=data['context'].get('image_filename'),
        brand=data['context'].get('brand'),
        sport=data['context'].get('sport'),
        copyright_year=data['context'].get('copyright_year'),
        card_set=data['context'].get('card_set')
    )

print(f"Recorded {len(data['corrections'])} corrections", file=sys.stderr)
`;

  return new Promise((resolve) => {
    const pythonProcess = spawn('python', ['-c', pythonCode], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });

    let stderr = '';
    pythonProcess.stderr.on('data', (data) => {
      stderr += data.toString();
    });

    // Add card_name and image_filename to context
    const enrichedContext = {
      ...context,
      card_name: modifiedCard.name || originalCard.name,
      image_filename: modifiedCard.source_file || originalCard.source_file
    };

    pythonProcess.stdin.write(JSON.stringify({ corrections, context: enrichedContext }));
    pythonProcess.stdin.end();

    pythonProcess.on('close', (code) => {
      if (code !== 0) {
        console.error('[CorrectionTracker] Python process exited with code', code);
        console.error('[CorrectionTracker] Error:', stderr);
      } else {
        console.log('[CorrectionTracker]', stderr.trim());
      }
      resolve();
    });

    pythonProcess.on('error', (err) => {
      console.error('[CorrectionTracker] Failed to start Python process:', err);
      resolve();
    });
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
// Reprocess status/cancel endpoints removed - reprocess functionality deprecated

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

// Startup validation
async function validateStartup() {
  const errors = [];
  const warnings = [];

  // check openai api key
  if (!process.env.OPENAI_API_KEY) {
    errors.push('OPENAI_API_KEY environment variable is required');
  } else {
    console.log('✓ openai api key configured');
  }

  // check jwt secret for production
  const environment = process.env.ENVIRONMENT || 'development';
  if (environment === 'production') {
    if (!process.env.JWT_SECRET) {
      errors.push('JWT_SECRET is required for production environment');
    } else if (process.env.JWT_SECRET.length < 32) {
      warnings.push('JWT_SECRET should be at least 32 characters for security');
    } else {
      console.log('✓ jwt secret configured for production');
    }
  }

  // check database url
  if (!process.env.DATABASE_URL) {
    warnings.push('DATABASE_URL not set, using default sqlite database');
  } else {
    console.log('✓ database url configured');
  }

  // check python availability
  try {
    await Promise.race([
      new Promise((resolve, reject) => {
        const pythonCheck = spawn('python', ['--version']);
        pythonCheck.on('close', (code) => {
          if (code === 0) {
            console.log('✓ python available');
            resolve();
          } else {
            reject(new Error('python not available'));
          }
        });
        pythonCheck.on('error', (err) => {
          reject(err);
        });
      }),
      new Promise((_, reject) => setTimeout(() => reject(new Error('python check timeout')), 5000))
    ]);
  } catch (err) {
    warnings.push('python not available - image processing will fail');
  }

  // print warnings
  if (warnings.length > 0) {
    console.log('\n⚠️  warnings:');
    warnings.forEach(w => console.log(`  - ${w}`));
  }

  // print errors and exit if any
  if (errors.length > 0) {
    console.error('\n❌ configuration errors:');
    errors.forEach(e => console.error(`  - ${e}`));
    console.error('\nserver cannot start with configuration errors\n');
    process.exit(1);
  }

  console.log('\n✓ startup validation passed\n');
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

        // Transform data to include UI-friendly confidence and flag indicators
        const transformedData = jsonData.map(card => ({
          ...card,
          _overall_confidence: card._grid_metadata?.confidence || 0.8,
          _has_autocorrections: !!(card._card_set_autocorrected || card._team_autocompleted),
          _has_warnings: !!(card._condition_suspicious || card._year_suspicious),
          _autocorrection_badges: [
            card._card_set_autocorrected && { field: 'card_set', label: 'Auto-fixed' },
            card._team_autocompleted && { field: 'team', label: 'City added' },
          ].filter(Boolean),
          _warning_badges: [
            card._condition_suspicious && { field: 'condition', label: 'Vintage - verify condition', type: 'condition' },
            card._year_suspicious && { field: 'copyright_year', label: 'Unusual year', type: 'year' },
          ].filter(Boolean)
        }));

        cards.push({
          id: baseName,
          jsonFile,
          imageFile,
          data: transformedData
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
  let id;
  try {
    id = req.params.id;
    const { cardIndex } = req.params;
    const { modifiedData } = req.body;

    // Acquire lock to prevent concurrent operations
    const lockResult = acquireLock(id, 'pass-card');
    if (!lockResult.acquired) {
      return res.status(423).json({
        error: 'Card is currently being processed',
        details: `Operation ${lockResult.holder} is in progress`
      });
    }

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

    // Use modified data for the specific card if provided
    const originalCardData = allCardData[parseInt(cardIndex)];
    if (modifiedData) {
      allCardData[parseInt(cardIndex)] = modifiedData;
    }

    // Record corrections for learning system
    // Always compare final card data with _original_extraction
    // This captures corrections even if made via auto-save (not sent in modifiedData)
    const finalCardData = allCardData[parseInt(cardIndex)];
    if (originalCardData._original_extraction) {
      recordCorrections(originalCardData, finalCardData).catch((err) => {
        console.error('[pass-card] Failed to record corrections:', err);
      });
    }

    // Import only the specific card to database
    const cardToImport = [finalCardData];

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
      // Match by base name and position (supports both IMG_2139_pos4.png and IMG_2139_pos4_Name_Number.png)
      const searchPattern = `${id}_pos${pos}`;
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

    // Convert selected text fields to lowercase for consistency
    // Also inject source_file and cropped_back_file
    const processedCardData = cardToImport.map(card => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition', 'notes'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      // Normalize is_player to boolean (handle string "true"/"false" from UI)
      if (processedCard.is_player !== undefined && processedCard.is_player !== null) {
        if (typeof processedCard.is_player === 'string') {
          processedCard.is_player = processedCard.is_player.toLowerCase() === 'true';
        } else if (typeof processedCard.is_player === 'boolean') {
          // Already boolean, keep as-is
        } else {
          // Default to true for any other value
          processedCard.is_player = Boolean(processedCard.is_player);
        }
      } else {
        // Default to true if not provided
        processedCard.is_player = true;
      }
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
    
    // Create undo transaction BEFORE database import
    let transactionId = null;
    const beforeState = {
      json_file: jsonFile,
      json_data: JSON.parse(JSON.stringify(allCardData)),
      card_index: parseInt(cardIndex),
      cropped_back_file: croppedBackFile,
      image_file: imageFile
    };

    try {
      const createTxnProcess = spawn('python', ['-c', `
import sys
import json
from app.crud import create_undo_transaction

data = json.loads(sys.stdin.read())
transaction_id = create_undo_transaction(
    file_id=data['file_id'],
    action_type=data['action_type'],
    before_state=data['before_state'],
    card_index=data.get('card_index')
)
print(transaction_id)
      `], {
        cwd: path.join(__dirname, '../..'),
        stdio: ['pipe', 'pipe', 'pipe']
      });

      createTxnProcess.stdin.write(JSON.stringify({
        file_id: id,
        action_type: 'pass_card',
        before_state: beforeState,
        card_index: parseInt(cardIndex)
      }));
      createTxnProcess.stdin.end();

      const txnOutput = await new Promise((resolve, reject) => {
        let output = '';
        createTxnProcess.stdout.on('data', (data) => { output += data.toString(); });
        createTxnProcess.on('close', (code) => {
          if (code === 0) resolve(output.trim());
          else reject(new Error('Failed to create undo transaction'));
        });
      });

      transactionId = txnOutput;
      console.log(`[pass-card] Created undo transaction: ${transactionId}`);
    } catch (txnErr) {
      console.error(`[pass-card] Warning: Failed to create undo transaction: ${txnErr.message}`);
    }

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
    backup_path = backup_database(os.getenv('DB_PATH', 'cards/verified/trading_cards.db'), os.getenv('DB_BACKUP_DIR', 'backups'))
    print(f"DB backup created: {backup_path}", file=sys.stderr)
except Exception as e:
    print(f"Warning: DB backup failed: {e}", file=sys.stderr)

# Convert selected text fields to lowercase for consistency
text_fields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition']
for card_info in card_data:
    for field in text_fields:
        if field in card_info and isinstance(card_info[field], str):
            card_info[field] = card_info[field].lower()

card_complete_ids = []
with get_session() as session:
    for card_info in card_data:
        try:
            # Create CardCreate instance for validation
            card_create = CardCreate(**card_info)

            # Check for existing card (duplicate detection) to get card_id
            # Use canonical_name for matching if available, otherwise fall back to exact name match
            canonical_name = card_info.get("canonical_name")

            if canonical_name:
                # Use canonical name for duplicate detection (handles name variations)
                existing = session.query(Card).filter(
                    Card.brand == card_info.get("brand"),
                    Card.number == card_info.get("number"),
                    Card.canonical_name == canonical_name,
                    Card.copyright_year == card_info.get("copyright_year")
                ).first()
            else:
                # Fallback to exact name match for backwards compatibility
                existing = session.query(Card).filter(
                    Card.brand == card_info.get("brand"),
                    Card.number == card_info.get("number"),
                    Card.name == card_info.get("name"),
                    Card.copyright_year == card_info.get("copyright_year")
                ).first()

            if existing:
                card_id = existing.id
                print(f"Found existing card: {card_info.get('name')}, adding to cards_complete", file=sys.stderr)
            else:
                # Create new card entry to get card_id
                # Trigger will update this with correct data from cards_complete
                new_card = Card(**card_create.model_dump())
                session.add(new_card)
                session.flush()  # Get the new card's ID
                card_id = new_card.id
                print(f"Created new card: {card_info.get('name')}", file=sys.stderr)

            # Create CardComplete record for each physical card copy
            # Database triggers will automatically update cards table and quantity
            grid_meta = card_info.get('_grid_metadata', {})
            card_complete = CardComplete(
                card_id=card_id,
                source_file=card_info.get('source_file') or card_info.get('original_filename'),
                grid_position=str(grid_meta.get('position') or card_info.get('grid_position', '')),
                original_filename=card_info.get('original_filename'),
                notes=card_info.get('notes'),
                name=card_info.get('name'),
                sport=card_info.get('sport'),
                brand=card_info.get('brand'),
                number=card_info.get('number'),
                copyright_year=card_info.get('copyright_year'),
                team=card_info.get('team'),
                card_set=card_info.get('card_set'),
                condition=card_info.get('condition'),
                is_player=card_info.get('is_player'),
                value_estimate=card_info.get('value_estimate'),
                features=card_info.get('features'),
                cropped_back_file=card_info.get('cropped_back_file')
            )
            session.add(card_complete)
            session.flush()
            card_complete_ids.append(card_complete.id)
            print(f"Added cards_complete record for: {card_info.get('name')} (triggers will sync to cards)", file=sys.stderr)

        except Exception as e:
            print(f"Error processing card {card_info.get('name', 'n/a')}: {e}", file=sys.stderr)
            continue

    session.commit()

# Automatically merge any duplicates created during this import
from app.auto_merge import auto_merge_duplicates_for_card

# Get unique card_ids that were used in this batch
unique_card_ids = list(set([
    session.query(CardComplete).filter(CardComplete.id == cc_id).first().card_id
    for cc_id in card_complete_ids
]))

for card_id in unique_card_ids:
    merged_count = auto_merge_duplicates_for_card(card_id)
    if merged_count > 0:
        print(f"Auto-merged {merged_count} duplicate(s) for card ID {card_id}", file=sys.stderr)

# Output card_complete_ids as JSON to stdout
print(json.dumps({"success": True, "card_complete_ids": card_complete_ids}))
print("Database import completed successfully", file=sys.stderr)
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
      const text = data.toString();
      output += text;
      console.log(`[pass-card] Python stdout: ${text.trim()}`);
    });

    pythonProcess.stderr.on('data', (data) => {
      const text = data.toString();
      error += text;
      console.error(`[pass-card] Python stderr: ${text.trim()}`);
    });

    pythonProcess.on('close', async (code) => {
      try { REPROCESS_JOBS.delete(id); } catch (_) {}
      console.log(`[pass-card] Python exited with code ${code}, allCardData had ${allCardData.length} cards, splicing index ${cardIndex}`);
      console.log(`[pass-card] Full output: ${output.trim()}`);
      console.log(`[pass-card] Full error: ${error.trim()}`);
      if (code === 0) {
        // Parse card_complete_ids from Python output
        let cardCompleteIds = [];
        try {
          const jsonOutput = output.trim().split('\n').find(line => line.startsWith('{'));
          if (jsonOutput) {
            const result = JSON.parse(jsonOutput);
            cardCompleteIds = result.card_complete_ids || [];
            console.log(`[pass-card] Parsed card_complete_ids: ${JSON.stringify(cardCompleteIds)}`);
          }
        } catch (parseErr) {
          console.error(`[pass-card] Warning: Failed to parse card_complete_ids: ${parseErr.message}`);
        }

        // Remove the imported card from the array FIRST, before any async operations
        const cardIdx = parseInt(cardIndex);
        allCardData.splice(cardIdx, 1);
        console.log(`[pass-card] After splice: ${allCardData.length} cards remaining`);

        // Update the JSON file with remaining cards - THIS MUST SUCCEED
        if (allCardData.length > 0) {
          try {
            await atomicJsonUpdate(jsonPath, allCardData);
            console.log(`[pass-card] JSON updated successfully: ${jsonPath}`);
            // Release lock after JSON is safely written
            releaseLock(id);
            console.log(`[pass-card] Unlocked ${id}`);
          } catch (writeErr) {
            console.error(`[pass-card] CRITICAL: Failed to update JSON file: ${writeErr.message}`);
            // Card is already in DB but JSON wasn't updated - try again
            try {
              await atomicJsonUpdate(jsonPath, allCardData);
              console.log(`[pass-card] JSON retry succeeded`);
              releaseLock(id);
              console.log(`[pass-card] Unlocked ${id} after retry`);
            } catch (retryErr) {
              releaseLock(id);
              console.error(`[pass-card] CRITICAL: JSON retry failed: ${retryErr.message}`);
              return res.status(500).json({
                error: 'Card added to database but failed to update pending list. Please refresh.',
                details: retryErr.message
              });
            }
          }

          // Partial verification: do NOT move bulk back image yet (still processing remaining cards)
          // Image will be moved when last card is verified
          console.log(`[pass-card] Partial verification - keeping bulk back in pending for remaining ${allCardData.length} cards`);

          // Track file movements for undo
          const fileMovements = [];

          // Move cropped back to verified/cropped_backs
          if (croppedBackFile) {
            try {
              await fs.mkdir(CROPPED_BACKS_VERIFIED, { recursive: true });
              const sourcePath = path.join(CROPPED_BACKS_PENDING, croppedBackFile);
              const destPath = path.join(CROPPED_BACKS_VERIFIED, croppedBackFile);
              await fs.rename(sourcePath, destPath);
              console.log(`[pass-card] Moved cropped back to verified: ${croppedBackFile}`);

              // Record file movement
              fileMovements.push({
                source: sourcePath,
                dest: destPath,
                file_type: 'cropped_back'
              });
            } catch (cropErr) {
              console.error(`[pass-card] Warning: Failed to move cropped back: ${cropErr.message}`);
            }
          }


          // Update undo transaction with after_state
          if (transactionId) {
            try {
              const updateTxnProcess = spawn('python', ['-c', `
import sys
import json
from app.crud import update_undo_transaction_after_state
from app.file_movement_tracker import FileMovementTracker

data = json.loads(sys.stdin.read())
tracker = FileMovementTracker()

# Record file movements
for movement in data['file_movements']:
    tracker.record_movement(
        source=movement['source'],
        dest=movement['dest'],
        transaction_id=data['transaction_id'],
        file_type=movement.get('file_type')
    )

# Update transaction with after_state
update_undo_transaction_after_state(
    transaction_id=data['transaction_id'],
    after_state=data['after_state']
)
print("Transaction updated successfully")
              `], {
                cwd: path.join(__dirname, '../..'),
                stdio: ['pipe', 'pipe', 'pipe']
              });

              updateTxnProcess.stdin.write(JSON.stringify({
                transaction_id: transactionId,
                file_movements: fileMovements,
                after_state: {
                  card_complete_ids: cardCompleteIds,
                  files_moved: fileMovements.length
                }
              }));
              updateTxnProcess.stdin.end();

              updateTxnProcess.on('close', (code) => {
                if (code === 0) {
                  console.log(`[pass-card] Updated undo transaction ${transactionId}`);
                } else {
                  console.error(`[pass-card] Warning: Failed to update undo transaction`);
                }
              });
            } catch (updateErr) {
              console.error(`[pass-card] Warning: Failed to update transaction: ${updateErr.message}`);
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
          // NOTE: Keep lock held until JSON is deleted to prevent save-progress from recreating it

          const imageFile = bulkBackFiles.find(file => {
            const imgBaseName = path.parse(file).name;
            const imgExt = path.parse(file).ext.toLowerCase();
            return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
          });

          // Track file movements for undo
          const fileMovements = [];

          try {
            // Delete grouped JSON file FIRST (data is now in database)
            await fs.unlink(jsonPath);
            // NOW release the lock - after JSON is deleted
            releaseLock(id);
            console.log(`[pass-card] Unlocked ${id} - all cards done, JSON deleted`);

            // Move image file to verified folder with verified_ prefix (use rename, not copy)
            if (imageFile) {
              const verifiedImageName = getVerifiedFilename(imageFile);
              const verifiedImagePath = path.join(VERIFIED_IMAGES_DIR, verifiedImageName);
              const sourceBulkPath = path.join(PENDING_BULK_BACK_DIR, imageFile);

              // Check if already in verified with ANY extension (avoid duplicates like .HEIC + .jpeg)
              const baseNameWithoutExt = path.parse(verifiedImageName).name;
              const verifiedFiles = await fs.readdir(VERIFIED_IMAGES_DIR);
              const existingFile = verifiedFiles.find(f => path.parse(f).name === baseNameWithoutExt);

              if (existingFile) {
                console.log(`[pass-card] Image already in verified as ${existingFile}, skipping ${verifiedImageName}`);
                // Delete from pending since already verified
                try {
                  await fs.unlink(sourceBulkPath);
                  console.log(`[pass-card] Deleted duplicate from pending: ${imageFile}`);
                } catch (delErr) {
                  console.error(`[pass-card] Warning: Failed to delete duplicate: ${delErr.message}`);
                }
              } else {
                // Not in verified yet, move it (rename = atomic move, no duplicate)
                await fs.rename(sourceBulkPath, verifiedImagePath);
                console.log(`[pass-card] Moved image to verified: ${verifiedImageName}`);

                // Record bulk image movement
                fileMovements.push({
                  source: sourceBulkPath,
                  dest: verifiedImagePath,
                  file_type: 'bulk_back'
                });
              }
            }

            // Move cropped back to verified/cropped_backs (last card)
            if (croppedBackFile) {
              try {
                await fs.mkdir(CROPPED_BACKS_VERIFIED, { recursive: true });
                const sourceCroppedPath = path.join(CROPPED_BACKS_PENDING, croppedBackFile);
                const destCroppedPath = path.join(CROPPED_BACKS_VERIFIED, croppedBackFile);
                await fs.rename(sourceCroppedPath, destCroppedPath);
                console.log(`[pass-card] Moved last cropped back to verified: ${croppedBackFile}`);

                // Record cropped back movement
                fileMovements.push({
                  source: sourceCroppedPath,
                  dest: destCroppedPath,
                  file_type: 'cropped_back'
                });
              } catch (cropErr) {
                console.error(`[pass-card] Warning: Failed to move last cropped back: ${cropErr.message}`);
              }
            }


            // Update undo transaction with after_state
            if (transactionId) {
              try {
                const updateTxnProcess = spawn('python', ['-c', `
import sys
import json
from app.crud import update_undo_transaction_after_state
from app.file_movement_tracker import FileMovementTracker

data = json.loads(sys.stdin.read())
tracker = FileMovementTracker()

# Record file movements
for movement in data['file_movements']:
    tracker.record_movement(
        source=movement['source'],
        dest=movement['dest'],
        transaction_id=data['transaction_id'],
        file_type=movement.get('file_type')
    )

# Update transaction with after_state
update_undo_transaction_after_state(
    transaction_id=data['transaction_id'],
    after_state=data['after_state']
)
print("Transaction updated successfully")
                `], {
                  cwd: path.join(__dirname, '../..'),
                  stdio: ['pipe', 'pipe', 'pipe']
                });

                updateTxnProcess.stdin.write(JSON.stringify({
                  transaction_id: transactionId,
                  file_movements: fileMovements,
                  after_state: {
                    card_complete_ids: cardCompleteIds,
                    files_moved: fileMovements.length,
                    json_deleted: true
                  }
                }));
                updateTxnProcess.stdin.end();

                updateTxnProcess.on('close', (code) => {
                  if (code === 0) {
                    console.log(`[pass-card] Updated undo transaction ${transactionId} (all cards done)`);
                  } else {
                    console.error(`[pass-card] Warning: Failed to update undo transaction`);
                  }
                });
              } catch (updateErr) {
                console.error(`[pass-card] Warning: Failed to update transaction: ${updateErr.message}`);
              }
            }

            // Log verification action (all from this image processed)
            try {
              const py = `from app.logging_system import logger\nlogger.log_verification_action(filename='${(imageFileEarly||'').replace(/'/g,"\'")}', action='pass')`;
              const p = spawn('python', ['-c', py], { cwd: path.join(__dirname, '../..') });
              p.on('error', ()=>{});
            } catch(_) {}

            // Trigger automatic model retraining check (non-blocking, bulk back completed)
            try {
              console.log('[pass-card] Bulk back complete, triggering auto-retrain check...');
              const autoRetrainProc = spawn('python', ['-m', 'app.auto_retrain', '--min-new-cards', '9'], {
                cwd: path.join(__dirname, '../..'),
                detached: true,
                stdio: 'ignore'
              });
              autoRetrainProc.unref();
            } catch(autoRetrainErr) {
              console.log('[pass-card] Auto-retrain check failed (non-critical):', autoRetrainErr.message);
            }

            res.json({
              success: true,
              message: 'Last card verified and imported. All cards from this image processed and archived.',
              remainingCards: 0,
              output: output.trim()
            });
            try { await audit('verify_image_archived', { id, scope: 'all' }); } catch {}
          } catch (moveError) {
            releaseLock(id);
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
        PASS_IN_PROGRESS.delete(id);
        res.status(500).json({
          error: 'Failed to import card to database',
          details: error.trim()
        });
      }
    });

  } catch (error) {
    // Always release lock on error
    const id = req.params?.id;
    if (id) releaseLock(id);
    console.error('Error processing single card pass action:', error);
    res.status(500).json({ error: 'Failed to process single card pass action' });
  }
});

// Handle Pass action for entire photo
app.post('/api/pass/:id', async (req, res) => {
  let id;
  try {
    id = req.params.id;
    const { modifiedData } = req.body;

    // Acquire lock to prevent concurrent operations
    const lockResult = acquireLock(id, 'pass-all');
    if (!lockResult.acquired) {
      return res.status(423).json({
        error: 'Card is currently being processed',
        details: `Operation ${lockResult.holder} is in progress`
      });
    }

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
    const jsonData = JSON.parse(await fs.readFile(path.join(PENDING_VERIFICATION_DIR, jsonFile), 'utf8'));
    let cardData = modifiedData || jsonData;

    // Record corrections for learning system
    // Always compare final data with _original_extraction, regardless of whether user edited via UI
    // This captures all corrections including those made via auto-save
    for (let i = 0; i < cardData.length; i++) {
      if (jsonData[i] && jsonData[i]._original_extraction) {
        recordCorrections(jsonData[i], cardData[i]).catch((err) => {
          console.error('[pass-all] Failed to record corrections:', err);
        });
      }
    }

    // Convert text fields to lowercase for consistency and inject source_file and cropped_back_file
    cardData = cardData.map((card, idx) => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition', 'notes'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      // Normalize is_player to boolean (handle string "true"/"false" from UI)
      if (processedCard.is_player !== undefined && processedCard.is_player !== null) {
        if (typeof processedCard.is_player === 'string') {
          processedCard.is_player = processedCard.is_player.toLowerCase() === 'true';
        } else if (typeof processedCard.is_player === 'boolean') {
          // Already boolean, keep as-is
        } else {
          // Default to true for any other value
          processedCard.is_player = Boolean(processedCard.is_player);
        }
      } else {
        // Default to true if not provided
        processedCard.is_player = true;
      }
      // Ensure source_file is set from the image filename
      if (!processedCard.source_file && imageFile) {
        processedCard.source_file = imageFile;
      }
      if (!processedCard.original_filename && imageFile) {
        processedCard.original_filename = imageFile;
      }
      // Add cropped_back_file for each card
      const gridMeta = card._grid_metadata || {};
      const pos = gridMeta.position !== undefined ? gridMeta.position : idx;
      if (!processedCard.cropped_back_file) {
        processedCard.cropped_back_file = `${id}_pos${pos}.png`;
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
text_fields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition', 'notes']
for card_info in card_data:
    for field in text_fields:
        if field in card_info and isinstance(card_info[field], str):
            card_info[field] = card_info[field].lower()

with get_session() as session:
    for idx, card_info in enumerate(card_data):
        try:
            # Create CardCreate instance for validation
            card_create = CardCreate(**card_info)

            # Check for existing card (duplicate detection) to get card_id
            # Use canonical_name for matching if available, otherwise fall back to exact name match
            canonical_name = card_info.get("canonical_name")

            if canonical_name:
                # Use canonical name for duplicate detection (handles name variations)
                existing = session.query(Card).filter(
                    Card.brand == card_info.get("brand"),
                    Card.number == card_info.get("number"),
                    Card.canonical_name == canonical_name,
                    Card.copyright_year == card_info.get("copyright_year")
                ).first()
            else:
                # Fallback to exact name match for backwards compatibility
                existing = session.query(Card).filter(
                    Card.brand == card_info.get("brand"),
                    Card.number == card_info.get("number"),
                    Card.name == card_info.get("name"),
                    Card.copyright_year == card_info.get("copyright_year")
                ).first()

            if existing:
                card_id = existing.id
                print(f"Found existing card: {card_info.get('name')}, adding to cards_complete")
            else:
                # Create new card entry to get card_id
                # Trigger will update this with correct data from cards_complete
                new_card = Card(**card_create.model_dump())
                session.add(new_card)
                session.flush()  # Get the new card ID
                card_id = new_card.id
                print(f"Created new card: {card_info.get('name')}")

            # Create CardComplete record with full card data for each physical copy
            # Database triggers will automatically update cards table and quantity
            grid_meta = card_info.get('_grid_metadata', {})
            card_complete = CardComplete(
                card_id=card_id,
                source_file=source_file,
                grid_position=str(grid_meta.get('position') or card_info.get('grid_position', idx)),
                original_filename=source_file,
                notes=card_info.get('notes'),
                # Card data (denormalized)
                name=card_info.get('name'),
                sport=card_info.get('sport'),
                brand=card_info.get('brand'),
                number=card_info.get('number'),
                copyright_year=card_info.get('copyright_year'),
                team=card_info.get('team'),
                card_set=card_info.get('card_set'),
                condition=card_info.get('condition'),
                is_player=card_info.get('is_player'),
                value_estimate=card_info.get('value_estimate'),
                features=card_info.get('features'),
                cropped_back_file=card_info.get('cropped_back_file')
            )
            session.add(card_complete)
            print(f"Added cards_complete record for: {card_info.get('name')} (triggers will sync to cards)")

        except Exception as e:
            print(f"Error processing card {card_info.get('name', 'n/a')}: {e}")
            continue

    session.commit()

# Automatically merge any duplicates created during this import
from app.auto_merge import auto_merge_duplicates_for_card

# Get all card_ids that were processed
processed_card_ids = set()
for card_info in card_data:
    try:
        canonical_name = card_info.get("canonical_name")
        if canonical_name:
            card = session.query(Card).filter(
                Card.brand == card_info.get("brand"),
                Card.number == card_info.get("number"),
                Card.canonical_name == canonical_name,
                Card.copyright_year == card_info.get("copyright_year")
            ).first()
        else:
            card = session.query(Card).filter(
                Card.brand == card_info.get("brand"),
                Card.number == card_info.get("number"),
                Card.name == card_info.get("name"),
                Card.copyright_year == card_info.get("copyright_year")
            ).first()
        if card:
            processed_card_ids.add(card.id)
    except:
        pass

for card_id in processed_card_ids:
    merged_count = auto_merge_duplicates_for_card(card_id)
    if merged_count > 0:
        print(f"Auto-merged {merged_count} duplicate(s) for card ID {card_id}")

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
      const text = data.toString();
      output += text;
      console.log(`[pass-all] Python stdout: ${text.trim()}`);
    });

    pythonProcess.stderr.on('data', (data) => {
      const text = data.toString();
      error += text;
      console.error(`[pass-all] Python stderr: ${text.trim()}`);
    });

    pythonProcess.on('close', async (code) => {
      console.log(`[pass-all] Python exited with code ${code} for ${id}`);
      console.log(`[pass-all] Full output: ${output.trim()}`);
      console.log(`[pass-all] Full error: ${error.trim()}`);
      if (code === 0) {
        // Database import successful, now move files to verified folder
        try {
          // Delete grouped JSON file (per-card JSON in verified_final is canonical)
          await fs.unlink(path.join(PENDING_VERIFICATION_DIR, jsonFile));
          console.log(`[pass-all] Deleted JSON: ${jsonFile}`);

          // Move image file to verified/verified_images folder with verified_ prefix
          const verifiedImageName = getVerifiedFilename(imageFile);
          const sourceBulkPath = path.join(PENDING_BULK_BACK_DIR, imageFile);
          const verifiedImagePath = path.join(VERIFIED_IMAGES_DIR, verifiedImageName);

          // Check if already in verified with ANY extension (avoid duplicates like .HEIC + .jpeg)
          const baseNameWithoutExt = path.parse(verifiedImageName).name;
          const verifiedFiles = await fs.readdir(VERIFIED_IMAGES_DIR);
          const existingFile = verifiedFiles.find(f => path.parse(f).name === baseNameWithoutExt);

          if (existingFile) {
            console.log(`[pass-all] Image already in verified as ${existingFile}, skipping ${verifiedImageName}`);
            // Delete from pending since already verified
            try {
              await fs.unlink(sourceBulkPath);
              console.log(`[pass-all] Deleted duplicate from pending: ${imageFile}`);
            } catch (delErr) {
              console.error(`[pass-all] Warning: Failed to delete duplicate: ${delErr.message}`);
            }
          } else {
            await fs.rename(sourceBulkPath, verifiedImagePath);
            console.log(`[pass-all] Moved image to verified: ${verifiedImageName}`);
          }

          // Move all cropped back images to verified cropped backs folder
          const CROPPED_BACKS_PENDING = path.join(PENDING_VERIFICATION_DIR, 'pending_verification_cropped_backs');
          const CROPPED_BACKS_VERIFIED = path.join(VERIFIED_ROOT_DIR, 'verified_cropped_backs');
          try {
            await fs.mkdir(CROPPED_BACKS_VERIFIED, { recursive: true });
            const croppedFiles = await fs.readdir(CROPPED_BACKS_PENDING);
            const matchingCroppedFiles = croppedFiles.filter(f => f.startsWith(id + '_pos'));
            for (const croppedFile of matchingCroppedFiles) {
              await fs.rename(
                path.join(CROPPED_BACKS_PENDING, croppedFile),
                path.join(CROPPED_BACKS_VERIFIED, croppedFile)
              );
              console.log(`[pass-all] Moved cropped back to verified: ${croppedFile}`);
            }
          } catch (cropErr) {
            console.error(`[pass-all] Warning: Failed to move cropped backs: ${cropErr.message}`);
          }

          // Log verification action (pass all)
          try {
            const py = `from app.logging_system import logger\nlogger.log_verification_action(filename='${(imageFile||'').replace(/'/g,"\'")}', action='pass')`;
            const p = spawn('python', ['-c', py], { cwd: path.join(__dirname, '../..') });
            p.on('error', ()=>{});
          } catch(_) {}

          // Trigger automatic model retraining check (non-blocking)
          try {
            console.log('[pass-all] Triggering auto-retrain check...');
            const autoRetrainProc = spawn('python', ['-m', 'app.auto_retrain', '--min-new-cards', '9'], {
              cwd: path.join(__dirname, '../..'),
              detached: true,
              stdio: 'ignore'
            });
            autoRetrainProc.unref();
          } catch(autoRetrainErr) {
            console.log('[pass-all] Auto-retrain check failed (non-critical):', autoRetrainErr.message);
          }

          releaseLock(id);
          res.json({
            success: true,
            message: 'Cards verified, imported to database, and archived successfully',
            output: output.trim()
          });
        } catch (moveError) {
          console.error('[pass-all] Error moving files to verified folder:', moveError);
          releaseLock(id);
          res.json({
            success: true,
            message: 'Cards imported to database but file archiving failed',
            output: output.trim()
          });
        }
      } else {
        console.error(`[pass-all] Python failed with code ${code}: ${error.trim()}`);
        releaseLock(id);
        res.status(500).json({
          error: 'Failed to import card to database',
          details: error.trim()
        });
      }
    });
    
  } catch (error) {
    if (id) releaseLock(id);
    console.error('Error processing pass action:', error);
    res.status(500).json({ error: 'Failed to process pass action' });
  }
});

// Save partial progress for card verification
app.post('/api/save-progress/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const { data, cardIndex } = req.body;

    // Skip if any operation is currently processing this file (prevents race condition)
    const existingLock = FILE_LOCKS.get(id);
    if (existingLock) {
      console.log(`[save-progress] Skipping - ${existingLock.type} in progress for ${id}`);
      return res.json({ success: true, message: `Skipped - ${existingLock.type} in progress`, skipped: true });
    }

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
    const processData = (card, existingCard = null) => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      // Preserve _original_extraction from existing card if available
      if (existingCard && existingCard._original_extraction) {
        processedCard._original_extraction = existingCard._original_extraction;
      }
      return processedCard;
    };

    let finalData;

    // If cardIndex is provided, only update that specific card (single card mode)
    if (cardIndex !== undefined && data.length === 1) {
      finalData = [...existingData];
      if (cardIndex >= 0 && cardIndex < finalData.length) {
        // Record corrections for learning before updating
        const originalCard = existingData[cardIndex];
        const modifiedCard = data[0];
        recordCorrections(originalCard, modifiedCard).catch((err) => {
          console.error('[save-progress] Failed to record corrections:', err);
        });

        finalData[cardIndex] = processData(data[0], existingData[cardIndex]);
      }
      console.log(`[save-progress] Single card mode: updated card ${cardIndex}, total cards: ${finalData.length}`);
    } else {
      // Full array update (entire photo mode) - but merge by grid_position to be safe
      if (data.length === existingData.length) {
        // Same length, safe to replace entirely
        // Record corrections for all changed cards
        for (let i = 0; i < data.length; i++) {
          recordCorrections(existingData[i], data[i]).catch((err) => {
            console.error(`[save-progress] Failed to record corrections for card ${i}:`, err);
          });
        }
        finalData = data.map((card, idx) => processData(card, existingData[idx]));
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
              // Record corrections for this card
              recordCorrections(existingData[idx], incomingCard).catch((err) => {
                console.error(`[save-progress] Failed to record corrections for pos ${pos}:`, err);
              });
              finalData[idx] = processData(incomingCard, existingData[idx]);
            }
          }
        }
      }
      console.log(`[save-progress] Full mode: ${data.length} incoming, ${existingData.length} existing, ${finalData.length} final`);
    }

    // Save merged data to JSON file (atomic write)
    await atomicJsonUpdate(jsonPath, finalData);

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

// Reprocess card data using GPT Vision
app.post('/api/reprocess/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const { mode } = req.body; // 'remaining' or 'all'

    // Find the image file in pending verification bulk back directory
    const bulkBackFiles = await fs.readdir(PENDING_BULK_BACK_DIR);
    const imageFile = bulkBackFiles.find(file => {
      const imgBaseName = path.parse(file).name;
      const imgExt = path.parse(file).ext.toLowerCase();
      return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
    });

    if (!imageFile) {
      return res.status(404).json({ error: 'Image file not found for reprocessing' });
    }

    const imagePath = path.join(PENDING_BULK_BACK_DIR, imageFile);

    // Call Python to reprocess the image with grid_processor
    const pythonProcess = spawn('python', ['-c', `
import sys
from app.grid_processor import reprocess_grid_image

image_path = sys.argv[1]
cards = reprocess_grid_image(image_path)

# Output JSON
import json
print(json.dumps(cards))
`, imagePath], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
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
          const reprocessedCards = JSON.parse(output);
          res.json({ success: true, data: reprocessedCards });
        } catch (parseError) {
          console.error('Failed to parse reprocessed data:', parseError);
          res.status(500).json({ error: 'Failed to parse reprocessed data', details: parseError.message });
        }
      } else {
        console.error('Reprocess failed:', error);
        res.status(500).json({ error: 'Reprocessing failed', details: error.trim() });
      }
    });

  } catch (error) {
    console.error('Error reprocessing card:', error);
    res.status(500).json({ error: 'Failed to reprocess card' });
  }
});

app.post('/api/fail-card/:id/:cardIndex', async (req, res) => {
  let id;
  try {
    id = req.params.id;
    const { cardIndex } = req.params;

    // Acquire lock to prevent concurrent operations
    const lockResult = acquireLock(id, 'fail-card');
    if (!lockResult.acquired) {
      return res.status(423).json({
        error: 'Card is currently being processed',
        details: `Operation ${lockResult.holder} is in progress`
      });
    }

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

    // Get failed card position before removing
    const cardIdx = parseInt(cardIndex);
    const failedCard = allCardData[cardIdx];
    const gridMeta = failedCard?._grid_metadata || {};
    const failedPosition = gridMeta.position !== undefined ? gridMeta.position : cardIdx;

    // Archive cropped back image instead of deleting (enables undo recovery)
    const CROPPED_BACKS_PENDING = path.join(PENDING_VERIFICATION_DIR, 'pending_verification_cropped_backs');
    const FAILED_ARCHIVE_DIR = path.join(__dirname, '../../cards/archive/failed_cropped_backs');
    try {
      if (failedCard) {
        const croppedFiles = await fs.readdir(CROPPED_BACKS_PENDING);
        // Match by base name and position
        const searchPattern = `${id}_pos${failedPosition}_`;
        let croppedBackFile = croppedFiles.find(f => f.startsWith(searchPattern));
        // If not found by position, try by name/number
        if (!croppedBackFile && failedCard.name && failedCard.number) {
          const namePart = failedCard.name.replace(/\s+/g, '_').replace(/[^a-zA-Z0-9_]/g, '');
          croppedBackFile = croppedFiles.find(f =>
            f.includes(`_${namePart}_`) && f.includes(`_${failedCard.number}.`)
          );
        }
        // Archive the cropped back if found (instead of deleting)
        if (croppedBackFile) {
          await fs.mkdir(FAILED_ARCHIVE_DIR, { recursive: true });
          const timestamp = new Date().toISOString().replace(/:/g, '-').replace(/\..+/, '');
          const archiveName = `${id}_pos${failedPosition}_${timestamp}.png`;
          await fs.rename(
            path.join(CROPPED_BACKS_PENDING, croppedBackFile),
            path.join(FAILED_ARCHIVE_DIR, archiveName)
          );
          console.log(`[fail-card] Archived cropped back: ${archiveName}`);
        }
      }
    } catch (cropErr) {
      console.log(`[fail-card] No cropped_backs dir or error: ${cropErr.message}`);
    }

    // Find the bulk back image
    const imageFile = bulkBackFiles.find(file => {
      const imgBaseName = path.parse(file).name;
      const imgExt = path.parse(file).ext.toLowerCase();
      return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
    });

    // Move bulk back image to unprocessed with position info
    let movedImageName = null;
    if (imageFile) {
      const ext = path.extname(imageFile);
      const baseName = path.parse(imageFile).name;
      // Append failed position to filename so user knows which card failed
      movedImageName = `${baseName}_failed_pos${failedPosition}${ext}`;
      try {
        await fs.rename(
          path.join(PENDING_BULK_BACK_DIR, imageFile),
          path.join(UNPROCESSED_BULK_BACK_DIR, movedImageName)
        );
        console.log(`[fail-card] Moved image back to unprocessed: ${movedImageName}`);
      } catch (moveErr) {
        console.error(`[fail-card] Error moving image: ${moveErr.message}`);
        movedImageName = null;
      }
    }

    // Delete all cropped backs for this image since we're moving it back
    try {
      const croppedFiles = await fs.readdir(CROPPED_BACKS_PENDING);
      for (const f of croppedFiles) {
        if (f.startsWith(`${id}_pos`)) {
          await fs.unlink(path.join(CROPPED_BACKS_PENDING, f));
          console.log(`[fail-card] Deleted cropped back: ${f}`);
        }
      }
    } catch (e) {
      // Ignore errors cleaning up cropped backs
    }

    // Delete the JSON file since we're moving the image back
    try {
      await fs.unlink(jsonPath);
      console.log(`[fail-card] Deleted JSON: ${jsonFile}`);
    } catch (e) {
      console.error(`[fail-card] Error deleting JSON: ${e.message}`);
    }

    releaseLock(id);
    res.json({
      success: true,
      message: movedImageName
        ? `Card at position ${failedPosition} failed. Image moved back to unprocessed as ${movedImageName}`
        : `Card at position ${failedPosition} failed. Pending data removed.`,
      movedImage: movedImageName,
      failedPosition: failedPosition,
      remainingCards: 0
    });

  } catch (error) {
    if (id) releaseLock(id);
    console.error('Error processing single card fail action:', error);
    res.status(500).json({ error: 'Failed to process single card fail action' });
  }
});

// Handle Fail action for entire photo
app.post('/api/fail/:id', async (req, res) => {
  let id;
  try {
    id = req.params.id;

    // Acquire lock to prevent concurrent operations
    const lockResult = acquireLock(id, 'fail-all');
    if (!lockResult.acquired) {
      return res.status(423).json({
        error: 'Card is currently being processed',
        details: `Operation ${lockResult.holder} is in progress`
      });
    }

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

    releaseLock(id);
    res.json({ success: true, message: 'Cards rejected. Image moved back to unprocessed for reprocessing.' });
  } catch (error) {
    if (id) releaseLock(id);
    console.error('Error processing fail action:', error);
    res.status(500).json({ error: 'Failed to process fail action' });
  }
});

// Get all cards from database with pagination and filtering
app.get('/api/cards', async (req, res) => {
  try {
    const { page = 1, limit = 20, search = '', sport = '', brand = '', condition = '', team = '', year = '', card_set = '', name = '', number = '', features = '', is_player = '', sortBy = '', sortDir = 'asc' } = req.query;

    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card, CardComplete
from sqlalchemy import func, or_, and_, asc, desc

page = ${parseInt(page)}
limit = ${parseInt(limit)}
search = "${search}"
sport = "${sport}"
brand = "${brand}"
condition = "${condition}"
team = "${team}"
year = "${year}"
card_set = "${card_set}"
name = "${req.query.name || ''}"
number = "${req.query.number || ''}"
features = "${req.query.features || ''}"
is_player = "${req.query.is_player || ''}"
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
    if team:
        filters.append(Card.team.ilike(f"%{team}%"))
    if year:
        filters.append(Card.copyright_year == int(year))
    if card_set:
        filters.append(Card.card_set.ilike(f"%{card_set}%"))
    if name:
        filters.append(Card.name.ilike(f"%{name}%"))
    if number:
        filters.append(Card.number.ilike(f"%{number}%"))
    if features:
        filters.append(Card.features.ilike(f"%{features}%"))
    if is_player:
        filters.append(Card.is_player == (is_player.lower() == 'true'))

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
        'is_player': Card.is_player,
        'features': Card.features,
        'value_estimate': Card.value_estimate,
        'quantity': Card.quantity,
        'date_added': Card.date_added,
    }

    # Special handling for value_estimate - extract numeric value for sorting
    if sort_by == 'value_estimate':
        import re
        # Use SQL CAST with extracted number for proper numeric sorting
        # Extract first number from value_estimate string (e.g., "$1-5" -> 1, "$10-25" -> 10)
        # SQLite: use substr and instr to extract digits, then cast
        # Simpler approach: sort in Python after fetching
        cards_all = query.all()
        def extract_price(card):
            val = card.value_estimate or ''
            nums = re.findall(r'[\\d.]+', str(val))
            if nums:
                try:
                    return float(nums[0])
                except:
                    pass
            return 0.0 if sort_dir == 'desc' else float('inf')
        cards_all.sort(key=extract_price, reverse=(sort_dir == 'desc'))
        total = len(cards_all)
        # Use CardComplete as ground truth for total quantity
        total_quantity = session.query(func.count(CardComplete.id)).scalar() or 0
        offset = (page - 1) * limit
        cards = cards_all[offset:offset + limit]
    else:
        col = valid_cols.get(sort_by)
        if col is not None:
            if sort_dir == 'desc':
                query = query.order_by(desc(col))
            else:
                query = query.order_by(asc(col))

        # Get total count and total quantity
        total = query.count()
        # Use CardComplete as ground truth for total quantity
        total_quantity = session.query(func.count(CardComplete.id)).scalar() or 0

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
                "is_player": card.is_player,
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
            "totalQuantity": total_quantity,
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
import re
import sys
from datetime import datetime
from app.database import get_session
from app.models import Card
from app.correction_tracker import CorrectionTracker

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

    # Capture original values for correction tracking
    original_values = {
        'name': card.name,
        'brand': card.brand,
        'team': card.team,
        'card_set': card.card_set,
        'copyright_year': card.copyright_year,
        'number': card.number,
        'condition': card.condition,
        'sport': card.sport
    }

    # Update fields
    for key, value in card_data.items():
        if hasattr(card, key) and key != 'id':
            setattr(card, key, value)

    session.commit()

    # Record corrections for changed fields
    tracker = CorrectionTracker(db_path="data/corrections.db")
    track_fields = ['name', 'brand', 'team', 'card_set', 'copyright_year', 'number', 'condition', 'sport']
    for field in track_fields:
        if field in card_data:
            orig = original_values.get(field) or ''
            new_val = card_data.get(field) or ''
            orig_norm = str(orig).lower().strip()
            new_norm = str(new_val).lower().strip()
            if orig_norm != new_norm and new_norm:
                tracker.log_correction(
                    field_name=field,
                    gpt_value=orig,
                    corrected_value=new_val,
                    card_name=card_data.get('name'),
                    brand=card_data.get('brand'),
                    sport=card_data.get('sport'),
                    copyright_year=card_data.get('copyright_year'),
                    card_set=card_data.get('card_set')
                )

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

// Unified file operation lock system to prevent race conditions
const FILE_LOCKS = new Map();
const LOCK_TIMEOUT_MS = 30000; // 30 seconds

function acquireLock(fileId, operationType, timeoutMs = LOCK_TIMEOUT_MS) {
  const existing = FILE_LOCKS.get(fileId);
  if (existing) {
    // Check if lock expired
    if (Date.now() - existing.timestamp > timeoutMs) {
      console.log(`[LOCK] Expired lock on ${fileId} (type: ${existing.type}), acquiring for ${operationType}`);
      releaseLock(fileId);
    } else {
      console.log(`[LOCK] Cannot acquire lock on ${fileId} for ${operationType}, held by ${existing.type}`);
      return { acquired: false, holder: existing.type };
    }
  }
  FILE_LOCKS.set(fileId, { type: operationType, timestamp: Date.now(), timeout: timeoutMs });
  console.log(`[LOCK] Acquired lock on ${fileId} for ${operationType}`);
  return { acquired: true };
}

function releaseLock(fileId) {
  const existing = FILE_LOCKS.get(fileId);
  if (existing) {
    console.log(`[LOCK] Released lock on ${fileId} (was: ${existing.type})`);
    FILE_LOCKS.delete(fileId);
  }
}

// Cleanup expired locks every 60 seconds
setInterval(() => {
  const now = Date.now();
  for (const [fileId, lock] of FILE_LOCKS.entries()) {
    if (now - lock.timestamp > lock.timeout) {
      console.log(`[LOCK] Auto-releasing expired lock on ${fileId} (type: ${lock.type})`);
      releaseLock(fileId);
    }
  }
}, 60000);

// Atomic JSON file update using write-rename pattern
async function atomicJsonUpdate(jsonPath, data) {
  const tmpPath = `${jsonPath}.tmp.${Date.now()}.${Math.random().toString(36).substr(2, 9)}`;
  try {
    // Write to temporary file first
    await fs.writeFile(tmpPath, JSON.stringify(data, null, 2));
    // Atomic rename (POSIX guarantees atomicity)
    await fs.rename(tmpPath, jsonPath);
  } catch (error) {
    // Clean up temporary file on error
    try {
      await fs.unlink(tmpPath);
    } catch (_) {}
    throw error;
  }
}

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

    // Clear any existing progress file to prevent showing stale 100% progress
    try {
      await fs.unlink(PYTHON_PROGRESS_FILE).catch(() => {});
    } catch {}


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
    years = session.query(distinct(Card.copyright_year)).filter(Card.copyright_year.isnot(None)).all()

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
        "features": sorted(list(all_features)),
        "years": sorted([y[0] for y in years if y[0]], reverse=True)
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
            "is_player": card.is_player
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

// Get field-specific autocomplete suggestions
app.post('/api/field-autocomplete', async (req, res) => {
  try {
    const { field, query, limit = 10 } = req.body;

    if (!field || !query || query.length < 1) {
      return res.json({ suggestions: [] });
    }

    const allowedFields = ['name', 'sport', 'brand', 'team', 'card_set', 'number'];
    if (!allowedFields.includes(field)) {
      return res.status(400).json({ error: 'Invalid field name' });
    }

    const pythonProcess = spawn('python', ['-c', `
import json
from app.database import get_session
from app.models import Card
from sqlalchemy import func, distinct

search_field = ${JSON.stringify(field)}
search_query = ${JSON.stringify(query || '')}
search_limit = ${limit}

with get_session() as session:
    # Get distinct values for the field that match the query
    field_attr = getattr(Card, search_field)

    query_obj = session.query(distinct(field_attr)).filter(
        field_attr.isnot(None),
        func.lower(field_attr).like(f"%{search_query.lower()}%")
    )

    # Exclude empty and 'unknown' values
    query_obj = query_obj.filter(
        field_attr != '',
        func.lower(field_attr) != 'unknown'
    )

    # Order by length first (shorter matches first), then alphabetically
    results = query_obj.order_by(
        func.length(field_attr),
        field_attr
    ).limit(search_limit).all()

    suggestions = [r[0] for r in results if r[0]]

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
          res.status(500).json({ error: 'Failed to parse autocomplete results' });
        }
      } else {
        res.status(500).json({
          error: 'Failed to get autocomplete suggestions',
          details: error.trim()
        });
      }
    });

  } catch (error) {
    console.error('Error getting field autocomplete:', error);
    res.status(500).json({ error: 'Failed to get autocomplete suggestions' });
  }
});

// Get full card data by name for autofill
app.post('/api/card-by-name', async (req, res) => {
  try {
    const { name } = req.body;

    if (!name || name.length < 1) {
      return res.json({ card: null });
    }

    const pythonProcess = spawn('python', ['-c', `
import json
from app.database import get_session
from app.models import Card
from sqlalchemy import func

search_name = ${JSON.stringify(name || '')}

with get_session() as session:
    # Find the most recent card with this name
    card = session.query(Card).filter(
        func.lower(Card.name) == search_name.lower()
    ).order_by(Card.date_added.desc()).first()

    if card:
        card_data = {
            'name': card.name,
            'sport': card.sport,
            'brand': card.brand,
            'team': card.team,
            'card_set': card.card_set,
            'number': card.number,
            'copyright_year': card.copyright_year,
            'condition': card.condition,
            'is_player': card.is_player,
            'features': card.features
        }
        print(json.dumps({"card": card_data}))
    else:
        print(json.dumps({"card": None}))
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
          res.json({ card: null });
        }
      } else {
        res.json({ card: null });
      }
    });

  } catch (error) {
    console.error('Error getting card by name:', error);
    res.status(500).json({ error: 'Failed to get card data' });
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
from app.models import Card, CardComplete
from sqlalchemy import func, distinct
import json

with get_session() as session:
    total_cards = session.query(func.count(Card.id)).scalar()
    # Use CardComplete as ground truth for total quantity
    total_quantity = session.query(func.count(CardComplete.id)).scalar() or 0
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

// Smart cropped back image endpoint - checks both pending and verified directories
app.get('/api/cropped-back-image/:filename', async (req, res) => {
  const { filename } = req.params;
  const pendingPath = path.join(CROPPED_BACKS_DIR, filename);
  const verifiedPath = path.join(VERIFIED_CROPPED_BACKS_DIR, filename);

  // Try exact match in pending first
  try {
    await fs.access(pendingPath);
    return res.sendFile(pendingPath);
  } catch (e) {}

  // Try exact match in verified
  try {
    await fs.access(verifiedPath);
    console.log(`[cropped-back] Found exact match in verified: ${filename}`);
    return res.sendFile(verifiedPath);
  } catch (e) {
    console.log(`[cropped-back] Not found in verified: ${filename}`);
  }

  // Exact file not found - try position-based fallbacks
  // filename format: stem_posN_Name_Number.ext or stem_posN.ext (png or jpg)
  const posMatch = filename.match(/^(.+)_pos(\d+)(?:_.+)?\.(png|jpg)$/i);
  if (posMatch) {
    const stem = posMatch[1];
    const pos = posMatch[2];

    // Check verified directory first for position match (with or without name suffix, any extension)
    try {
      const verifiedFiles = await fs.readdir(VERIFIED_CROPPED_BACKS_DIR);
      // Try exact position with suffix first, then without suffix
      let fallback = verifiedFiles.find(f => f.startsWith(stem) && f.includes(`_pos${pos}_`));
      if (!fallback) {
        // Match stem_pos1.jpg or stem_pos1.png (no trailing underscore/suffix)
        fallback = verifiedFiles.find(f => f.match(new RegExp(`^${stem}_pos${pos}\\.(png|jpg)$`, 'i')));
      }
      if (fallback) {
        return res.sendFile(path.join(VERIFIED_CROPPED_BACKS_DIR, fallback));
      }
    } catch (readErr) {}

    // Check pending directory for position match
    try {
      const pendingFiles = await fs.readdir(CROPPED_BACKS_DIR);
      // Try exact position with suffix first, then without suffix
      let fallback = pendingFiles.find(f => f.startsWith(stem) && f.includes(`_pos${pos}_`));
      if (!fallback) {
        fallback = pendingFiles.find(f => f.match(new RegExp(`^${stem}_pos${pos}\\.(png|jpg)$`, 'i')));
      }
      if (fallback) {
        return res.sendFile(path.join(CROPPED_BACKS_DIR, fallback));
      }

      // Last resort: any position from pending (shouldn't normally happen)
      fallback = pendingFiles.find(f => f.startsWith(stem) && f.includes('_pos'));
      if (fallback) {
        console.log(`[cropped-back] Using fallback image from pending: ${fallback} for requested: ${filename}`);
        return res.sendFile(path.join(CROPPED_BACKS_DIR, fallback));
      }
    } catch (readErr) {}

    // Last resort: any position from verified (for position mismatches)
    try {
      const verifiedFiles = await fs.readdir(VERIFIED_CROPPED_BACKS_DIR);
      let fallback = verifiedFiles.find(f => f.startsWith(stem) && f.includes('_pos'));
      if (fallback) {
        console.log(`[cropped-back] Using fallback image from verified: ${fallback} for requested: ${filename}`);
        return res.sendFile(path.join(VERIFIED_CROPPED_BACKS_DIR, fallback));
      }
    } catch (readErr) {}
  }

  // No fallback found
  res.status(404).send('Cropped image not found');
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
            "notes": ic.notes,
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
from app.correction_tracker import CorrectionTracker

copy_id = ${parseInt(id)}
updates = json.loads('''${JSON.stringify(updates).replace(/'/g, "\\'")}''')

with get_session() as session:
    copy = session.query(CardComplete).filter(CardComplete.id == copy_id).first()
    if not copy:
        print(json.dumps({"success": False, "error": "Individual card not found"}))
        sys.exit(0)

    # Capture original values for correction tracking
    original_values = {
        'condition': copy.condition,
        'value_estimate': copy.value_estimate,
        'features': copy.features,
        'notes': copy.notes
    }

    # Update allowed fields
    allowed_fields = ['condition', 'value_estimate', 'features', 'notes']
    for field in allowed_fields:
        if field in updates:
            setattr(copy, field, updates[field])

    session.commit()

    # Record corrections for changed fields (only condition tracked for learning)
    tracker = CorrectionTracker(db_path="data/corrections.db")
    track_fields = ['condition']
    for field in track_fields:
        if field in updates:
            orig = original_values.get(field) or ''
            new_val = updates.get(field) or ''
            orig_norm = str(orig).lower().strip()
            new_norm = str(new_val).lower().strip()
            if orig_norm != new_norm and new_norm:
                tracker.log_correction(
                    field_name=field,
                    gpt_value=orig,
                    corrected_value=new_val,
                    card_name=copy.name,
                    brand=copy.brand,
                    sport=copy.sport,
                    copyright_year=copy.copyright_year,
                    card_set=copy.card_set
                )

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
      console.log('[refresh-prices] Exit code:', code);
      console.log('[refresh-prices] Output:', output);
      console.log('[refresh-prices] Error:', error);

      if (code === 0) {
        try {
          const result = JSON.parse(output);
          console.log('[refresh-prices] Parsed result:', result);
          res.json({ success: true, ...result });
        } catch (e) {
          console.log('[refresh-prices] JSON parse error:', e.message);
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
    const actionType = undoneAction.action;

    // Handle different action types
    if (actionType === 'pass_card' || actionType === 'pass_all') {
      console.log(`[undo] Reversing database import and file movements for ${actionType}`);

      // Find the corresponding UndoTransaction by file_id, action_type, and timestamp proximity
      try {
        const findTxnProcess = spawn('python', ['-c', `
import sys
import json
from app.crud import get_transactions_for_file
from datetime import datetime

file_id = sys.argv[1]
action_type = sys.argv[2]
card_index = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != 'null' else None
timestamp_str = sys.argv[4]

# Parse timestamp
target_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

# Get all non-reversed transactions for this file
transactions = get_transactions_for_file(file_id)

# Find matching transaction (by action_type and card_index if provided)
matching_txn = None
for txn in transactions:
    if txn.action_type == action_type:
        if card_index is not None and txn.card_index is not None:
            if str(txn.card_index) == str(card_index):
                matching_txn = txn
                break
        elif card_index is None and txn.card_index is None:
            matching_txn = txn
            break

if matching_txn:
    print(json.dumps({
        "success": True,
        "transaction_id": matching_txn.transaction_id,
        "action_type": matching_txn.action_type
    }))
else:
    print(json.dumps({"success": False, "error": "No matching transaction found"}))
        `, id, actionType, String(undoneAction.cardIndex || 'null'), undoneAction.timestamp], {
          cwd: path.join(__dirname, '../..'),
          stdio: ['pipe', 'pipe', 'pipe']
        });

        const txnOutput = await new Promise((resolve, reject) => {
          let output = '';
          let error = '';
          findTxnProcess.stdout.on('data', (data) => { output += data.toString(); });
          findTxnProcess.stderr.on('data', (data) => { error += data.toString(); });
          findTxnProcess.on('close', (code) => {
            if (code === 0) {
              try {
                const result = JSON.parse(output.trim());
                resolve(result);
              } catch (e) {
                reject(new Error(`Failed to parse transaction output: ${output}`));
              }
            } else {
              reject(new Error(`Transaction lookup failed: ${error}`));
            }
          });
        });

        if (txnOutput.success && txnOutput.transaction_id) {
          const transactionId = txnOutput.transaction_id;
          console.log(`[undo] Found transaction ${transactionId}, reversing...`);

          // Reverse database import and file movements
          const undoProcess = spawn('python', ['-c', `
import sys
import json
from app.crud import undo_card_import, mark_transaction_reversed
from app.file_movement_tracker import FileMovementTracker

transaction_id = sys.argv[1]

# Reverse database changes
db_result = undo_card_import(transaction_id)
print(f"Database rollback: deleted {db_result['affected_cards']} cards_complete records", file=sys.stderr)

# Reverse file movements
tracker = FileMovementTracker()
file_result = tracker.reverse_movement(transaction_id)
print(f"File reversal: moved {file_result['reversed_count']} files back", file=sys.stderr)

# Mark transaction as reversed
mark_transaction_reversed(transaction_id)

# Output result
result = {
    "success": True,
    "cards_deleted": db_result['affected_cards'],
    "files_reversed": file_result['reversed_count'],
    "errors": file_result.get('errors', [])
}
print(json.dumps(result))
          `, transactionId], {
            cwd: path.join(__dirname, '../..'),
            stdio: ['pipe', 'pipe', 'pipe']
          });

          const undoOutput = await new Promise((resolve, reject) => {
            let output = '';
            let error = '';
            undoProcess.stdout.on('data', (data) => { output += data.toString(); });
            undoProcess.stderr.on('data', (data) => {
              const text = data.toString();
              error += text;
              console.log(`[undo] ${text.trim()}`);
            });
            undoProcess.on('close', (code) => {
              if (code === 0) {
                try {
                  const result = JSON.parse(output.trim());
                  resolve(result);
                } catch (e) {
                  reject(new Error(`Failed to parse undo output: ${output}`));
                }
              } else {
                reject(new Error(`Undo process failed: ${error}`));
              }
            });
          });

          console.log(`[undo] Rollback complete: ${undoOutput.cards_deleted} cards deleted, ${undoOutput.files_reversed} files reversed`);
          if (undoOutput.errors && undoOutput.errors.length > 0) {
            console.error(`[undo] File reversal errors:`, undoOutput.errors);
          }
        } else {
          console.warn(`[undo] No transaction found for ${actionType} - continuing with JSON restore only`);
        }
      } catch (txnErr) {
        console.error(`[undo] Warning: Transaction reversal failed: ${txnErr.message}`);
        // Continue with JSON restoration even if transaction reversal fails
      }
    } else if (actionType === 'fail_card') {
      // Attempt to restore cropped back from archive
      console.log(`[undo] Attempting to restore cropped back from archive for ${id}`);
      // TODO: Implement cropped back restoration from archive
    }

    // Restore the beforeData to the JSON file (for all action types)
    if (undoneAction.beforeData) {
      const jsonPath = path.join(PENDING_VERIFICATION_DIR, `${id}.json`);

      // Check if JSON still exists (might have been deleted on pass/fail all)
      try {
        await fs.access(jsonPath);
        // File exists, write beforeData back (atomic)
        await atomicJsonUpdate(jsonPath, undoneAction.beforeData);
        console.log(`[undo] Restored ${id}.json to state before ${undoneAction.action}`);
      } catch (e) {
        // File doesn't exist, recreate it (atomic)
        await atomicJsonUpdate(jsonPath, undoneAction.beforeData);
        console.log(`[undo] Recreated ${id}.json from history`);
      }
    }

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

// Undo all actions for a file back to original extraction
app.post('/api/undo-all/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const historyFile = path.join(VERIFICATION_HISTORY_DIR, `${id}_history.json`);

    // Read history
    let history = [];
    try {
      const data = await fs.readFile(historyFile, 'utf8');
      history = JSON.parse(data);
    } catch (e) {
      return res.status(404).json({ error: 'No history found for this file' });
    }

    if (history.length === 0) {
      return res.status(400).json({ error: 'No actions to undo' });
    }

    console.log(`[undo-all] Reversing ${history.length} actions for ${id}`);

    let undoneCount = 0;
    let errors = [];

    // Process actions in reverse order (most recent first)
    for (let i = history.length - 1; i >= 0; i--) {
      const action = history[i];
      const actionType = action.action;

      try {
        // Handle pass_card and pass_all actions
        if (actionType === 'pass_card' || actionType === 'pass_all') {
          console.log(`[undo-all] Reversing ${actionType} (${i + 1}/${history.length})`);

          // Find and reverse transaction
          try {
            const findTxnProcess = spawn('python', ['-c', `
import sys
import json
from app.crud import get_transactions_for_file
from datetime import datetime

file_id = sys.argv[1]
action_type = sys.argv[2]
card_index = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] != 'null' else None

# Get all non-reversed transactions for this file
transactions = get_transactions_for_file(file_id)

# Find matching transaction
matching_txn = None
for txn in transactions:
    if txn.action_type == action_type:
        if card_index is not None and txn.card_index is not None:
            if str(txn.card_index) == str(card_index):
                matching_txn = txn
                break
        elif card_index is None and txn.card_index is None:
            matching_txn = txn
            break

if matching_txn:
    print(json.dumps({
        "success": True,
        "transaction_id": matching_txn.transaction_id
    }))
else:
    print(json.dumps({"success": False}))
            `, id, actionType, String(action.cardIndex || 'null')], {
              cwd: path.join(__dirname, '../..'),
              stdio: ['pipe', 'pipe', 'pipe']
            });

            const txnOutput = await new Promise((resolve, reject) => {
              let output = '';
              findTxnProcess.stdout.on('data', (data) => { output += data.toString(); });
              findTxnProcess.on('close', (code) => {
                if (code === 0) {
                  try {
                    resolve(JSON.parse(output.trim()));
                  } catch (e) {
                    reject(new Error(`Parse error: ${output}`));
                  }
                } else {
                  reject(new Error('Transaction lookup failed'));
                }
              });
            });

            if (txnOutput.success && txnOutput.transaction_id) {
              // Reverse the transaction
              const undoProcess = spawn('python', ['-c', `
import sys
from app.crud import undo_card_import, mark_transaction_reversed
from app.file_movement_tracker import FileMovementTracker

transaction_id = sys.argv[1]

# Reverse database changes
undo_card_import(transaction_id)

# Reverse file movements
tracker = FileMovementTracker()
tracker.reverse_movement(transaction_id)

# Mark as reversed
mark_transaction_reversed(transaction_id)

print("OK")
              `, txnOutput.transaction_id], {
                cwd: path.join(__dirname, '../..'),
                stdio: ['pipe', 'pipe', 'pipe']
              });

              await new Promise((resolve, reject) => {
                undoProcess.on('close', (code) => {
                  if (code === 0) resolve();
                  else reject(new Error('Undo failed'));
                });
              });

              console.log(`[undo-all] Reversed transaction ${txnOutput.transaction_id}`);
            }
          } catch (txnErr) {
            console.error(`[undo-all] Warning: Failed to reverse transaction for action ${i}: ${txnErr.message}`);
            errors.push(`Action ${i}: ${txnErr.message}`);
          }
        }

        undoneCount++;
      } catch (actionErr) {
        console.error(`[undo-all] Error processing action ${i}:`, actionErr);
        errors.push(`Action ${i}: ${actionErr.message}`);
      }
    }

    // Clear the history (atomic)
    await atomicJsonUpdate(historyFile, []);
    console.log(`[undo-all] Cleared history for ${id}`);

    // Restore the original extraction (first entry in history)
    if (history.length > 0 && history[0].beforeData) {
      const jsonPath = path.join(PENDING_VERIFICATION_DIR, `${id}.json`);
      try {
        await atomicJsonUpdate(jsonPath, history[0].beforeData);
        console.log(`[undo-all] Restored original extraction to ${id}.json`);
      } catch (restoreErr) {
        console.error(`[undo-all] Warning: Failed to restore original JSON: ${restoreErr.message}`);
        errors.push(`JSON restore: ${restoreErr.message}`);
      }
    }

    res.json({
      success: true,
      actionsUndone: undoneCount,
      totalActions: history.length,
      errors: errors.length > 0 ? errors : undefined
    });
  } catch (error) {
    console.error('[undo-all] Error:', error);
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

// ============================================================================
// Recent Activity Endpoint
// ============================================================================

// Recent activity endpoint - returns last 10 verification actions across all files
app.get('/api/recent-activity', async (req, res) => {
  try {
    const limit = parseInt(req.query.limit) || 10;
    const allActivity = [];

    // Read all history files from verification history directory
    const historyDir = VERIFICATION_HISTORY_DIR;

    try {
      await fs.mkdir(historyDir, { recursive: true });
      const files = await fs.readdir(historyDir);

      for (const file of files) {
        if (file.endsWith('_history.json')) {
          const fileId = file.replace('_history.json', '');
          const historyPath = path.join(historyDir, file);

          try {
            const content = await fs.readFile(historyPath, 'utf8');
            const history = JSON.parse(content);

            // Add each action with file context
            history.forEach(action => {
              allActivity.push({
                ...action,
                fileId: fileId,
                fileName: `${fileId}.json`
              });
            });
          } catch (e) {
            console.error(`[recent-activity] Error reading ${file}:`, e);
          }
        }
      }

      // Sort by timestamp (most recent first) and take the limit
      allActivity.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
      const recentActivity = allActivity.slice(0, limit);

      res.json({
        activity: recentActivity,
        count: recentActivity.length,
        total: allActivity.length
      });
    } catch (e) {
      // History directory doesn't exist or is empty
      res.json({ activity: [], count: 0, total: 0 });
    }
  } catch (error) {
    console.error('[recent-activity] Error:', error);
    res.status(500).json({ error: error.message, activity: [], count: 0, total: 0 });
  }
});

// Search for previously verified cards by name prefix (for autofill)
app.get('/api/search-cards', async (req, res) => {
  try {
    const { query = '', limit = 10 } = req.query;

    if (!query || query.trim().length < 2) {
      return res.json({ cards: [] });
    }

    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card

query = "${query.toLowerCase().replace(/"/g, '\\"')}"
limit = ${parseInt(limit) || 10}

with get_session() as session:
    # Search by name prefix (case-insensitive)
    cards = session.query(Card).filter(
        Card.name.like(query + '%')
    ).order_by(
        Card.name
    ).limit(limit).all()

    results = []
    for card in cards:
        results.append({
            'id': card.id,
            'name': card.name,
            'sport': card.sport,
            'brand': card.brand,
            'team': card.team,
            'number': card.number,
            'copyright_year': card.copyright_year,
            'card_set': card.card_set,
            'condition': card.condition,
            'is_player': card.is_player,
            'features': card.features,
            'value_estimate': card.value_estimate,
            'notes': card.notes
        })

    print(json.dumps({'cards': results}))
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
          res.json(result);
        } catch (e) {
          res.json({ cards: [] });
        }
      } else {
        console.error('Search error:', error);
        res.json({ cards: [] });
      }
    });
  } catch (error) {
    console.error('Error searching cards:', error);
    res.json({ cards: [] });
  }
});

// Initialize and start server
async function startServer() {
  try {
    console.log('🔍 validating startup configuration...\n');
    await validateStartup();

    console.log('📁 ensuring required directories exist...');
    await ensureDirectories();

    app.listen(PORT, () => {
      console.log(`\n🚀 server running on http://localhost:${PORT}`);
      console.log(`📁 frontend available at http://localhost:3000`);
      console.log(`🏥 health check available at http://localhost:${PORT}/health`);
      console.log(`🔐 auth endpoints available at http://localhost:${PORT}/api/auth`);
    });
  } catch (err) {
    console.error('failed to start server:', err);
    process.exit(1);
  }
}

startServer();
