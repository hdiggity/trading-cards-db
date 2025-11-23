import React, { useState, useEffect, useRef } from 'react';
import './App.css';

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
    'is_player_card': 'Player Card',
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
    case 'is_player_card':
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

// Zoomable image component
function ZoomableImage({ src, alt, className }) {
  const [isZoomed, setIsZoomed] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const imgRef = useRef(null);
  const pinchRef = useRef(null); // { initialDist, initialZoom, centerX, centerY }

  // Clamp panning so image stays reasonably in view when zoomed
  const clampPosition = (pos, z, rect) => {
    if (!rect) return pos;
    // Max pan relative to center based on extra size at current zoom
    const maxX = Math.max(0, (rect.width * (z - 1)) / 2);
    const maxY = Math.max(0, (rect.height * (z - 1)) / 2);
    return {
      x: Math.min(maxX, Math.max(-maxX, pos.x)),
      y: Math.min(maxY, Math.max(-maxY, pos.y)),
    };
  };
  
  const handleImageClick = (e) => {
    if (!isZoomed) {
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
    const rect = imgRef.current ? imgRef.current.getBoundingClientRect() : null;
    const prev = zoomLevel;
    const next = Math.max(1, Math.min(5, prev + delta));
    if (next > 1 && !isZoomed) setIsZoomed(true);
    if (rect && next !== prev) {
      const cx = rect.width / 2;
      const cy = rect.height / 2;
      const factor = (next - prev) / Math.max(next, 1);
      setPosition((p) => clampPosition({ x: p.x - cx * factor, y: p.y - cy * factor }, next, rect));
    }
    setZoomLevel(next);
    if (next === 1) setIsZoomed(false);
  };

  const fitToView = () => {
    // For now, fit means reset to 1 and center
    handleZoomOut();
  };
  
  const handleWheel = (e) => {
    // Smooth trackpad/mouse wheel zoom; support pinch via ctrlKey
    const normalizeDeltaY = (event) => {
      let dy = event.deltaY;
      if (event.deltaMode === 1) dy *= 16; // lines -> pixels
      else if (event.deltaMode === 2) dy *= 100; // pages -> pixels
      return dy;
    };

    const dy = normalizeDeltaY(e);
    const isPinch = e.ctrlKey === true;

    if (!isZoomed && isPinch) {
      // Enter zoom mode on pinch gesture
      setIsZoomed(true);
      setZoomLevel(1.1);
    }

    if (!isZoomed) return;

    e.preventDefault();

    const prevZoom = zoomLevel;
    const sensitivity = isPinch ? 0.0030 : 0.0018;
    let nextZoom = prevZoom + (-dy * sensitivity);
    nextZoom = Math.max(1, Math.min(5, nextZoom));

    // Anchor zoom around cursor for better control
    const rect = imgRef.current ? imgRef.current.getBoundingClientRect() : null;
    if (rect && nextZoom !== prevZoom) {
      const cx = e.clientX - rect.left - rect.width / 2;
      const cy = e.clientY - rect.top - rect.height / 2;
      const factor = (nextZoom - prevZoom) / nextZoom;
      setPosition((p) => clampPosition({ x: p.x - cx * factor, y: p.y - cy * factor }, nextZoom, rect));
    }

    setZoomLevel(nextZoom);

    if (nextZoom === 1) {
      setIsZoomed(false);
      setPosition({ x: 0, y: 0 });
    }
  };
  
  const handleMouseDown = (e) => {
    if (isZoomed && zoomLevel > 1) {
      setIsDragging(true);
      setDragStart({ x: e.clientX - position.x, y: e.clientY - position.y });
    }
  };
  
  const handleMouseMove = (e) => {
    if (isDragging) {
      const rect = imgRef.current ? imgRef.current.getBoundingClientRect() : null;
      const newPos = { x: e.clientX - dragStart.x, y: e.clientY - dragStart.y };
      setPosition(clampPosition(newPos, zoomLevel, rect));
    }
  };
  
  const handleMouseUp = () => {
    setIsDragging(false);
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
      setIsDragging(true);
      setDragStart({ x: e.touches[0].clientX - position.x, y: e.touches[0].clientY - position.y });
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
    } else if (isDragging && e.touches.length === 1) {
      const rect = imgRef.current ? imgRef.current.getBoundingClientRect() : null;
      const newPos = { x: e.touches[0].clientX - dragStart.x, y: e.touches[0].clientY - dragStart.y };
      setPosition(clampPosition(newPos, zoomLevel, rect));
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
        <div className="zoom-hint">Click to zoom</div>
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

  const predefinedFeatures = [
    'rookie', 'autograph', 'jersey', 'parallel', 'refractor', 'chrome',
    'limited edition', 'serial numbered', 'prospect', 'hall of fame', 'insert', 'short print'
  ];

  const allFeatures = [...new Set([...predefinedFeatures, ...availableFeatures])];

  const handleFeatureToggle = (feature) => {
    const newSelected = selectedFeatures.includes(feature)
      ? selectedFeatures.filter(f => f !== feature)
      : [...selectedFeatures, feature];
    
    setSelectedFeatures(newSelected);
    onChange(newSelected.length === 0 ? 'none' : newSelected.join(','));
  };

  const addCustomFeature = () => {
    if (customFeature.trim() && !selectedFeatures.includes(customFeature.trim())) {
      const newSelected = [...selectedFeatures, customFeature.trim()];
      setSelectedFeatures(newSelected);
      onChange(newSelected.join(','));
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

function App({ onNavigate }) {
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

  useEffect(() => {
    fetchPendingCards();
    fetchFieldOptions();

    // Poll for newly processed cards every 10 seconds
    const pollInterval = setInterval(() => {
      // Only poll if not currently processing an action
      if (!processing && !reprocessing) {
        fetchPendingCards();
      }
    }, 10000);

    return () => clearInterval(pollInterval);
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
        }
        setIsEditing(true);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingCards, currentIndex, currentCardIndex, verificationMode]);

  const fetchFieldOptions = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/field-options');
      const data = await response.json();
      setFieldOptions(data);
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
        const result = await response.json();
        if (result.team) {
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
          lookupTeamForCard(card, index);
        }
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing, editedData.length]);

  const fetchPendingCards = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/pending-cards');
      const data = await response.json();
      console.log('[fetchPendingCards] Loaded', data.length, 'pending images. Cards per image:', data.map(d => d.data?.length || 0));
      setPendingCards(data);
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
      const data = await response.json();
      if (data.suggestions && data.suggestions.length > 0) {
        setCardSuggestions(prev => ({ ...prev, [cardIndex]: data.suggestions }));
        setShowSuggestions(prev => ({ ...prev, [cardIndex]: true }));
      } else {
        setCardSuggestions(prev => ({ ...prev, [cardIndex]: [] }));
        setShowSuggestions(prev => ({ ...prev, [cardIndex]: false }));
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
      is_player_card: suggestion.is_player_card !== undefined ? suggestion.is_player_card : newData[cardIndex].is_player_card
    };
    setEditedData(newData);
    setShowSuggestions(prev => ({ ...prev, [cardIndex]: false }));
    // Trigger auto-save
    setTimeout(() => autoSaveProgress(newData), 500);
  };

  const handleAction = async (action, mode = null) => {
    if (pendingCards.length === 0) return;

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
        await response.json();

        // Re-fetch pending cards from server to ensure sync
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
            const newIndex = currentIndex >= freshData.length ? Math.max(0, freshData.length - 1) : currentIndex;
            setCurrentIndex(newIndex);
            setCurrentCardIndex(0);
            setIsEditing(false);
            setEditedData([]);
          }
        }
      } else {
        const errorResult = await response.json();
        alert(`Error processing card: ${errorResult.error}`);
      }
    } catch (error) {
      console.error('Error processing action:', error);
      alert('Error processing card');
    }
    
    setProcessing(false);
  };

  const autoSaveProgress = async (dataToSave = null) => {
    if (pendingCards.length === 0) return;

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
        const result = await response.json();
        setLastSaved(new Date(result.timestamp));
        
        // Update the current card's data in the local state
        const updatedCards = [...pendingCards];
        updatedCards[currentIndex] = {
          ...currentCard,
          data: saveData
        };
        setPendingCards(updatedCards);
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
    // Convert text fields to lowercase for consistency (include name)
    const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
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
        });
      }, 500);
    }
  };

  const addNewCard = () => {
    const newCard = {
      name: '',
      sport: '',
      brand: '',
      number: '',
      copyright_year: '',
      team: '',
      is_player_card: true,
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
      
      const result = await response.json();
      
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
        alert(`Re-processing failed: ${result.error}\n\nDetails: ${result.details || 'No additional details'}`);
      }
    } catch (error) {
      console.error('Error re-processing card:', error);
      alert('Error re-processing card');
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
          onClick={() => onNavigate('main')}
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
      <header className="App-header">
        <div className="header-top">
          <h1>trading card verification</h1>
          <button 
            className="back-button" 
            onClick={() => onNavigate('main')}
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
              disabled={isEditing}
            >
              <option value="entire">Entire Photo</option>
              <option value="single">Single Card</option>
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
          <div className="main-image-block">
            <div className="main-image-title">Original Scan</div>
            <ZoomableImage
              src={`http://localhost:3001/api/bulk-back-image/${currentCard.imageFile}`}
              alt="Trading card"
              className="card-image"
            />
          </div>

          {/* Paired view: show cropped back and matched front for fast verification */}
          {verificationMode === 'single' && currentCard?.data?.length > 0 && (
            (() => {
              const sel = currentCard.data[Math.min(currentCardIndex, currentCard.data.length - 1)] || {};
              const stem = (currentCard.imageFile || '').replace(/\.[^.]+$/, '');
              // Build cropped back filename: stem_posN_Name_Number.png
              const pos = sel?._grid_metadata?.position ?? sel?.grid_position ?? currentCardIndex;
              const cardName = (sel?.name || 'unknown').replace(/\s+/g, '_');
              const cardNumber = sel?.number || 'no_num';
              const croppedFilename = `${stem}_pos${pos}_${cardName}_${cardNumber}.png`;
              const backCropUrl = `http://localhost:3001/api/cropped-back-image/${croppedFilename}`;
              const frontFile = sel?.matched_front_file; // filename under cards/unprocessed_single_front
              const frontUrl = frontFile
                ? `http://localhost:3001/api/front-image/${frontFile}`
                : null;
              if (!backCropUrl && !frontUrl) return null;
              return (
                <div className="paired-images">
                  {backCropUrl && (
                    <div className="paired-image-block">
                      <div className="paired-image-title">Back (cropped)</div>
                      <ZoomableImage 
                        src={backCropUrl}
                        alt="Card back (cropped)"
                        className="card-image"
                      />
                    </div>
                  )}
                  {frontUrl && (
                    <div className="paired-image-block">
                      <div className="paired-image-title">Front (matched)</div>
                      <ZoomableImage 
                        src={frontUrl}
                        alt="Card front (matched)"
                        className="card-image"
                      />
                    </div>
                  )}
                </div>
              );
            })()
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
              {autoSaving && <span className="saving">Saving...</span>}
              {!autoSaving && lastSaved && (
                <span className="saved">
                  Saved {new Date(lastSaved).toLocaleTimeString()}
                </span>
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
                        <input
                          type="text"
                          value={card.name}
                          onChange={(e) => updateCardField(index, 'name', e.target.value)}
                          onFocus={() => {
                            if (cardSuggestions[index]?.length > 0) {
                              setShowSuggestions(prev => ({ ...prev, [index]: true }));
                            }
                          }}
                        />
                      </div>
                      {showSuggestions[index] && cardSuggestions[index]?.length > 0 && (
                        <div className="suggestions-container" style={{
                          backgroundColor: '#2a2a2a',
                          border: '1px solid #444',
                          borderRadius: '4px',
                          marginBottom: '10px',
                          maxHeight: '150px',
                          overflowY: 'auto'
                        }}>
                          <div style={{
                            padding: '5px 10px',
                            borderBottom: '1px solid #444',
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center'
                          }}>
                            <span style={{ fontSize: '11px', color: '#888' }}>
                              Matching cards from database ({cardSuggestions[index].length})
                            </span>
                            <button
                              onClick={() => setShowSuggestions(prev => ({ ...prev, [index]: false }))}
                              style={{
                                background: 'none',
                                border: 'none',
                                color: '#888',
                                cursor: 'pointer',
                                fontSize: '12px'
                              }}
                            >
                              hide
                            </button>
                          </div>
                          {cardSuggestions[index].map((suggestion, sIdx) => (
                            <div
                              key={sIdx}
                              onClick={() => applySuggestion(index, suggestion)}
                              style={{
                                padding: '8px 10px',
                                borderBottom: '1px solid #333',
                                cursor: 'pointer',
                                fontSize: '12px'
                              }}
                              onMouseEnter={(e) => e.target.style.backgroundColor = '#3a3a3a'}
                              onMouseLeave={(e) => e.target.style.backgroundColor = 'transparent'}
                            >
                              <strong>{suggestion.name}</strong> - {suggestion.brand} #{suggestion.number} ({suggestion.copyright_year})
                              {suggestion.team && suggestion.team !== 'unknown' && ` - ${suggestion.team}`}
                            </div>
                          ))}
                        </div>
                      )}
                      <div className="field-group">
                        <label><strong>{formatFieldName('sport')}:</strong></label>
                        <input 
                          type="text" 
                          value={card.sport} 
                          onChange={(e) => updateCardField(index, 'sport', e.target.value)}
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('brand')}:</strong></label>
                        <input 
                          type="text" 
                          value={card.brand} 
                          onChange={(e) => updateCardField(index, 'brand', e.target.value)}
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('number')}:</strong></label>
                        <input 
                          type="text" 
                          value={card.number} 
                          onChange={(e) => updateCardField(index, 'number', e.target.value)}
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
                        <input 
                          type="text" 
                          value={card.team} 
                          onChange={(e) => updateCardField(index, 'team', e.target.value)}
                        />
                      </div>
                      <div className="field-group">
                        <label><strong>{formatFieldName('is_player_card')}:</strong></label>
                        <select 
                          value={card.is_player_card} 
                          onChange={(e) => updateCardField(index, 'is_player_card', e.target.value === 'true')}
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
                        <input 
                          type="text" 
                          value={card.card_set} 
                          onChange={(e) => updateCardField(index, 'card_set', e.target.value)}
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
                        <strong>{formatFieldName('is_player_card')}:</strong> 
                        <span>{formatFieldValue('is_player_card', card.is_player_card)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.is_player_card} fieldName="is_player_card" />
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
          {verificationMode === 'single' && currentCard.data.length > 1 && (
            <>
              <button
                onClick={() => {
                  setIsEditing(false);
                  setCurrentCardIndex(Math.max(0, currentCardIndex - 1));
                }}
                disabled={currentCardIndex === 0 || reprocessing}
                className="nav-button"
              >
                ← Previous Card
              </button>
              <button
                onClick={() => {
                  setIsEditing(false);
                  setCurrentCardIndex(Math.min(currentCard.data.length - 1, currentCardIndex + 1));
                }}
                disabled={currentCardIndex === currentCard.data.length - 1 || reprocessing}
                className="nav-button"
              >
                Next Card →
              </button>
            </>
          )}

          <button
            onClick={goToPrevious}
            disabled={currentIndex === 0 || reprocessing}
            className="nav-button"
          >
            ← Previous Photo
          </button>
          <button
            onClick={goToNext}
            disabled={currentIndex === pendingCards.length - 1 || reprocessing}
            className="nav-button"
          >
            Next Photo →
          </button>
        </div>

        <div className="action-buttons">
          {verificationMode === 'single' ? (
            <>
              <div className="action-group">
                <span className="action-label">Card:</span>
                <button
                  onClick={() => handleAction('fail')}
                  disabled={processing || reprocessing}
                  className="fail-button"
                >
                  {processing ? '...' : 'Fail Card'}
                </button>
                <button
                  onClick={() => handleAction('pass')}
                  disabled={processing || reprocessing}
                  className="pass-button"
                >
                  {processing ? '...' : 'Pass Card'}
                </button>
              </div>
              <div className="action-group">
                <span className="action-label">Image:</span>
                <button
                  onClick={() => handleAction('fail', 'entire')}
                  disabled={processing || reprocessing}
                  className="fail-button"
                >
                  {processing ? '...' : 'Fail All'}
                </button>
                <button
                  onClick={() => handleAction('pass', 'entire')}
                  disabled={processing || reprocessing}
                  className="pass-button"
                >
                  {processing ? '...' : 'Pass All'}
                </button>
              </div>
            </>
          ) : (
            <>
              <button
                onClick={() => handleAction('fail')}
                disabled={processing || reprocessing}
                className="fail-button"
              >
                {processing ? 'Processing...' : 'Fail All'}
              </button>
              <button
                onClick={() => handleAction('pass')}
                disabled={processing || reprocessing}
                className="pass-button"
              >
                {processing ? 'Processing...' : 'Pass All'}
              </button>
            </>
          )}
        </div>
        
        <div className="system-controls">
          <button 
            onClick={() => onNavigate && onNavigate('logs')}
            className="system-log-button"
            title="View system logs for debugging"
          >
            system logs
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
