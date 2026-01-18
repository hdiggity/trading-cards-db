import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import './App.css';
import ConfirmDialog from './components/ConfirmDialog';

// Utility function to format field names for display
const formatFieldName = (fieldName) => {
  const fieldMap = {
    'name': 'Name',
    'sport': 'Sport',
    'brand': 'Brand',
    'number': 'Number',
    'copyright_year': 'Year',
    'team': 'Team',
    'card_set': 'Set',
    'condition': 'Condition',
    'is_player': 'Player Card',
    'features': 'Features',
    'value_estimate': 'Price Estimate',
    'notes': 'Notes'
  };
  return fieldMap[fieldName] || fieldName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
};

// Utility helpers for display normalization
const normalizeCondition = (val) => {
  if (!val) return '';
  return String(val).replace(/_/g, ' ').trim().toLowerCase();
};

// Utility function to format field values for display
const formatFieldValue = (fieldName, value) => {
  if (value === null || value === undefined) return 'N/A';

  const raw = typeof value === 'string' ? value : String(value);
  const noUnderscore = raw.replace(/_/g, ' ').trim();

  switch (fieldName) {
    case 'is_player':
      return value ? 'yes' : 'no';
    case 'name':
      return noUnderscore.toLowerCase();
    case 'features': {
      if (!noUnderscore || noUnderscore.toLowerCase() === 'none') return 'none';
      return noUnderscore
        .split(',')
        .map((f) => f.trim().replace(/_/g, ' ').toLowerCase())
        .filter(Boolean)
        .join(', ');
    }
    case 'sport':
      return noUnderscore.toLowerCase();
    case 'brand':
    case 'team':
      return noUnderscore.toLowerCase();
    case 'card_set':
      return noUnderscore.toLowerCase();
    case 'condition':
      return noUnderscore.toLowerCase();
    default:
      return noUnderscore || 'N/A';
  }
};

// Confidence indicator component
function ConfidenceIndicator({ confidence, fieldName }) {
  if (confidence === undefined || confidence === null) return null;
  
  const getConfidenceColor = (score) => {
    if (score >= 0.8) return '#059669'; // Green
    if (score >= 0.6) return '#d97706'; // Orange
    return '#dc2626'; // Red
  };
  
  const getConfidenceLabel = (score) => {
    if (score >= 0.8) return 'High';
    if (score >= 0.6) return 'Medium';
    return 'Low';
  };
  
  return (
    <div className="confidence-indicator" title={`AI Confidence: ${(confidence * 100).toFixed(0)}%`}>
      <div 
        className="confidence-bar"
        style={{
          width: '60px',
          height: '4px',
          backgroundColor: '#e5e7eb',
          borderRadius: '2px',
          overflow: 'hidden',
          display: 'inline-block',
          marginLeft: '8px'
        }}
      >
        <div 
          style={{
            width: `${confidence * 100}%`,
            height: '100%',
            backgroundColor: getConfidenceColor(confidence),
            transition: 'width 0.3s ease'
          }}
        />
      </div>
      <span 
        className="confidence-label"
        style={{
          fontSize: '0.75rem',
          color: getConfidenceColor(confidence),
          marginLeft: '6px',
          fontWeight: '500'
        }}
      >
        {getConfidenceLabel(confidence)}
      </span>
    </div>
  );
}

// TCDB verification removed

// Zoomable image component - simplified for intuitive use
function ZoomableImage({ src, alt, className, onError }) {
  const [isZoomed, setIsZoomed] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [mouseDownPos, setMouseDownPos] = useState({ x: 0, y: 0 });
  const [hasDraggedEnough, setHasDraggedEnough] = useState(false);
  const imgRef = useRef(null);
  const pinchRef = useRef(null);
  const DRAG_THRESHOLD = 5; // pixels to move before considering it a drag

  // Clamp panning so image stays in view
  const clampPosition = (pos, z, rect) => {
    if (!rect) return pos;
    const maxX = Math.max(0, (rect.width * (z - 1)) / 2);
    const maxY = Math.max(0, (rect.height * (z - 1)) / 2);
    return {
      x: Math.min(maxX, Math.max(-maxX, pos.x)),
      y: Math.min(maxY, Math.max(-maxY, pos.y)),
    };
  };

  // Single click = toggle between 1x and 2x zoom
  const handleImageClick = (e) => {
    if (hasDraggedEnough) return; // Don't toggle if we dragged
    if (isZoomed) {
      // Zoom out
      setIsZoomed(false);
      setZoomLevel(1);
      setPosition({ x: 0, y: 0 });
    } else {
      // Zoom in to 2x centered on click point
      const rect = imgRef.current?.getBoundingClientRect();
      if (rect) {
        const cx = e.clientX - rect.left - rect.width / 2;
        const cy = e.clientY - rect.top - rect.height / 2;
        setPosition({ x: -cx * 0.5, y: -cy * 0.5 });
      }
      setIsZoomed(true);
      setZoomLevel(2);
    }
  };

  const handleZoomOut = () => {
    setIsZoomed(false);
    setZoomLevel(1);
    setPosition({ x: 0, y: 0 });
  };

  const stepZoom = (delta) => {
    const rect = imgRef.current?.getBoundingClientRect();
    const next = Math.max(1, Math.min(5, zoomLevel + delta));
    if (next > 1 && !isZoomed) setIsZoomed(true);
    if (rect) setPosition((p) => clampPosition(p, next, rect));
    setZoomLevel(next);
    if (next === 1) { setIsZoomed(false); setPosition({ x: 0, y: 0 }); }
  };

  const fitToView = () => handleZoomOut();

  // Scroll wheel = zoom in/out (works always, not just when zoomed)
  const handleWheel = (e) => {
    e.preventDefault();
    const dy = e.deltaY;

    // Adaptive sensitivity based on input device
    // Mousepad typically has smaller deltaY values and benefits from higher sensitivity
    // Mouse wheel has larger deltaY values
    let sensitivity;
    if (Math.abs(dy) < 5) {
      // Very small delta = mousepad/trackpad with fine control
      sensitivity = e.ctrlKey ? 0.015 : 0.01;
    } else if (Math.abs(dy) < 50) {
      // Small to medium delta = mousepad/trackpad
      sensitivity = e.ctrlKey ? 0.008 : 0.005;
    } else {
      // Large delta = mouse wheel
      sensitivity = e.ctrlKey ? 0.003 : 0.002;
    }

    const rect = imgRef.current?.getBoundingClientRect();
    let nextZoom = Math.max(1, Math.min(5, zoomLevel - dy * sensitivity));

    // Anchor zoom around cursor for smooth zoom-to-point
    if (rect && nextZoom !== zoomLevel) {
      const cx = e.clientX - rect.left - rect.width / 2;
      const cy = e.clientY - rect.top - rect.height / 2;
      const factor = (nextZoom - zoomLevel) / nextZoom;
      setPosition((p) => clampPosition({ x: p.x - cx * factor, y: p.y - cy * factor }, nextZoom, rect));
    }

    if (nextZoom > 1 && !isZoomed) setIsZoomed(true);
    setZoomLevel(nextZoom);
    if (nextZoom === 1) { setIsZoomed(false); setPosition({ x: 0, y: 0 }); }
  };
  
  const handleMouseDown = (e) => {
    if (isZoomed && zoomLevel > 1) {
      e.preventDefault();
      setMouseDownPos({ x: e.clientX, y: e.clientY });
      setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
      setIsDragging(true);
      setHasDraggedEnough(false);
    }
  };

  const handleMouseMove = (e) => {
    if (isDragging && isZoomed && zoomLevel > 1) {
      e.preventDefault();

      // Calculate distance moved since mouse down
      const dx = Math.abs(e.clientX - mouseDownPos.x);
      const dy = Math.abs(e.clientY - mouseDownPos.y);
      const distanceMoved = Math.sqrt(dx * dx + dy * dy);

      // Mark as dragged if moved beyond threshold
      if (distanceMoved > DRAG_THRESHOLD) {
        setHasDraggedEnough(true);
      }

      const rect = imgRef.current?.getBoundingClientRect();
      if (rect) {
        const newPos = { x: e.clientX - dragStart.x, y: e.clientY - dragStart.y };
        setPosition(clampPosition(newPos, zoomLevel, rect));
      }
    }
  };

  const handleMouseUp = () => {
    setIsDragging(false);
    setMouseDownPos({ x: 0, y: 0 });
    // hasDraggedEnough persists for click handler to check
  };
  
  // Touch helpers
  const distance = (t1, t2) => {
    const dx = t1.clientX - t2.clientX;
    const dy = t1.clientY - t2.clientY;
    return Math.hypot(dx, dy);
  };

  const handleTouchStart = (e) => {
    if (e.touches.length === 2) {
      const d = distance(e.touches[0], e.touches[1]);
      const rect = imgRef.current ? imgRef.current.getBoundingClientRect() : null;
      const centerX = rect ? ((e.touches[0].clientX + e.touches[1].clientX) / 2 - rect.left - rect.width / 2) : 0;
      const centerY = rect ? ((e.touches[0].clientY + e.touches[1].clientY) / 2 - rect.top - rect.height / 2) : 0;
      pinchRef.current = { initialDist: d, initialZoom: zoomLevel, centerX, centerY };
      if (!isZoomed) setIsZoomed(true);
      e.preventDefault();
    } else if (e.touches.length === 1 && isZoomed && zoomLevel > 1) {
      setMouseDownPos({ x: e.touches[0].clientX, y: e.touches[0].clientY });
      setDragStart({ x: e.touches[0].clientX - position.x, y: e.touches[0].clientY - position.y });
      setIsDragging(true);
      setHasDraggedEnough(false);
    }
  };

  const handleTouchMove = (e) => {
    if (pinchRef.current && e.touches.length === 2) {
      e.preventDefault();
      const d = distance(e.touches[0], e.touches[1]);
      const { initialDist, initialZoom, centerX, centerY } = pinchRef.current;
      let nextZoom = Math.max(1, Math.min(5, initialZoom * (d / Math.max(1, initialDist))));
      if (imgRef.current && nextZoom !== zoomLevel) {
        const factor = (nextZoom - zoomLevel) / nextZoom;
        const rect = imgRef.current.getBoundingClientRect();
        setPosition((p) => clampPosition({ x: p.x - centerX * factor, y: p.y - centerY * factor }, nextZoom, rect));
      }
      setZoomLevel(nextZoom);
      if (nextZoom === 1) {
        setIsZoomed(false);
        setPosition({ x: 0, y: 0 });
      }
    } else if (isDragging && e.touches.length === 1 && isZoomed && zoomLevel > 1) {
      e.preventDefault();
      const rect = imgRef.current?.getBoundingClientRect();
      if (rect) {
        const newPos = { x: e.touches[0].clientX - dragStart.x, y: e.touches[0].clientY - dragStart.y };
        setPosition(clampPosition(newPos, zoomLevel, rect));
      }
    }
  };

  const handleTouchEnd = () => {
    if (pinchRef.current) pinchRef.current = null;
    setIsDragging(false);
  };

  // Double-click to toggle zoom at cursor
  const handleDoubleClick = (e) => {
    const rect = imgRef.current ? imgRef.current.getBoundingClientRect() : null;
    if (!rect) return;
    if (!isZoomed || zoomLevel === 1) {
      const next = 2;
      const cx = e.clientX - rect.left - rect.width / 2;
      const cy = e.clientY - rect.top - rect.height / 2;
      const factor = (next - 1) / next;
      setIsZoomed(true);
      setZoomLevel(next);
      setPosition((p) => clampPosition({ x: p.x - cx * factor, y: p.y - cy * factor }, next, rect));
    } else {
      // If already zoomed, step up to max or reset if near max
      if (zoomLevel < 4.8) {
        const next = Math.min(5, zoomLevel + 0.6);
        const cx = e.clientX - rect.left - rect.width / 2;
        const cy = e.clientY - rect.top - rect.height / 2;
        const factor = (next - zoomLevel) / next;
        setZoomLevel(next);
        setPosition((p) => clampPosition({ x: p.x - cx * factor, y: p.y - cy * factor }, next, rect));
      } else {
        setIsZoomed(false);
        setZoomLevel(1);
        setPosition({ x: 0, y: 0 });
      }
    }
  };

  // Keyboard shortcuts for zooming
  useEffect(() => {
    const onKey = (e) => {
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.isComposing)) return;
      if (e.key === '+' || e.key === '=' ) {
        e.preventDefault();
        const rect = imgRef.current ? imgRef.current.getBoundingClientRect() : null;
        const next = Math.min(5, (isZoomed ? zoomLevel : 1) + 0.2);
        setIsZoomed(true);
        if (rect) {
          const cx = rect.width * 0.0; // center
          const cy = rect.height * 0.0;
          const factor = (next - zoomLevel) / Math.max(next, 1);
          setPosition((p) => clampPosition({ x: p.x - cx * factor, y: p.y - cy * factor }, next, rect));
        }
        setZoomLevel(next);
      } else if (e.key === '-' || e.key === '_') {
        e.preventDefault();
        const next = Math.max(1, zoomLevel - 0.2);
        setZoomLevel(next);
        if (next === 1) { setIsZoomed(false); setPosition({ x: 0, y: 0 }); }
      } else if (e.key.toLowerCase() === 'r') {
        setIsZoomed(false); setZoomLevel(1); setPosition({ x: 0, y: 0 });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isZoomed, zoomLevel]);

  return (
    <div className="zoomable-image-container">
      <img
        src={src}
        alt={alt}
        className={`${className} ${isZoomed ? 'zoomed' : ''} ${isDragging ? 'no-transition' : 'smooth-zoom'}`}
        style={{
          transform: `scale(${zoomLevel}) translate(${position.x / zoomLevel}px, ${position.y / zoomLevel}px)`,
          cursor: isZoomed ? (isDragging ? 'grabbing' : 'grab') : 'zoom-in'
        }}
        ref={imgRef}
        onClick={handleImageClick}
        onDoubleClick={handleDoubleClick}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onError={onError}
      />
      <div className="zoom-controls">
        <button onClick={() => stepZoom(-0.5)} title="Zoom out">−</button>
        <span className="zoom-readout">{Math.round(zoomLevel * 100)}%</span>
        <button onClick={() => stepZoom(0.5)} title="Zoom in">+</button>
        <button onClick={() => { setIsZoomed(true); setZoomLevel(2); }} title="1:1 (2x)">1:1</button>
        <button onClick={fitToView} title="Fit to view">Fit</button>
        <button onClick={handleZoomOut} title="Reset">Reset</button>
        <input
          type="range"
          min={100}
          max={500}
          step={10}
          value={Math.round(zoomLevel * 100)}
          onChange={(e) => {
            const rect = imgRef.current ? imgRef.current.getBoundingClientRect() : null;
            const next = Math.max(1, Math.min(5, Number(e.target.value) / 100));
            if (!isZoomed && next > 1) setIsZoomed(true);
            if (rect) setPosition((p) => clampPosition(p, next, rect));
            setZoomLevel(next);
            if (next === 1) { setIsZoomed(false); setPosition({ x: 0, y: 0 }); }
          }}
          aria-label="Zoom level"
        />
      </div>
      {!isZoomed && (
        <div className="zoom-hint">Click or scroll to zoom</div>
      )}
    </div>
  );
}

// Autocomplete input component with real-time suggestions
function AutocompleteInput({ field, value, onChange, placeholder, className, onAutofill }) {
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [loading, setLoading] = useState(false);
  const timeoutRef = useRef(null);
  const inputRef = useRef(null);

  const fetchSuggestions = async (query) => {
    if (!query || query.length < 1) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }

    setLoading(true);
    try {
      // For name field, search previously verified cards for autofill
      if (field === 'name' && onAutofill) {
        const response = await fetch(`http://localhost:3001/api/search-cards?query=${encodeURIComponent(query)}&limit=8`);

        if (response.ok) {
          const data = await response.json();
          if (data.cards && data.cards.length > 0) {
            setSuggestions(data.cards); // Store full card objects
            setShowSuggestions(true);
          } else {
            setSuggestions([]);
            setShowSuggestions(false);
          }
        }
      } else {
        // For other fields, use field-specific autocomplete
        const response = await fetch('http://localhost:3001/api/field-autocomplete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ field, query, limit: 8 })
        });

        if (response.ok) {
          const data = await response.json();
          if (data.suggestions && data.suggestions.length > 0) {
            setSuggestions(data.suggestions);
            setShowSuggestions(true);
          } else {
            setSuggestions([]);
            setShowSuggestions(false);
          }
        }
      }
    } catch (error) {
      console.error('Error fetching autocomplete suggestions:', error);
    }
    setLoading(false);
  };

  const handleInputChange = (e) => {
    const newValue = e.target.value;
    onChange(newValue);

    // Debounce autocomplete requests
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    timeoutRef.current = setTimeout(() => {
      fetchSuggestions(newValue);
    }, 300);
  };

  const handleSuggestionClick = async (suggestion) => {
    setShowSuggestions(false);
    setSuggestions([]);

    // If suggestion is a card object (from name field search)
    if (typeof suggestion === 'object' && suggestion.name) {
      onChange(suggestion.name);
      // Autofill all fields from this card
      if (field === 'name' && onAutofill) {
        onAutofill(suggestion);
      }
    } else {
      // String suggestion (from field autocomplete)
      onChange(suggestion);
    }
  };

  const handleBlur = () => {
    // Delay hiding to allow clicking on suggestions
    setTimeout(() => {
      setShowSuggestions(false);
    }, 200);
  };

  return (
    <div className="autocomplete-wrapper" style={{ position: 'relative' }}>
      <input
        ref={inputRef}
        type="text"
        value={value || ''}
        onChange={handleInputChange}
        onFocus={() => {
          if (suggestions.length > 0) {
            setShowSuggestions(true);
          }
        }}
        onBlur={handleBlur}
        placeholder={placeholder}
        className={className}
      />
      {loading && (
        <div style={{
          position: 'absolute',
          right: '8px',
          top: '50%',
          transform: 'translateY(-50%)',
          fontSize: '10px',
          color: '#999'
        }}>
          ...
        </div>
      )}
      {showSuggestions && suggestions.length > 0 && (
        <div className="autocomplete-suggestions" style={{
          position: 'absolute',
          top: '100%',
          left: 0,
          right: 0,
          backgroundColor: '#fff',
          border: '1px solid #4a90e2',
          borderRadius: '4px',
          maxHeight: '150px',
          overflowY: 'auto',
          zIndex: 1000,
          boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
          marginTop: '2px'
        }}>
          {suggestions.map((suggestion, idx) => {
            // Check if suggestion is a card object or a string
            const isCardObject = typeof suggestion === 'object' && suggestion.name;

            return (
              <div
                key={idx}
                onClick={() => handleSuggestionClick(suggestion)}
                style={{
                  padding: '8px 12px',
                  cursor: 'pointer',
                  borderBottom: idx < suggestions.length - 1 ? '1px solid #eee' : 'none',
                  fontSize: '13px',
                  transition: 'background-color 0.15s'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = '#f0f7ff';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = '#fff';
                }}
              >
                {isCardObject ? (
                  <div>
                    <div style={{ fontWeight: 'bold' }}>{suggestion.name}</div>
                    <div style={{ fontSize: '11px', color: '#666', marginTop: '2px' }}>
                      {[suggestion.copyright_year, suggestion.brand, suggestion.team, suggestion.number].filter(Boolean).join(' • ')}
                    </div>
                  </div>
                ) : (
                  suggestion
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// Features multi-select component
function FeaturesSelector({ value, availableFeatures, onChange }) {
  const [selectedFeatures, setSelectedFeatures] = useState(() => {
    if (!value || value === 'none') return [];
    return value.split(',').map(f => f.trim()).filter(f => f);
  });
  const [customFeature, setCustomFeature] = useState('');
  const [showCustomInput, setShowCustomInput] = useState(false);
  const [addedCustomFeatures, setAddedCustomFeatures] = useState([]);

  // Sync selectedFeatures when value prop changes (e.g., when switching cards)
  useEffect(() => {
    if (!value || value === 'none') {
      setSelectedFeatures([]);
    } else {
      setSelectedFeatures(value.split(',').map(f => f.trim()).filter(f => f));
    }
  }, [value]);

  // Only show features that exist in the database, plus custom added features
  const allFeatures = [...new Set([...availableFeatures, ...selectedFeatures, ...addedCustomFeatures])];

  const handleFeatureToggle = (feature) => {
    const newSelected = selectedFeatures.includes(feature)
      ? selectedFeatures.filter(f => f !== feature)
      : [...selectedFeatures, feature];

    setSelectedFeatures(newSelected);
    onChange(newSelected.length === 0 ? 'none' : newSelected.join(','));
  };

  const addCustomFeature = () => {
    const trimmed = customFeature.trim();
    if (trimmed && !allFeatures.includes(trimmed)) {
      setAddedCustomFeatures(prev => [...prev, trimmed]);
      setCustomFeature('');
      setShowCustomInput(false);
    }
  };

  return (
    <div className="features-selector">
      <div className="features-grid">
        {allFeatures.map(feature => (
          <label key={feature} className="feature-option">
            <input
              type="checkbox"
              checked={selectedFeatures.includes(feature)}
              onChange={() => handleFeatureToggle(feature)}
            />
            <span>{formatFieldValue('features', feature)}</span>
          </label>
        ))}
      </div>
      
      {!showCustomInput && (
        <button 
          type="button" 
          onClick={() => setShowCustomInput(true)}
          className="add-custom-feature"
        >
          + Add Custom Feature
        </button>
      )}
      
      {showCustomInput && (
        <div className="custom-feature-input">
          <input
            type="text"
            value={customFeature}
            onChange={(e) => setCustomFeature(e.target.value)}
            placeholder="Enter custom feature"
            onKeyPress={(e) => e.key === 'Enter' && addCustomFeature()}
          />
          <button onClick={addCustomFeature}>Add</button>
          <button onClick={() => { setShowCustomInput(false); setCustomFeature(''); }}>Cancel</button>
        </div>
      )}
    </div>
  );
}

function App() {
  const navigate = useNavigate();
  const [pendingCards, setPendingCards] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const reprocessControllerRef = useRef(null);
  const [isEditing, setIsEditing] = useState(false);
  const [editedData, setEditedData] = useState([]);
  const [lastSaved, setLastSaved] = useState(null);
  const [autoSaving, setAutoSaving] = useState(false);
  const [fieldOptions, setFieldOptions] = useState(null);
  const [verificationMode, setVerificationMode] = useState('single'); // 'single' or 'entire'
  const [currentCardIndex, setCurrentCardIndex] = useState(0);
  const [cardSuggestions, setCardSuggestions] = useState({}); // { cardIndex: [suggestions] }
  const [showSuggestions, setShowSuggestions] = useState({}); // { cardIndex: true/false }
  const suggestionTimeoutRef = useRef(null);

  // Undo/Redo functionality
  const [verificationHistory, setVerificationHistory] = useState([]);
  const [canUndo, setCanUndo] = useState(false);

  // Unsaved changes tracking
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [originalData, setOriginalData] = useState([]);

  // Confirmation dialog state
  const [confirmDialog, setConfirmDialog] = useState({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: null
  });

  // Session recovery state
  const [showRecovery, setShowRecovery] = useState(false);
  const [recoverySession, setRecoverySession] = useState(null);

  useEffect(() => {
    // Check for saved session on mount
    const checkSavedSession = () => {
      try {
        // Check if we've already shown recovery for this browser session
        const recoveryShown = sessionStorage.getItem('recoveryShown');
        if (recoveryShown) {
          return; // Don't show recovery again in this browser session
        }

        const savedSession = localStorage.getItem('editSession');
        if (savedSession) {
          const session = JSON.parse(savedSession);
          const now = Date.now();
          const sessionAge = now - session.timestamp;
          const oneHour = 3600000;

          // Only show recovery if session is less than 1 hour old and not currently editing
          if (sessionAge < oneHour && !isEditing) {
            setRecoverySession(session);
            setShowRecovery(true);
          } else if (sessionAge >= oneHour) {
            // Clear old session
            localStorage.removeItem('editSession');
          }
        }
      } catch (error) {
        console.error('Error checking saved session:', error);
        localStorage.removeItem('editSession');
      }
    };

    checkSavedSession();
    fetchPendingCards();
    fetchFieldOptions();

    // Poll for newly processed cards every 10 seconds
    const pollInterval = setInterval(() => {
      // Only poll if not currently processing an action
      if (!processing && !reprocessing) {
        fetchPendingCards();
      }
    }, 10000);

    // Add global unhandled rejection handler for debugging
    const handleUnhandledRejection = (event) => {
      event.preventDefault();
      console.warn('Suppressed unhandled rejection:', event.reason);
    };
    window.addEventListener('unhandledrejection', handleUnhandledRejection);

    return () => {
      clearInterval(pollInterval);
      window.removeEventListener('unhandledrejection', handleUnhandledRejection);
    };
  }, []);

  // Auto-start editing when card changes (isEditing intentionally excluded to prevent loops)
  useEffect(() => {
    if (pendingCards.length > 0 && !isEditing) {
      const currentCard = pendingCards[currentIndex];
      if (currentCard && currentCard.data) {
        if (verificationMode === 'single') {
          const processedCard = { ...currentCard.data[currentCardIndex] };
          const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
          textFields.forEach(field => {
            if (processedCard[field] && typeof processedCard[field] === 'string') {
              processedCard[field] = processedCard[field].toLowerCase();
            }
          });
          setEditedData([processedCard]);
        } else {
          const processedData = currentCard.data.map(card => {
            const processedCard = { ...card };
            const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
            textFields.forEach(field => {
              if (processedCard[field] && typeof processedCard[field] === 'string') {
                processedCard[field] = processedCard[field].toLowerCase();
              }
            });
            return processedCard;
          });
          setEditedData(processedData);
          setOriginalData(JSON.parse(JSON.stringify(processedData))); // Deep copy for comparison
        }
        setIsEditing(true);
        setHasUnsavedChanges(false); // Reset on new card
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingCards, currentIndex, currentCardIndex, verificationMode]);

  const fetchFieldOptions = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/field-options');
      if (response.ok) {
        try {
          const data = await response.json();
          setFieldOptions(data);
        } catch (_) {}
      }
    } catch (error) {
      console.error('Error fetching field options:', error);
    }
  };

  // Auto-lookup team for cards with unknown team
  const lookupTeamForCard = async (card, cardIndex) => {
    const team = card.team || '';
    if (team.toLowerCase() === 'unknown' || team === '') {
      try {
        const response = await fetch('http://localhost:3001/api/team-lookup', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: card.name,
            copyright_year: card.copyright_year,
            sport: card.sport
          })
        });
        if (!response.ok) return;
        let result;
        try {
          result = await response.json();
        } catch (_) { return; }
        if (result && result.team) {
          // Update the card with the looked up team
          setEditedData(prev => {
            const newData = [...prev];
            if (newData[cardIndex]) {
              newData[cardIndex] = {
                ...newData[cardIndex],
                team: result.team.toLowerCase(),
                _team_auto_filled: true,
                _team_source: result.source
              };
            }
            return newData;
          });
          console.log(`[team-lookup] Auto-filled team for ${card.name}: ${result.team} (${result.source})`);
        }
      } catch (error) {
        console.error('Error looking up team:', error);
      }
    }
  };

  // Effect to auto-lookup teams when editing starts
  useEffect(() => {
    if (isEditing && editedData.length > 0) {
      editedData.forEach((card, index) => {
        const team = card.team || '';
        if (team.toLowerCase() === 'unknown' || team === '') {
          lookupTeamForCard(card, index).catch(err => console.error('Team lookup failed:', err));
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing, editedData.length]);

  const fetchPendingCards = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/pending-cards');
      if (response.ok) {
        try {
          const data = await response.json();
          console.log('[fetchPendingCards] Loaded', data.length, 'pending images. Cards per image:', data.map(d => d.data?.length || 0));
          setPendingCards(data);
        } catch (_) {}
      }
      setLoading(false);
    } catch (error) {
      console.error('Error fetching pending cards:', error);
      setLoading(false);
    }
  };

  const fetchCardSuggestions = async (cardIndex, searchParams) => {
    // Only search if we have some meaningful criteria
    const { name, brand, number, copyright_year } = searchParams;
    if (!name && !brand && !number && !copyright_year) {
      setCardSuggestions(prev => ({ ...prev, [cardIndex]: [] }));
      return;
    }
    // Need at least 2 chars for name search
    if (name && name.length < 2 && !brand && !number && !copyright_year) {
      setCardSuggestions(prev => ({ ...prev, [cardIndex]: [] }));
      return;
    }

    try {
      const response = await fetch('http://localhost:3001/api/card-suggestions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(searchParams)
      });
      if (response.ok) {
        try {
          const data = await response.json();
          if (data.suggestions && data.suggestions.length > 0) {
            setCardSuggestions(prev => ({ ...prev, [cardIndex]: data.suggestions }));
            setShowSuggestions(prev => ({ ...prev, [cardIndex]: true }));
          } else {
            setCardSuggestions(prev => ({ ...prev, [cardIndex]: [] }));
            setShowSuggestions(prev => ({ ...prev, [cardIndex]: false }));
          }
        } catch (_) {}
      }
    } catch (error) {
      console.error('Error fetching card suggestions:', error);
    }
  };

  const applySuggestion = (cardIndex, suggestion) => {
    const newData = [...editedData];
    newData[cardIndex] = {
      ...newData[cardIndex],
      name: suggestion.name || newData[cardIndex].name,
      brand: suggestion.brand || newData[cardIndex].brand,
      number: suggestion.number || newData[cardIndex].number,
      copyright_year: suggestion.copyright_year || newData[cardIndex].copyright_year,
      team: suggestion.team || newData[cardIndex].team,
      card_set: suggestion.card_set || newData[cardIndex].card_set,
      sport: suggestion.sport || newData[cardIndex].sport,
      features: suggestion.features || newData[cardIndex].features,
      is_player: suggestion.is_player !== undefined ? suggestion.is_player : newData[cardIndex].is_player
    };
    setEditedData(newData);
    setShowSuggestions(prev => ({ ...prev, [cardIndex]: false }));
    // Trigger auto-save
    setTimeout(() => autoSaveProgress(newData), 500);
  };

  // Fetch verification history when card changes
  useEffect(() => {
    const fetchHistory = async () => {
      if (pendingCards.length === 0 || currentIndex >= pendingCards.length) {
        setVerificationHistory([]);
        setCanUndo(false);
        return;
      }

      const currentCard = pendingCards[currentIndex];
      if (!currentCard?.id) return;

      try {
        const response = await fetch(`http://localhost:3001/api/verification-history/${currentCard.id}`);
        if (response.ok) {
          const data = await response.json();
          setVerificationHistory(data.history || []);
          setCanUndo(data.history && data.history.length > 0);
        } else {
          setVerificationHistory([]);
          setCanUndo(false);
        }
      } catch (error) {
        console.error('Failed to fetch verification history:', error);
        setVerificationHistory([]);
        setCanUndo(false);
      }
    };

    fetchHistory();
  }, [pendingCards, currentIndex]);

  // Undo last action
  const handleUndo = async () => {
    console.log('Undo clicked - canUndo:', canUndo, 'pendingCards.length:', pendingCards.length);

    if (!canUndo || pendingCards.length === 0) {
      console.log('Undo blocked - canUndo:', canUndo, 'pendingCards.length:', pendingCards.length);
      return;
    }

    const currentCard = pendingCards[currentIndex];
    console.log('Current card:', currentCard?.id);

    if (!currentCard?.id) {
      console.log('Undo blocked - no current card ID');
      return;
    }

    try {
      console.log('Calling undo API for card:', currentCard.id);
      const response = await fetch(`http://localhost:3001/api/undo/${currentCard.id}`, {
        method: 'POST'
      });

      if (response.ok) {
        const result = await response.json();

        // Reload cards to get updated data
        await fetchPendingCards();

        // Show success message
        console.log('Undo successful:', result.message || 'Last action undone');
        alert('Undo successful!');

        // Update history
        setVerificationHistory(prev => prev.slice(0, -1));
        setCanUndo(verificationHistory.length > 1);
      } else {
        const error = await response.json();
        console.error('Undo failed:', error.error || 'Unknown error');
        alert(`Failed to undo: ${error.error || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Undo error:', error);
      alert('Failed to undo action');
    }
  };

  // Keyboard shortcut for undo (Cmd/Ctrl+Z)
  useEffect(() => {
    const handleKeyDown = (e) => {
      // Check for Cmd+Z (Mac) or Ctrl+Z (Windows/Linux)
      if ((e.metaKey || e.ctrlKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        if (canUndo) {
          handleUndo();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [canUndo, pendingCards, currentIndex]);

  // Track unsaved changes by comparing edited data with original
  useEffect(() => {
    if (!isEditing || editedData.length === 0 || originalData.length === 0) {
      setHasUnsavedChanges(false);
      return;
    }

    // Deep comparison of editedData vs originalData
    const hasChanges = JSON.stringify(editedData) !== JSON.stringify(originalData);
    setHasUnsavedChanges(hasChanges);
  }, [editedData, originalData, isEditing]);

  // Save edit session to localStorage for recovery
  useEffect(() => {
    if (isEditing && editedData.length > 0 && pendingCards.length > 0) {
      const currentCard = pendingCards[currentIndex];
      if (currentCard?.id) {
        const sessionState = {
          cardId: currentCard.id,
          editedData: editedData,
          currentIndex: currentIndex,
          currentCardIndex: currentCardIndex,
          verificationMode: verificationMode,
          timestamp: Date.now()
        };
        localStorage.setItem('editSession', JSON.stringify(sessionState));
      }
    } else {
      // Clear session when not editing
      localStorage.removeItem('editSession');
    }
  }, [isEditing, editedData, currentIndex, currentCardIndex, verificationMode, pendingCards]);

  // Warn user before leaving page with unsaved changes
  useEffect(() => {
    const handleBeforeUnload = (e) => {
      if (hasUnsavedChanges) {
        e.preventDefault();
        e.returnValue = ''; // Required for Chrome
        return ''; // Required for some browsers
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasUnsavedChanges]);

  // Recovery handlers
  const handleRestore = () => {
    if (!recoverySession) return;

    try {
      // Find the card that was being edited
      const cardIndex = pendingCards.findIndex(card => card.id === recoverySession.cardId);

      if (cardIndex !== -1) {
        setCurrentIndex(cardIndex);
        setCurrentCardIndex(recoverySession.currentCardIndex || 0);
        setVerificationMode(recoverySession.verificationMode || 'single');
        setEditedData(recoverySession.editedData);
        setOriginalData(JSON.parse(JSON.stringify(recoverySession.editedData)));
        setIsEditing(true);
        setShowRecovery(false);
        setRecoverySession(null);
        // Mark that we've shown recovery for this browser session
        sessionStorage.setItem('recoveryShown', 'true');
        console.log('Session restored successfully');
      } else {
        // Card no longer exists
        setShowRecovery(false);
        setRecoverySession(null);
        localStorage.removeItem('editSession');
        sessionStorage.setItem('recoveryShown', 'true');
        console.log('Card from saved session no longer exists');
      }
    } catch (error) {
      console.error('Error restoring session:', error);
      setShowRecovery(false);
      setRecoverySession(null);
      localStorage.removeItem('editSession');
      sessionStorage.setItem('recoveryShown', 'true');
    }
  };

  const handleDiscardRecovery = () => {
    setShowRecovery(false);
    setRecoverySession(null);
    localStorage.removeItem('editSession');
    // Mark that we've shown recovery for this browser session
    sessionStorage.setItem('recoveryShown', 'true');
  };

  // Wrapper to show confirmation for destructive actions
  const handleActionWithConfirm = (action, mode = null) => {
    if (pendingCards.length === 0) return;

    const actionMode = mode || verificationMode;
    const currentCard = pendingCards[currentIndex];

    // Determine if we need confirmation
    const needsConfirmation = actionMode === 'entire' || (action === 'fail' && actionMode === 'entire');

    if (needsConfirmation) {
      const cardCount = actionMode === 'entire' ? currentCard.data.length : 1;
      const actionText = action === 'pass' ? 'pass' : 'fail';
      const actionTextUpper = action === 'pass' ? 'PASS' : 'FAIL';

      setConfirmDialog({
        isOpen: true,
        title: `${actionTextUpper} ${cardCount} CARD${cardCount > 1 ? 'S' : ''}?`,
        message: `are you sure you want to ${actionText} ${cardCount} card${cardCount > 1 ? 's' : ''}? this action will ${action === 'pass' ? 'add them to the database' : 'discard them'}.`,
        onConfirm: () => {
          setConfirmDialog({ ...confirmDialog, isOpen: false });
          handleAction(action, mode);
        }
      });
    } else {
      // Single card actions don't need confirmation
      handleAction(action, mode);
    }
  };

  const handleAction = async (action, mode = null) => {
    if (pendingCards.length === 0) return;

    // Cancel any pending auto-save to prevent race condition
    if (autoSaveTimeoutRef.current) {
      clearTimeout(autoSaveTimeoutRef.current);
      autoSaveTimeoutRef.current = null;
    }

    // Use passed mode or current verificationMode
    const actionMode = mode || verificationMode;

    setProcessing(true);
    const currentCard = pendingCards[currentIndex];

    try {
      let endpoint, requestBody;

      if (actionMode === 'single') {
        // Single card verification
        const modifiedCardData = isEditing ? editedData[0] : currentCard.data[currentCardIndex];
        endpoint = `http://localhost:3001/api/${action}-card/${currentCard.id}/${currentCardIndex}`;
        requestBody = action === 'pass' && isEditing ? { modifiedData: modifiedCardData } : {};
      } else {
        // Entire photo verification
        endpoint = `http://localhost:3001/api/${action}/${currentCard.id}`;
        requestBody = action === 'pass' && isEditing ? { modifiedData: editedData } : {};
      }

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });

      if (response.ok) {
        try { await response.json(); } catch (_) {}

        // Clear recovery flag so recovery banner can show for future unsaved work
        sessionStorage.removeItem('recoveryShown');

        // Re-fetch pending cards from server to ensure sync
        try {
          const refreshResponse = await fetch('http://localhost:3001/api/pending-cards');
          if (refreshResponse.ok) {
            const freshData = await refreshResponse.json();
            setPendingCards(freshData);

            if (actionMode === 'single') {
              // Find the same image in fresh data
              const sameImage = freshData.find(c => c.id === currentCard.id);
              if (sameImage && sameImage.data.length > 0) {
                // Image still has cards, stay on it
                const newCardIndex = currentCardIndex >= sameImage.data.length ? 0 : currentCardIndex;
                setCurrentCardIndex(newCardIndex);
                const nextCard = { ...sameImage.data[newCardIndex] };
                const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
                textFields.forEach(field => {
                  if (nextCard[field] && typeof nextCard[field] === 'string') {
                    nextCard[field] = nextCard[field].toLowerCase();
                  }
                });
                setEditedData([nextCard]);
              } else {
                // Image done or removed, move to next
                const newIndex = currentIndex >= freshData.length ? Math.max(0, freshData.length - 1) : currentIndex;
                setCurrentIndex(newIndex);
                setCurrentCardIndex(0);
                setIsEditing(false);
                setEditedData([]);
              }
            } else {
              // Entire photo mode - image should be removed
              if (freshData.length === 0) {
                // No more pending cards, navigate to main page
                navigate('/');
                return;
              }
              const newIndex = currentIndex >= freshData.length ? Math.max(0, freshData.length - 1) : currentIndex;
              setCurrentIndex(newIndex);
              setCurrentCardIndex(0);
              setIsEditing(false);
              setEditedData([]);
            }
          }
        } catch (refreshErr) {
          console.error('Error refreshing cards:', refreshErr);
        }
      } else {
        let errorMsg = 'Unknown error';
        try {
          const errorResult = await response.json();
          errorMsg = errorResult.error || errorMsg;
        } catch (_) {}
        alert(`Error processing card: ${errorMsg}`);
      }
    } catch (error) {
      console.error('Error processing action:', error);
      alert('Error processing card');
    }
    
    setProcessing(false);
  };

  const autoSaveProgress = async (dataToSave = null) => {
    if (pendingCards.length === 0) return;
    // Don't auto-save during pass/fail actions to prevent race condition
    if (processing) return;

    const currentCard = pendingCards[currentIndex];
    const saveData = dataToSave || editedData;

    if (saveData.length === 0) return;

    setAutoSaving(true);

    try {
      // In single card mode, send cardIndex so server knows which card to update
      const requestBody = verificationMode === 'single'
        ? { data: saveData, cardIndex: currentCardIndex }
        : { data: saveData };

      const response = await fetch(`http://localhost:3001/api/save-progress/${currentCard.id}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      });
      
      if (response.ok) {
        try {
          const result = await response.json();
          setLastSaved(new Date(result.timestamp));
        } catch (_) {
          setLastSaved(new Date());
        }

        // Update the current card's data in the local state
        const updatedCards = [...pendingCards];
        updatedCards[currentIndex] = {
          ...currentCard,
          data: saveData
        };
        setPendingCards(updatedCards);

        // Update original data to clear unsaved changes indicator
        setOriginalData(JSON.parse(JSON.stringify(saveData)));
        setHasUnsavedChanges(false);
      } else {
        console.error('Failed to auto-save progress');
      }
    } catch (error) {
      console.error('Error auto-saving progress:', error);
    }

    setAutoSaving(false);
  };

  // Debounce timer for auto-save
  const autoSaveTimeoutRef = React.useRef(null);

  const updateCardField = (cardIndex, field, value) => {
    const newData = [...editedData];
    // Convert text fields to lowercase for consistency
    const textFields = ['name', 'sport', 'brand', 'team', 'card_set', 'notes'];
    let processedValue = textFields.includes(field) && typeof value === 'string'
      ? value.toLowerCase()
      : value;

    if (field === 'condition' && typeof processedValue === 'string') {
      processedValue = normalizeCondition(processedValue);
    }
    if (field === 'features' && typeof processedValue === 'string') {
      processedValue = processedValue
        .split(',')
        .map((f) => f.trim().replace(/_/g, ' ').toLowerCase())
        .filter(Boolean)
        .join(',');
    }
    newData[cardIndex] = { ...newData[cardIndex], [field]: processedValue };
    setEditedData(newData);

    // Auto-save with debouncing (save 2 seconds after last edit)
    if (autoSaveTimeoutRef.current) {
      clearTimeout(autoSaveTimeoutRef.current);
    }

    autoSaveTimeoutRef.current = setTimeout(() => {
      autoSaveProgress(newData);
    }, 2000);

    // Trigger suggestions when name changes (debounced)
    const suggestionFields = ['name', 'brand', 'number', 'copyright_year'];
    if (suggestionFields.includes(field)) {
      if (suggestionTimeoutRef.current) {
        clearTimeout(suggestionTimeoutRef.current);
      }
      suggestionTimeoutRef.current = setTimeout(() => {
        const card = newData[cardIndex];
        fetchCardSuggestions(cardIndex, {
          name: card.name,
          brand: card.brand,
          number: card.number,
          copyright_year: card.copyright_year,
          sport: card.sport
        }).catch(err => console.error('Suggestion fetch failed:', err));
      }, 500);
    }
  };

  const handleAutofill = (cardIndex, cardData) => {
    // Autofill all fields from the database card except the name (already set)
    const newData = [...editedData];
    const fieldsToAutofill = ['sport', 'brand', 'team', 'card_set', 'number', 'copyright_year', 'condition', 'is_player', 'features'];

    fieldsToAutofill.forEach(field => {
      if (cardData[field] !== null && cardData[field] !== undefined) {
        newData[cardIndex] = { ...newData[cardIndex], [field]: cardData[field] };
      }
    });

    setEditedData(newData);

    // Auto-save after autofill
    if (autoSaveTimeoutRef.current) {
      clearTimeout(autoSaveTimeoutRef.current);
    }
    autoSaveTimeoutRef.current = setTimeout(() => {
      autoSaveProgress(newData);
    }, 2000);
  };

  const addNewCard = () => {
    const newCard = {
      name: '',
      sport: '',
      brand: '',
      number: '',
      copyright_year: '',
      team: '',
      is_player: true,
      features: 'none',
      condition: 'near mint',
      card_set: ''
    };
    const newData = [...editedData, newCard];
    setEditedData(newData);
    
    // Auto-save immediately when adding a card
    setTimeout(() => autoSaveProgress(newData), 500);
  };

  const removeCard = (cardIndex) => {
    if (editedData.length <= 1) {
      alert('Cannot remove the last card');
      return;
    }
    const newData = editedData.filter((_, index) => index !== cardIndex);
    setEditedData(newData);
    
    // Auto-save immediately when removing a card
    setTimeout(() => autoSaveProgress(newData), 500);
  };

  const handleReprocess = async (mode = 'remaining') => {
    if (pendingCards.length === 0) return;

    setReprocessing(true);
    const currentCard = pendingCards[currentIndex];
    const controller = new AbortController();
    reprocessControllerRef.current = controller;

    try {
      const response = await fetch(`http://localhost:3001/api/reprocess/${currentCard.id}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ mode }),
        signal: controller.signal,
      });

      let result;
      try {
        result = await response.json();
      } catch (parseError) {
        console.error('Failed to parse reprocess response:', parseError);
        alert('Re-processing failed: Server returned invalid response');
        setReprocessing(false);
        return;
      }

      if (response.ok) {
        // Update the current card's data with the re-processed result
        const updatedCards = [...pendingCards];
        updatedCards[currentIndex] = {
          ...currentCard,
          data: result.data
        };
        setPendingCards(updatedCards);

        // Reset edit state
        setIsEditing(false);
        setEditedData([]);

        alert('Card data re-processed successfully! Please review the updated information.');
      } else {
        alert(`Re-processing failed: ${result.error || 'Unknown error'}\n\nDetails: ${result.details || 'No additional details'}`);
      }
    } catch (error) {
      if (error.name === 'AbortError') {
        console.log('Reprocess was cancelled');
      } else {
        console.error('Error re-processing card:', error);
        alert('Error re-processing card: ' + (error.message || 'Unknown error'));
      }
    }
    
    setReprocessing(false);
  };

  const cancelReprocess = async () => {
    try {
      const currentCard = pendingCards[currentIndex];
      await fetch(`http://localhost:3001/api/cancel-reprocess/${currentCard.id}`, { method: 'POST' });
    } catch (_) {}
    try { reprocessControllerRef.current?.abort(); } catch (_) {}
    setReprocessing(false);
  };

  const goToPrevious = () => {
    if (reprocessing) {
      alert('Please wait for re-processing to complete');
      return;
    }
    setIsEditing(false); // Reset edit state to trigger re-init for new card
    setCurrentIndex(Math.max(0, currentIndex - 1));
  };

  const goToNext = () => {
    if (reprocessing) {
      alert('Please wait for re-processing to complete');
      return;
    }
    setIsEditing(false); // Reset edit state to trigger re-init for new card
    setCurrentIndex(Math.min(pendingCards.length - 1, currentIndex + 1));
  };

  if (loading) {
    return <div className="loading">Loading pending cards...</div>;
  }

  if (pendingCards.length === 0) {
    return (
      <div className="no-cards">
        <h2>verification complete</h2>
        <p>no pending cards for verification</p>
        <button 
          className="return-home-button" 
          onClick={() => navigate('/')}
        >
          return to main page
        </button>
      </div>
    );
  }

  const currentCard = pendingCards[currentIndex];
  let displayData;
  
  if (verificationMode === 'single') {
    displayData = isEditing ? editedData : [currentCard.data[currentCardIndex]];
  } else {
    displayData = isEditing ? editedData : currentCard.data;
  }

  return (
    <div className="App">
      {/* Reprocess progress bar at top */}
      <div className={`verify-progress ${reprocessing ? 'show' : ''}`} role="status" aria-live="polite">
        <div className="verify-progress-inner">
          <div className="verify-progress-title">Re-processing card data…</div>
          <div className="verify-progress-actions">
            <button className="cancel-processing" type="button" onClick={cancelReprocess} title="Cancel re-processing">cancel</button>
          </div>
          <div className="progress-track top">
            <div className="progress-bar indeterminate" />
          </div>
        </div>
      </div>

      {/* Session recovery banner */}
      {showRecovery && recoverySession && (
        <div className="recovery-banner">
          <div className="recovery-content">
            <div className="recovery-icon">⚠️</div>
            <div className="recovery-text">
              <strong>UNSAVED WORK FOUND</strong>
              <p>found unsaved work from previous session. restore it?</p>
            </div>
            <div className="recovery-actions">
              <button onClick={handleRestore} className="restore-button">
                restore
              </button>
              <button onClick={handleDiscardRecovery} className="discard-button">
                discard
              </button>
            </div>
          </div>
        </div>
      )}

      <header className="App-header">
        <div className="header-top">
          <h1>trading card verification</h1>
          <button 
            className="back-button" 
            onClick={() => navigate('/')}
          >
            ← Back to Main
          </button>
        </div>
        <div className="verification-controls">
          <div className="verification-mode">
            <label>Verification Mode:</label>
            <select
              value={verificationMode}
              onChange={(e) => {
                setVerificationMode(e.target.value);
                setCurrentCardIndex(0);
                setIsEditing(false);
                setEditedData([]);
              }}
            >
              <option value="entire">ENTIRE PHOTO</option>
              <option value="single">SINGLE CARD</option>
            </select>
          </div>
          
          <div className="card-info">
            <p>Photo {currentIndex + 1} of {pendingCards.length}</p>
            {verificationMode === 'single' && currentCard.data.length > 1 && (
              <p>Card {currentCardIndex + 1} of {currentCard.data.length}</p>
            )}
          </div>
        </div>
      </header>

      <div className="card-container">
        <div className="image-section">
          {/* Single container with images side-by-side */}
          {verificationMode === 'single' && currentCard?.data?.length > 0 ? (
            (() => {
              const sel = currentCard.data[Math.min(currentCardIndex, currentCard.data.length - 1)] || {};
              const stem = (currentCard.imageFile || '').replace(/\.[^.]+$/, '');
              const pos = sel?._grid_metadata?.position ?? sel?.grid_position ?? currentCardIndex;
              let croppedFilename = sel?.cropped_back_file || sel?._grid_metadata?.cropped_back_alias;
              if (croppedFilename) {
                croppedFilename = croppedFilename.split('/').pop();
              }
              if (!croppedFilename) {
                const cardName = (sel?.name || 'unknown')
                  .split(' ')
                  .map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
                  .join('_');
                const cardNumber = (sel?.number || 'no_num').replace(/[^a-zA-Z0-9]/g, '_');
                croppedFilename = `${stem}_pos${pos}_${cardName}_${cardNumber}.png`;
              }
              const backCropUrl = croppedFilename ? `http://localhost:3001/api/cropped-back-image/${croppedFilename}` : null;

              return (
                <div className="unified-image-container">
                  <div className="image-grid">
                    <div className="image-with-label">
                      <div className="image-label">FULL SCAN</div>
                      <ZoomableImage
                        src={`http://localhost:3001/api/bulk-back-image/${currentCard.imageFile}`}
                        alt="Full scan"
                        className="card-image"
                      />
                    </div>
                    {backCropUrl && (
                      <div className="image-with-label">
                        <div className="image-label">CROPPED</div>
                        <ZoomableImage
                          src={backCropUrl}
                          alt="Cropped back"
                          className="card-image"
                        />
                      </div>
                    )}
                  </div>
                </div>
              );
            })()
          ) : (
            <div className="main-image-block">
              <div className="main-image-title">Original Scan</div>
              <ZoomableImage
                src={`http://localhost:3001/api/bulk-back-image/${currentCard.imageFile}`}
                alt="Trading card"
                className="card-image"
              />
            </div>
          )}

          {/* Action buttons - placed right below images */}
          {verificationMode === 'single' && (
            <div className="below-image-actions">
              {canUndo && (
                <div className="action-group">
                  <button
                    onClick={handleUndo}
                    disabled={processing || reprocessing}
                    className="undo-button"
                    title="Undo last action (Cmd/Ctrl+Z)"
                  >
                    ← Undo
                  </button>
                </div>
              )}
              <div className="action-group">
                <span className="action-label">Card:</span>
                <button
                  onClick={() => handleActionWithConfirm('fail')}
                  disabled={processing || reprocessing}
                  className="fail-button"
                >
                  {processing ? '...' : 'Fail Card'}
                </button>
                <button
                  onClick={() => handleActionWithConfirm('pass')}
                  disabled={processing || reprocessing}
                  className="pass-button"
                >
                  {processing ? '...' : 'Pass Card'}
                </button>
              </div>
              <div className="action-group">
                <span className="action-label">Image:</span>
                <button
                  onClick={() => handleActionWithConfirm('fail', 'entire')}
                  disabled={processing || reprocessing}
                  className="fail-button"
                >
                  {processing ? '...' : 'Fail All'}
                </button>
                <button
                  onClick={() => handleActionWithConfirm('pass', 'entire')}
                  disabled={processing || reprocessing}
                  className="pass-button"
                >
                  {processing ? '...' : 'Pass All'}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="data-section">
          <h3>extracted card data:</h3>
          <div className="edit-controls-top">
            <button onClick={addNewCard} className="add-card-button">
              + Add Card
            </button>
            <button
              onClick={() => handleReprocess('remaining')}
              className="reprocess-button"
              disabled={reprocessing}
            >
              {reprocessing ? 'Re-processing...' : 'Re-process Remaining'}
            </button>
            <button
              onClick={() => handleReprocess('all')}
              className="reprocess-button reprocess-all"
              disabled={reprocessing}
            >
              Re-process All
            </button>
            <div className="save-status">
              {hasUnsavedChanges && (
                <span className="unsaved-changes-indicator" title="You have unsaved changes">
                  ● UNSAVED CHANGES
                </span>
              )}
              {autoSaving ? (
                <span className="saving">Saving...</span>
              ) : lastSaved ? (
                <span className="saved">
                  Saved {new Date(lastSaved).toLocaleTimeString()}
                </span>
              ) : (
                <span className="unsaved">Auto-save enabled</span>
              )}
            </div>
          </div>
          
          <div className="card-data">
            {displayData.map((card, index) => (
              <div key={index} className="card-entry">
                <div className="card-header">
                  <h4>Card {index + 1}:</h4>
                  {card._overall_confidence && (
                    <div className="overall-confidence" style={{ marginLeft: '12px' }}>
                      <span style={{ fontSize: '0.875rem', color: '#6b7280' }}>Overall Confidence:</span>
                      <ConfidenceIndicator confidence={card._overall_confidence} fieldName="overall" />
                    </div>
                  )}
                  {isEditing && displayData.length > 1 && (
                    <button 
                      onClick={() => removeCard(index)} 
                      className="remove-card-button"
                      title="Remove this card"
                    >
                      ✕
                    </button>
                  )}
                </div>
                <div className="card-fields">
                  {isEditing ? (
                    <>
                      <div className="field-group">
                        <label><strong>{formatFieldName('name')}:</strong></label>
                        <AutocompleteInput
                          field="name"
                          value={card.name}
                          onChange={(value) => updateCardField(index, 'name', value)}
                          onAutofill={(cardData) => handleAutofill(index, cardData)}
                          placeholder="player name"
                        />
                      </div>
                      {showSuggestions[index] && cardSuggestions[index]?.length > 0 && (
                        <div className="suggestions-container" style={{
                          backgroundColor: '#f8f9fa',
                          border: '2px solid #4a90e2',
                          borderRadius: '8px',
                          marginBottom: '15px',
                          maxHeight: '200px',
                          overflowY: 'auto',
                          boxShadow: '0 2px 8px rgba(74, 144, 226, 0.2)'
                        }}>
                          <div style={{
                            padding: '8px 12px',
                            borderBottom: '2px solid #e0e0e0',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            backgroundColor: '#4a90e2'
                          }}>
                            <span style={{ fontSize: '12px', color: '#fff', fontWeight: '600' }}>
                              Matching cards from database ({cardSuggestions[index].length})
                            </span>
                            <button
                              onClick={() => setShowSuggestions(prev => ({ ...prev, [index]: false }))}
                              style={{
                                background: 'none',
                                border: 'none',
                                color: '#fff',
                                cursor: 'pointer',
                                fontSize: '12px',
                                fontWeight: '500'
                              }}
                            >
                              ✕
                            </button>
                          </div>
                          {cardSuggestions[index].map((suggestion, sIdx) => (
                            <div
                              key={sIdx}
                              onClick={() => applySuggestion(index, suggestion)}
                              style={{
                                padding: '10px 12px',
                                borderBottom: sIdx < cardSuggestions[index].length - 1 ? '1px solid #e0e0e0' : 'none',
                                cursor: 'pointer',
                                fontSize: '13px',
                                backgroundColor: '#fff',
                                transition: 'all 0.2s'
                              }}
                              onMouseEnter={(e) => {
                                e.currentTarget.style.backgroundColor = '#e3f2fd';
                                e.currentTarget.style.transform = 'translateX(4px)';
                              }}
                              onMouseLeave={(e) => {
                                e.currentTarget.style.backgroundColor = '#fff';
                                e.currentTarget.style.transform = 'translateX(0)';
                              }}
                            >
                              <div style={{ color: '#2c3e50', fontWeight: '600', marginBottom: '4px' }}>
                                {suggestion.name}
                              </div>
                              <div style={{ fontSize: '11px', color: '#7f8c8d' }}>
                                {suggestion.brand} #{suggestion.number} ({suggestion.copyright_year})
                                {suggestion.team && suggestion.team !== 'unknown' && (
                                  <span style={{ color: '#e67e22', marginLeft: '8px' }}>{suggestion.team}</span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="field-group">
                        <label><strong>{formatFieldName('sport')}:</strong></label>
                        <AutocompleteInput
                          field="sport"
                          value={card.sport}
                          onChange={(value) => updateCardField(index, 'sport', value)}
                          placeholder="baseball, basketball, etc."
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('brand')}:</strong></label>
                        <AutocompleteInput
                          field="brand"
                          value={card.brand}
                          onChange={(value) => updateCardField(index, 'brand', value)}
                          placeholder="topps, upper deck, etc."
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('number')}:</strong></label>
                        <AutocompleteInput
                          field="number"
                          value={card.number}
                          onChange={(value) => updateCardField(index, 'number', value)}
                          placeholder="card number"
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('copyright_year')}:</strong></label>
                        <input 
                          type="text" 
                          value={card.copyright_year} 
                          onChange={(e) => updateCardField(index, 'copyright_year', e.target.value)}
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('team')}:</strong></label>
                        <AutocompleteInput
                          field="team"
                          value={card.team}
                          onChange={(value) => updateCardField(index, 'team', value)}
                          placeholder="team name"
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('is_player')}:</strong></label>
                        <select 
                          value={card.is_player} 
                          onChange={(e) => updateCardField(index, 'is_player', e.target.value === 'true')}
                        >
                          <option value={true}>yes</option>
                          <option value={false}>no</option>
                        </select>
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('features')}:</strong></label>
                        <FeaturesSelector 
                          value={card.features || 'none'}
                          availableFeatures={fieldOptions?.features || []}
                          onChange={(value) => updateCardField(index, 'features', value)}
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('condition')}:</strong></label>
                        <select 
                          value={normalizeCondition(card.condition)} 
                          onChange={(e) => updateCardField(index, 'condition', normalizeCondition(e.target.value))}
                        >
                          <option value="gem mint">gem mint (10)</option>
                          <option value="mint">mint (9)</option>
                          <option value="near mint">near mint (8)</option>
                          <option value="excellent">excellent (7)</option>
                          <option value="very good">very good (6)</option>
                          <option value="good">good (5)</option>
                          <option value="fair">fair (4)</option>
                          <option value="poor">poor (3)</option>
                        </select>
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('card_set')}:</strong></label>
                        <AutocompleteInput
                          field="card_set"
                          value={card.card_set}
                          onChange={(value) => updateCardField(index, 'card_set', value)}
                          placeholder="set name"
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('value_estimate')}:</strong></label>
                        <input
                          type="text"
                          value={card.value_estimate || ''}
                          onChange={(e) => updateCardField(index, 'value_estimate', e.target.value)}
                          placeholder="$1-5 or $12.34"
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('notes')}:</strong></label>
                        <textarea
                          value={card.notes || ''}
                          onChange={(e) => updateCardField(index, 'notes', e.target.value)}
                          placeholder="Additional notes about the card"
                          rows={2}
                          style={{ resize: 'vertical', width: '100%' }}
                        />
                      </div>
                    </>
                  ) : (
                    <>
                      <p>
                        <strong>{formatFieldName('name')}:</strong> 
                        <span>{formatFieldValue('name', card.name)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.name} fieldName="name" />
                      </p>
                      <p>
                        <strong>{formatFieldName('sport')}:</strong> 
                        <span>{formatFieldValue('sport', card.sport)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.sport} fieldName="sport" />
                      </p>
                      <p>
                        <strong>{formatFieldName('brand')}:</strong> 
                        <span>{formatFieldValue('brand', card.brand)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.brand} fieldName="brand" />
                      </p>
                      <p>
                        <strong>{formatFieldName('number')}:</strong> 
                        <span>{formatFieldValue('number', card.number)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.number} fieldName="number" />
                      </p>
                      <p>
                        <strong>{formatFieldName('copyright_year')}:</strong> 
                        <span>{formatFieldValue('copyright_year', card.copyright_year)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.copyright_year} fieldName="copyright_year" />
                      </p>
                      <p>
                        <strong>{formatFieldName('team')}:</strong> 
                        <span>{formatFieldValue('team', card.team)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.team} fieldName="team" />
                      </p>
                      <p>
                        <strong>{formatFieldName('card_set')}:</strong> 
                        <span>{formatFieldValue('card_set', card.card_set)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.card_set} fieldName="card_set" />
                      </p>
                      <p>
                        <strong>{formatFieldName('condition')}:</strong> 
                        <span>{formatFieldValue('condition', card.condition)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.condition} fieldName="condition" />
                      </p>
                      <p>
                        <strong>{formatFieldName('is_player')}:</strong> 
                        <span>{formatFieldValue('is_player', card.is_player)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.is_player} fieldName="is_player" />
                      </p>
                      <p>
                        <strong>{formatFieldName('features')}:</strong> 
                        <span>{formatFieldValue('features', card.features || 'none')}</span>
                        <ConfidenceIndicator confidence={card._confidence?.features} fieldName="features" />
                      </p>
                      {card.value_estimate !== undefined && (
                        <p>
                          <strong>{formatFieldName('value_estimate')}:</strong>
                          <span>{formatFieldValue('value_estimate', card.value_estimate)}</span>
                        </p>
                      )}
                      {card.notes && (
                        <p>
                          <strong>{formatFieldName('notes')}:</strong>
                          <span>{formatFieldValue('notes', card.notes)}</span>
                        </p>
                      )}
                    </>
                  )}
                </div>

                {/* TCDB verification removed */}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="controls">
        <div className="navigation">
          {verificationMode === 'single' && (
            <>
              <button
                onClick={() => {
                  setIsEditing(false);
                  setCurrentCardIndex(Math.max(0, currentCardIndex - 1));
                }}
                disabled={currentCardIndex === 0 || reprocessing || currentCard.data.length <= 1}
                className="nav-button"
                style={{ visibility: currentCard.data.length <= 1 ? 'hidden' : 'visible' }}
              >
                ← Previous Card
              </button>
              <button
                onClick={() => {
                  setIsEditing(false);
                  setCurrentCardIndex(Math.min(currentCard.data.length - 1, currentCardIndex + 1));
                }}
                disabled={currentCardIndex === currentCard.data.length - 1 || reprocessing || currentCard.data.length <= 1}
                className="nav-button"
                style={{ visibility: currentCard.data.length <= 1 ? 'hidden' : 'visible' }}
              >
                Next Card →
              </button>
            </>
          )}

          <button
            onClick={goToPrevious}
            disabled={currentIndex === 0 || reprocessing || pendingCards.length <= 1}
            className="nav-button"
            style={{ visibility: pendingCards.length <= 1 ? 'hidden' : 'visible' }}
          >
            ← Previous Photo
          </button>
          <button
            onClick={goToNext}
            disabled={currentIndex === pendingCards.length - 1 || reprocessing || pendingCards.length <= 1}
            className="nav-button"
            style={{ visibility: pendingCards.length <= 1 ? 'hidden' : 'visible' }}
          >
            Next Photo →
          </button>
        </div>

        {verificationMode !== 'single' && (
          <div className="action-buttons">
            {canUndo && (
              <button
                onClick={handleUndo}
                disabled={processing || reprocessing}
                className="undo-button"
                title="Undo last action (Cmd/Ctrl+Z)"
              >
                ← Undo
              </button>
            )}
            <button
              onClick={() => handleActionWithConfirm('fail')}
              disabled={processing || reprocessing}
              className="fail-button"
            >
              {processing ? 'Processing...' : 'Fail All'}
            </button>
            <button
              onClick={() => handleActionWithConfirm('pass')}
              disabled={processing || reprocessing}
              className="pass-button"
            >
              {processing ? 'Processing...' : 'Pass All'}
            </button>
          </div>
        )}
        
        <div className="system-controls">
          <button 
            onClick={() => navigate('/logs')}
            className="system-log-button"
            title="View system logs for debugging"
          >
            system logs
          </button>
        </div>
      </div>

      {/* Confirmation Dialog */}
      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        title={confirmDialog.title}
        message={confirmDialog.message}
        onConfirm={confirmDialog.onConfirm}
        onCancel={() => setConfirmDialog({ ...confirmDialog, isOpen: false })}
      />
    </div>
  );
}

export default App;
