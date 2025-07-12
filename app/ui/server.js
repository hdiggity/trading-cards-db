const express = require('express');
const cors = require('cors');
const fs = require('fs').promises;
const path = require('path');
const { spawn } = require('child_process');
const multer = require('multer');

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware
app.use(cors());
app.use(express.json());

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
const VERIFIED_DIR = path.join(__dirname, '../../images/verified');

// Ensure directories exist
async function ensureDirectories() {
  try {
    await fs.mkdir(PENDING_VERIFICATION_DIR, { recursive: true });
    await fs.mkdir(VERIFIED_DIR, { recursive: true });
  } catch (error) {
    console.error('Error creating directories:', error);
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

    // Log the upload using the logging system (simplified to avoid string escaping issues)
    try {
      const fileCount = uploadedFiles.length;
      const totalSize = uploadedFiles.reduce((sum, file) => sum + file.size, 0);
      const pythonCode = `
import sys
sys.path.append('${path.join(__dirname, '..').replace(/\\/g, '/')}')
from logging_system import logger, LogSource, ActionType

logger.log_action(
    source=LogSource.UI,
    action=ActionType.FILE_UPLOAD,
    message="Uploaded ${fileCount} raw scan image(s) via drag & drop",
    details="Total size: ${Math.round(totalSize / 1024)} KB",
    file_path="${rawScansPath.replace(/\\/g, '/')}"
)
print("Logged upload action")
      `;
      const pythonProcess = spawn('python', ['-c', pythonCode], {
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
        if (code !== 0) {
          console.error('Failed to log upload action:', error);
        }
      });
    } catch (logError) {
      console.error('Error logging upload action:', logError);
    }

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
    
    // Convert text fields to lowercase for consistency
    const processedCardData = cardToImport.map(card => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
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
from app.learning import store_user_corrections

# Read data from stdin
input_data = json.loads(sys.stdin.read())
card_data = input_data['card_data']
original_data = input_data.get('original_data')
image_filename = input_data.get('image_filename')

# Store learning data if we have original data for comparison
if original_data and image_filename:
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
            else:
                # Create new card
                new_card = Card(**card_create.model_dump())
                session.add(new_card)
                print(f"Added new card: {card_info.get('name')}")
                
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
      card_data: processedCardData,
      original_data: allCardData.length === 1 ? [allCardData[parseInt(cardIndex)]] : null,
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
        // Remove the imported card from the array
        allCardData.splice(parseInt(cardIndex), 1);
        
        // Update the JSON file with remaining cards
        if (allCardData.length > 0) {
          await fs.writeFile(jsonPath, JSON.stringify(allCardData, null, 2));
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
            // Move JSON file to verified folder
            await fs.rename(jsonPath, path.join(VERIFIED_DIR, path.basename(jsonPath)));
            
            // Move image file to verified folder
            if (imageFile) {
              await fs.rename(
                path.join(PENDING_VERIFICATION_DIR, imageFile),
                path.join(VERIFIED_DIR, imageFile)
              );
            }
            
            res.json({ 
              success: true, 
              message: 'Last card verified and imported. All cards from this image processed and archived.',
              remainingCards: 0,
              output: output.trim()
            });
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
            else:
                # Create new card
                new_card = Card(**card_create.model_dump())
                session.add(new_card)
                print(f"Added new card: {card_info.get('name')}")
                
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
          // Move JSON file to verified folder
          await fs.rename(
            path.join(PENDING_VERIFICATION_DIR, jsonFile),
            path.join(VERIFIED_DIR, jsonFile)
          );
          
          // Move image file to verified folder
          await fs.rename(
            path.join(PENDING_VERIFICATION_DIR, imageFile),
            path.join(VERIFIED_DIR, imageFile)
          );
          
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
    
    // Convert text fields to lowercase for consistency
    const processedData = data.map(card => {
      const processedCard = { ...card };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
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
    
    // Re-run AI extraction with improved prompt and previous context
    const pythonProcess = spawn('python', ['-c', `
import sys
import json
import os
sys.path.append("${path.join(__dirname, '../..')}")
from app.utils import gpt_extract_cards_from_image, save_cards_to_verification
from pathlib import Path

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
            model="gpt-4o", messages=diagnostic_messages, max_tokens=500, temperature=0.1
        )
        diagnostic_result = diagnostic_response.choices[0].message.content.strip()
        print(f"AI DIAGNOSTIC - What it sees: {diagnostic_result}", file=sys.stderr)
    except Exception as e:
        print(f"Diagnostic failed: {e}", file=sys.stderr)
    
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
          
          const newCardData = JSON.parse(jsonOutput.trim());
          
          if (!Array.isArray(newCardData)) {
            throw new Error('Expected array of cards, got: ' + typeof newCardData);
          }
          
          console.log('Successfully parsed', newCardData.length, 'cards from re-processing');
          
          // Update the JSON file with new extraction
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
    const { page = 1, limit = 20, search = '', sport = '', brand = '', condition = '' } = req.query;
    
    const pythonProcess = spawn('python', ['-c', `
import json
import sys
from app.database import get_session
from app.models import Card
from sqlalchemy import func, or_, and_

page = ${parseInt(page)}
limit = ${parseInt(limit)}
search = "${search}"
sport = "${sport}"
brand = "${brand}"
condition = "${condition}"

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
                "quantity": card.quantity,
                "last_price": card.last_price,
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
app.post('/api/process-raw-scans', async (req, res) => {
  try {
    const pythonProcess = spawn('python', ['-m', 'app.run', '--raw'], {
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
        res.json({ 
          success: true, 
          message: 'Raw scan processing completed successfully',
          output: output.trim()
        });
      } else {
        res.status(500).json({ 
          error: 'Raw scan processing failed', 
          details: error.trim() 
        });
      }
    });
    
  } catch (error) {
    console.error('Error triggering raw scan processing:', error);
    res.status(500).json({ error: 'Failed to trigger raw scan processing' });
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
    
    result = {
        "total_cards": total_cards,
        "total_quantity": total_quantity,
        "unique_players": unique_players,
        "unique_years": unique_years,
        "unique_brands": unique_brands
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

// Enhanced system logs endpoint with database integration
app.get('/api/system-logs', async (req, res) => {
  try {
    const { limit = 100, level, source } = req.query;
    
    const pythonProcess = spawn('python', ['-c', `
from app.logging_system import logger
import json
import sys

try:
    # Get logs from enhanced logging system
    logs = logger.get_recent_logs(limit=${parseInt(limit)})
    
    # Add system status checks
    import os
    from pathlib import Path
    
    status_logs = []
    
    # Check OpenAI API key
    if not os.getenv("OPENAI_API_KEY"):
        status_logs.append({
            "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.%fZ)",
            "level": "error",
            "source": "configuration",
            "action": None,
            "message": "OPENAI_API_KEY environment variable not set",
            "details": "This will cause card processing to fail. Set OPENAI_API_KEY in your .env file.",
            "metadata": None,
            "image_filename": None
        })
    else:
        status_logs.append({
            "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.%fZ)",
            "level": "success",
            "source": "configuration", 
            "action": None,
            "message": "OPENAI_API_KEY is configured",
            "details": "API key is available for GPT-4 Vision processing",
            "metadata": None,
            "image_filename": None
        })
    
    # Check required directories
    required_dirs = [
        "images/raw_scans",
        "images/pending_verification", 
        "images/verified"
    ]
    
    for dir_path in required_dirs:
        if Path(dir_path).exists():
            status_logs.append({
                "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.%fZ)",
                "level": "success",
                "source": "filesystem",
                "action": None,
                "message": f"Directory exists: {Path(dir_path).name}",
                "details": f"Path: {dir_path}",
                "metadata": None,
                "image_filename": None
            })
        else:
            status_logs.append({
                "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.%fZ)",
                "level": "warning",
                "source": "filesystem",
                "action": None,
                "message": f"Directory missing: {Path(dir_path).name}",
                "details": f"Expected path: {dir_path}. This directory will be created automatically when needed.",
                "metadata": None,
                "image_filename": None
            })
    
    # Combine logs and sort
    all_logs = logs + status_logs
    all_logs.sort(key=lambda x: x["timestamp"], reverse=True)
    
    result = {
        "logs": all_logs[:${parseInt(limit)}],
        "totalLogs": len(all_logs),
        "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.%fZ)"
    }
    
    print(json.dumps(result))
    
except Exception as e:
    print(f"Error getting enhanced logs: {e}", file=sys.stderr)
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
          // Fallback to basic logs if enhanced system fails
          res.json({
            logs: [{
              timestamp: new Date().toISOString(),
              level: 'warning',
              source: 'system',
              message: 'Enhanced logging system unavailable, using fallback',
              details: `Parse error: ${parseError.message}`,
              metadata: null
            }],
            totalLogs: 1,
            timestamp: new Date().toISOString()
          });
        }
      } else {
        // Fallback to basic system check
        res.json({
          logs: [{
            timestamp: new Date().toISOString(),
            level: 'error',
            source: 'system',
            message: 'Enhanced logging system failed to initialize',
            details: error.trim() || 'Unknown error',
            metadata: null
          }],
          totalLogs: 1,
          timestamp: new Date().toISOString()
        });
      }
    });
    
  } catch (error) {
    console.error('Error fetching enhanced system logs:', error);
    res.status(500).json({ 
      error: 'Failed to fetch system logs',
      details: error.message,
      logs: [{
        timestamp: new Date().toISOString(),
        level: 'error',
        source: 'api',
        message: 'Failed to fetch system logs',
        details: `Error: ${error.message}`,
        metadata: null
      }],
      totalLogs: 1,
      timestamp: new Date().toISOString()
    });
  }
});

// Upload history endpoint
app.get('/api/upload-history', async (req, res) => {
  try {
    const { limit = 50 } = req.query;
    
    const pythonProcess = spawn('python', ['-c', `
from app.logging_system import logger
import json

try:
    history = logger.get_upload_history(limit=${parseInt(limit)})
    print(json.dumps({
        "history": history,
        "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.%fZ)"
    }))
except Exception as e:
    print(f"Error getting upload history: {e}", file=sys.stderr)
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
          res.status(500).json({ 
            error: 'Failed to parse upload history',
            details: parseError.message
          });
        }
      } else {
        res.status(500).json({ 
          error: 'Failed to get upload history', 
          details: error.trim() 
        });
      }
    });
    
  } catch (error) {
    console.error('Error fetching upload history:', error);
    res.status(500).json({ 
      error: 'Failed to fetch upload history',
      details: error.message
    });
  }
});

// Initialize and start server
ensureDirectories().then(() => {
  app.listen(PORT, () => {
    console.log(`🚀 API Server running on http://localhost:${PORT}`);
    console.log(`📁 Frontend available at http://localhost:3000`);
  });
});