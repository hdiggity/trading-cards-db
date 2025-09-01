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

// Configure multer for file uploads
const storage = multer.diskStorage({
  destination: function (req, file, cb) {
    const rawScansPath = path.join(__dirname, '../../images/raw_scans');
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
app.get('/images/*', async (req, res) => {
  try {
    const imagePath = path.join(__dirname, '../../images', req.params[0]);
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
const PENDING_VERIFICATION_DIR = path.join(__dirname, '../../images/pending_verification');
// New folder for verified images (no spaces for path safety)
// Standardized verified directories
const VERIFIED_ROOT_DIR = path.join(__dirname, '../../images/verified');
const VERIFIED_IMAGES_DIR = path.join(VERIFIED_ROOT_DIR, 'images'); // verified image files live here
const VERIFIED_LEGACY_DIR = path.join(VERIFIED_ROOT_DIR, 'legacy');
const AUDIT_LOG = path.join(__dirname, '../../logs/audit.log');

// Ensure directories exist
async function ensureDirectories() {
  try {
    await fs.mkdir(PENDING_VERIFICATION_DIR, { recursive: true });
    await fs.mkdir(VERIFIED_ROOT_DIR, { recursive: true });
    await fs.mkdir(VERIFIED_IMAGES_DIR, { recursive: true });
    await fs.mkdir(VERIFIED_LEGACY_DIR, { recursive: true });
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
    
    const cards = [];
    
    for (const jsonFile of jsonFiles) {
      const baseName = path.parse(jsonFile).name;
      
      // Look for corresponding image file in the same directory
      const imageFile = pendingFiles.find(file => {
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
  const rawScansPath = path.join(__dirname, '../../images/raw_scans');
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
    
    // Find the files in pending verification directory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    
    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    // Find corresponding image file early so we can pass it to learning process
    const imageFileEarly = pendingFiles.find(file => {
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
    
    // Use modified data for the specific card if provided
    if (modifiedData) {
      allCardData[parseInt(cardIndex)] = modifiedData;
    }
    
    // Import only the specific card to database
    const cardToImport = [allCardData[parseInt(cardIndex)]];
    
    // Convert selected text fields to lowercase for consistency (include 'name')
    const processedCardData = cardToImport.map(card => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      return processedCard;
    });
    
    // Import card directly to database and store learning data
    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card
from app.schemas import CardCreate
from app.per_card_export import write_per_card_file
from app.learning import store_user_corrections
from app.per_card_export import write_per_card_file
from app.db_backup import backup_database
import os

# Read data from stdin
input_data = json.loads(sys.stdin.read())
card_data = input_data['card_data']
original_data = input_data.get('original_data')
image_filename = input_data.get('image_filename')

# Before writing, create a timestamped DB backup for safety
try:
    backup_path = backup_database(os.getenv('DB_PATH', 'trading_cards.db'), os.getenv('DB_BACKUP_DIR', 'backups'))
    print(f"DB backup created: {backup_path}", file=sys.stderr)
except Exception as e:
    print(f"Warning: DB backup failed: {e}", file=sys.stderr)

# Store learning data if we have original data for comparison
if original_data and image_filename:
    try:
        store_user_corrections(image_filename, original_data, card_data)
        print(f"Stored learning data for {image_filename}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not store learning data: {e}", file=sys.stderr)

# Convert selected text fields to lowercase for consistency (include 'name')
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
                print(f"Updated quantity for existing card: {card_info.get('name')}")
                try:
                    write_per_card_file(existing)
                except Exception as _:
                    pass
            else:
                # Create new card
                new_card = Card(**card_create.model_dump())
                session.add(new_card)
                print(f"Added new card: {card_info.get('name')}")
                try:
                    write_per_card_file(new_card)
                except Exception as _:
                    pass
            
        except Exception as e:
            print(f"Error processing card {card_info.get('name', 'n/a')}: {e}")
            continue

print("Database import completed successfully")
    `], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });
    try { REPROCESS_JOBS.set(id, pythonProcess); } catch (_) {}
    
    // Prepare data with learning context
    const learningData = {
      card_data: processedCardData,
      original_data: allCardData.length === 1 ? [allCardData[parseInt(cardIndex)]] : null,
      image_filename: imageFileEarly || null
    };
    
    // Send card data and learning context to Python process
    pythonProcess.stdin.write(JSON.stringify(learningData));
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
      if (code === 0) {
        // Remove the imported card from the array
        allCardData.splice(parseInt(cardIndex), 1);
        
        // Update the JSON file with remaining cards
        if (allCardData.length > 0) {
          await fs.writeFile(jsonPath, JSON.stringify(allCardData, null, 2));
          // Log verification action (single card)
          try {
            const py = `from app.logging_system import logger\nlogger.log_verification_action(filename='${(imageFileEarly||'').replace(/'/g,"\'")}', action='pass', card_index=${parseInt(cardIndex)})`;
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
          const imageFile = pendingFiles.find(file => {
            const imgBaseName = path.parse(file).name;
            const imgExt = path.parse(file).ext.toLowerCase();
            return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
          });
          
          try {
            // Move grouped JSON file to legacy folder (we keep per-card files as canonical)
            await fs.rename(jsonPath, path.join(VERIFIED_LEGACY_DIR, path.basename(jsonPath)));
            // Move any per-card JSON split files for this image
            const baseNameRoot = path.parse(jsonPath).name;
            const root = baseNameRoot.split('__c')[0];
            const dirFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
            const perCard = dirFiles.filter(f => f.startsWith(root + '__c') && f.endsWith('.json'));
            for (const pc of perCard) {
              await fs.rename(
                path.join(PENDING_VERIFICATION_DIR, pc),
                path.join(VERIFIED_IMAGES_DIR, pc)
              );
            }
            
            // Move image file to verified/images folder
            if (imageFile) {
              await fs.rename(
                path.join(PENDING_VERIFICATION_DIR, imageFile),
                path.join(VERIFIED_IMAGES_DIR, imageFile)
              );
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
    
    // Find the files in pending verification directory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    
    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    const imageFile = pendingFiles.find(file => {
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
    
    // Convert text fields to lowercase for consistency
    cardData = cardData.map(card => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      return processedCard;
    });
    
    // Import cards directly to database and store learning data
    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card
from app.schemas import CardCreate
from app.learning import store_user_corrections

# Read data from stdin
input_data = json.loads(sys.stdin.read())
card_data = input_data['card_data']
original_data = input_data.get('original_data')
image_filename = input_data.get('image_filename')

# Store learning data if we have original data for comparison
if original_data and image_filename and original_data != card_data:
    try:
        store_user_corrections(image_filename, original_data, card_data)
        print(f"Stored learning data for {image_filename}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not store learning data: {e}", file=sys.stderr)

# Convert text fields to lowercase for consistency
text_fields = ['name', 'sport', 'brand', 'team', 'card_set']
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
                print(f"Updated quantity for existing card: {card_info.get('name')}")
                try:
                    write_per_card_file(existing)
                except Exception as _:
                    pass
            else:
                # Create new card
                new_card = Card(**card_create.model_dump())
                session.add(new_card)
                print(f"Added new card: {card_info.get('name')}")
                try:
                    write_per_card_file(new_card)
                except Exception as _:
                    pass
                
        except Exception as e:
            print(f"Error processing card {card_info.get('name', 'n/a')}: {e}")
            continue

print("Database import completed successfully")
    `], {
      cwd: path.join(__dirname, '../..'),
      stdio: ['pipe', 'pipe', 'pipe']
    });
    
    // Prepare data with learning context
    const learningData = {
      card_data: cardData,
      original_data: modifiedData ? originalData : null, // Only store learning if user made edits
      image_filename: imageFile
    };
    
    // Send card data and learning context to Python process
    pythonProcess.stdin.write(JSON.stringify(learningData));
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
        // Database import successful, now move files to verified folder
        try {
          // Move grouped JSON file to legacy folder
          await fs.rename(
            path.join(PENDING_VERIFICATION_DIR, jsonFile),
            path.join(VERIFIED_LEGACY_DIR, jsonFile)
          );
          
          // Move image file to verified/images folder
          await fs.rename(
            path.join(PENDING_VERIFICATION_DIR, imageFile),
            path.join(VERIFIED_IMAGES_DIR, imageFile)
          );

          // Log verification action (pass all)
          try {
            const py = `from app.logging_system import logger\nlogger.log_verification_action(filename='${(imageFile||'').replace(/'/g,"\'")}', action='pass')`;
            const p = spawn('python', ['-c', py], { cwd: path.join(__dirname, '../..') });
            p.on('error', ()=>{});
          } catch(_) {}

          // Also move any per-card JSONs if they exist; otherwise, create standardized per-card files
          try {
            const baseNameRoot = path.parse(jsonFile).name;
            const root = baseNameRoot.split('__c')[0];
            const dirFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
            const perCard = dirFiles.filter(f => f.startsWith(root + '__c') && f.endsWith('.json'));
            if (perCard.length > 0) {
              for (const pc of perCard) {
                // Standardize naming by re-writing via Python exporter
                try {
                  const pcPath = path.join(PENDING_VERIFICATION_DIR, pc);
                  const python = `
import json
from app.per_card_export import write_per_card_file

data = json.load(open(r'''${pcPath.replace(/\\/g,'/')}''','r'))
card = data[0] if isinstance(data, list) and data else data
try:
    # Build a lightweight object to mimic Card attributes for exporter
    class Obj: pass
    o = Obj()
    for k in ['name','sport','brand','number','copyright_year','team','card_set','condition','features','quantity','last_price','value_estimate']:
        setattr(o, k, card.get(k))
    p = write_per_card_file(o)
    print(str(p))
except Exception as e:
    print('err:' + str(e))
                  `;
                  await new Promise((resolve) => {
                    const proc = spawn('python', ['-c', python], { cwd: path.join(__dirname, '../..') });
                    proc.on('close', () => resolve());
                  });
                } catch (_) {}
                // Remove the old pending per-card file
                try { await fs.unlink(path.join(PENDING_VERIFICATION_DIR, pc)); } catch {}
              }
            } else {
              // Create standardized per-card files directly from grouped JSON via Python
              const groupedPath = path.join(VERIFIED_LEGACY_DIR, jsonFile);
              const python = `
import json
from app.per_card_export import write_per_card_file

arr = json.load(open(r'''${groupedPath.replace(/\\/g,'/')}''','r'))
if isinstance(arr, list):
    for card in arr:
        class Obj: pass
        o = Obj()
        for k in ['name','sport','brand','number','copyright_year','team','card_set','condition','features','quantity','last_price','value_estimate']:
            setattr(o, k, card.get(k))
        write_per_card_file(o)
              `;
              await new Promise((resolve) => {
                const proc = spawn('python', ['-c', python], { cwd: path.join(__dirname, '../..') });
                proc.on('close', () => resolve());
              });
            }
          } catch (e) {
            console.error('Per-card JSON move/split error:', e);
          }
          
          res.json({ 
            success: true, 
            message: 'Cards verified, imported to database, and archived successfully',
            output: output.trim()
          });
        } catch (moveError) {
          console.error('Error moving files to verified folder:', moveError);
          res.json({ 
            success: true, 
            message: 'Cards imported to database but file archiving failed',
            output: output.trim()
          });
        }
      } else {
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
    const { data } = req.body;
    
    // Find the JSON file in pending verification directory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    
    if (!jsonFile) {
      return res.status(404).json({ error: 'Card data file not found' });
    }
    
    // Convert selected text fields to lowercase for consistency (include 'name')
    const processedData = data.map(card => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set', 'features', 'condition'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      return processedCard;
    });
    
    // Save updated data to JSON file
    const jsonPath = path.join(PENDING_VERIFICATION_DIR, jsonFile);
    await fs.writeFile(jsonPath, JSON.stringify(processedData, null, 2));
    
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
app.post('/api/reprocess/:id', async (req, res) => {
  try {
    const { id } = req.params;
    
    // Find the files in pending verification directory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    
    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    const imageFile = pendingFiles.find(file => {
      const imgBaseName = path.parse(file).name;
      const imgExt = path.parse(file).ext.toLowerCase();
      return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
    });
    
    if (!jsonFile || !imageFile) {
      return res.status(404).json({ error: 'Files not found' });
    }
    
    const imagePath = path.join(PENDING_VERIFICATION_DIR, imageFile);
    
    // Get previous data for context
    const jsonPath = path.join(PENDING_VERIFICATION_DIR, jsonFile);
    const previousData = JSON.parse(await fs.readFile(jsonPath, 'utf8'));
    
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
    previous_data = json.loads(sys.stdin.read())
    
    print(f"Re-processing image with previous context: {image_path}", file=sys.stderr)
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
    
    // Find the JSON file in pending verification directory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    
    if (!jsonFile) {
      return res.status(404).json({ error: 'Card data file not found' });
    }
    
    // Get the current card data
    const jsonPath = path.join(PENDING_VERIFICATION_DIR, jsonFile);
    let allCardData = JSON.parse(await fs.readFile(jsonPath, 'utf8'));
    
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
      // No cards left, clean up files
      const imageFile = pendingFiles.find(file => {
        const imgBaseName = path.parse(file).name;
        const imgExt = path.parse(file).ext.toLowerCase();
        return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
      });
      
      try {
        await fs.unlink(jsonPath);
        if (imageFile) {
          await fs.unlink(path.join(PENDING_VERIFICATION_DIR, imageFile));
        }
        
        res.json({ 
          success: true, 
          message: 'Last card rejected. All cards from this image processed.',
          remainingCards: 0
        });
      } catch (cleanupError) {
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
    
    // Find the files in pending verification directory
    const pendingFiles = await fs.readdir(PENDING_VERIFICATION_DIR);
    
    const jsonFile = pendingFiles.find(file => path.parse(file).name === id && file.endsWith('.json'));
    const imageFile = pendingFiles.find(file => {
      const imgBaseName = path.parse(file).name;
      const imgExt = path.parse(file).ext.toLowerCase();
      return imgBaseName === id && ['.jpg', '.jpeg', '.png', '.heic'].includes(imgExt);
    });
    
    if (!jsonFile || !imageFile) {
      return res.status(404).json({ error: 'Files not found' });
    }
    
    // Delete both files (failed verification)
    await fs.unlink(path.join(PENDING_VERIFICATION_DIR, jsonFile));
    await fs.unlink(path.join(PENDING_VERIFICATION_DIR, imageFile));
    
    res.json({ success: true, message: 'Card rejected and files deleted' });
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

// Update a card in the database
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

// Delete a card from the database
app.delete('/api/cards/:id', async (req, res) => {
  try {
    const { id } = req.params;
    
    const pythonProcess = spawn('python', ['-c', `
from app.database import get_session
from app.models import Card

card_id = ${parseInt(id)}

with get_session() as session:
    card = session.query(Card).filter(Card.id == card_id).first()
    if not card:
        print("Card not found", file=sys.stderr)
        sys.exit(1)
    
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
    // Ensure logs directory exists and create a per-run log file
    const logsDir = path.join(__dirname, '../../logs');
    try { await fs.mkdir(logsDir, { recursive: true }); } catch {}
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const logFile = path.join(logsDir, `process_raw_scans_${stamp}.log`);
    const logStream = fsSync.createWriteStream(logFile, { flags: 'a' });

    const child = spawn('python', ['-m', 'app.run', '--raw'], {
      cwd: path.join(__dirname, '../..'),
      detached: true,
      stdio: ['ignore', 'pipe', 'pipe']
    });

    // Pipe output to the log file so we don't block or lose diagnostics
    child.stdout.pipe(logStream);
    child.stderr.pipe(logStream);
    // Compute initial total raw scans to drive progress and persist status so the client can discover processing after reloads
    const RAW_SCANS_DIR = path.join(__dirname, '../../images/raw_scans');
    let initialCount = 0;
    try {
      const files = await fs.readdir(RAW_SCANS_DIR);
      initialCount = files.filter((f) => ['.jpg', '.jpeg', '.png', '.heic'].includes(path.extname(f).toLowerCase())).length;
    } catch {}

    const status = { active: true, pid: child.pid, logFile: logFile.replace(/\\/g, '/'), startedAt: new Date().toISOString(), total: initialCount, remaining: initialCount, progress: initialCount === 0 ? 100 : 10 };
    writeStatus(status);

    // Periodically update remaining count and computed progress while process is active
    const progressTimer = setInterval(async () => {
      try {
        const files = await fs.readdir(RAW_SCANS_DIR).catch(() => []);
        const remaining = files.filter((f) => ['.jpg', '.jpeg', '.png', '.heic'].includes(path.extname(f).toLowerCase())).length;
        const total = status.total || initialCount || 1;
        const done = Math.max(0, total - remaining);
        const pct = Math.min(99, Math.max(10, Math.round((done / Math.max(total, 1)) * 100)));
        writeStatus({ ...status, active: true, remaining, progress: pct });
      } catch {}
    }, 4000);

    child.on('close', (code, signal) => {
      clearInterval(progressTimer);
      // Finalize progress to 100%
      const finished = { ...status, active: false, remaining: 0, progress: 100, finishedAt: new Date().toISOString(), exitCode: code ?? null, signal: signal ?? null };
      writeStatus(finished);
    });

    child.unref();

    res.status(202).json({
      success: true,
      message: 'Raw scan processing started in the background',
      pid: child.pid,
      logFile: logFile.replace(/\\/g, '/')
    });
  } catch (error) {
    console.error('Error triggering raw scan processing:', error);
    res.status(500).json({ error: 'Failed to trigger raw scan processing', details: String(error) });
  }
});

// Get count of raw scan images waiting to be processed
app.get('/api/raw-scan-count', async (req, res) => {
  try {
    const RAW_SCANS_DIR = path.join(__dirname, '../../images/raw_scans');
    
    try {
      const files = await fs.readdir(RAW_SCANS_DIR);
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
    console.error('Error getting raw scan count:', error);
    res.status(500).json({ error: 'Failed to get raw scan count' });
  }
});

// List raw scans with basic metadata (for preview before processing)
app.get('/api/raw-scans', async (req, res) => {
  try {
    const RAW_SCANS_DIR = path.join(__dirname, '../../images/raw_scans');
    let files;
    try {
      files = await fs.readdir(RAW_SCANS_DIR);
    } catch {
      return res.json({ files: [], count: 0 });
    }

    const imageFiles = files.filter((file) => ['.jpg', '.jpeg', '.png', '.heic', '.heif'].includes(path.extname(file).toLowerCase()));
    const enriched = await Promise.all(
      imageFiles.map(async (name) => {
        const p = path.join(RAW_SCANS_DIR, name);
        try {
          const st = await fs.stat(p);
          return {
            name,
            size: st.size,
            mtime: st.mtime,
            url: `/images/raw_scans/${name}`
          };
        } catch {
          return { name, size: null, mtime: null, url: `/images/raw_scans/${name}` };
        }
      })
    );
    // Sort newest first
    enriched.sort((a, b) => new Date(b.mtime) - new Date(a.mtime));
    res.json({ files: enriched, count: enriched.length });
  } catch (error) {
    console.error('Error listing raw scans:', error);
    res.status(500).json({ error: 'Failed to list raw scans' });
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

// Get learning insights
app.get('/api/learning-insights', async (req, res) => {
  try {
    const pythonProcess = spawn('python', ['-c', `
from app.learning import get_learning_insights
import json

try:
    insights = get_learning_insights()
    print(json.dumps(insights))
except Exception as e:
    print(f"Error getting insights: {e}", file=sys.stderr)
    sys.exit(1)
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
          res.status(500).json({ error: 'Failed to parse learning insights' });
        }
      } else {
        res.status(500).json({ 
          error: 'Failed to get learning insights', 
          details: error.trim() 
        });
      }
    });
    
  } catch (error) {
    console.error('Error getting learning insights:', error);
    res.status(500).json({ error: 'Failed to get learning insights' });
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

// System logs: simplified, database-only
app.get('/api/system-logs', async (req, res) => {
  try {
    const { limit = 200 } = req.query;
    const python = `
from app.logging_system import logger, init_logging_tables, UploadHistory
from app.database import get_session
from app.models import Card
import json
from datetime import datetime, timezone

try:
    # Ensure tables exist
    init_logging_tables()
except Exception:
    pass

def norm(ts: str) -> str:
    try:
        # Support timestamps with/without timezone and microseconds
        if ts.endswith('Z'):
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        else:
            dt = datetime.fromisoformat(ts)
        dt = dt.replace(tzinfo=timezone.utc)
        # RFC3339 with milliseconds (3 digits) to satisfy Safari/JS Date
        return dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    except Exception:
        # Fallback to current time if unparseable
        return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

logs = logger.get_recent_logs(limit=${parseInt(limit)})
for log in logs:
    if 'timestamp' in log and isinstance(log['timestamp'], str):
        log['timestamp'] = norm(log['timestamp'])

# Compute totals
uploads_total = 0
uploads_verified = 0
uploads_failed = 0
uploads_pending = 0
cards_total = 0
try:
    with get_session() as session:
        uploads_total = session.query(UploadHistory).count()
        uploads_verified = session.query(UploadHistory).filter(UploadHistory.status=='verified').count()
        uploads_failed = session.query(UploadHistory).filter(UploadHistory.status=='failed').count()
        uploads_pending = session.query(UploadHistory).filter(UploadHistory.status=='pending_verification').count()
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
