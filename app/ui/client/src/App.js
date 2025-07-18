import React, { useState, useEffect } from 'react';
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
    'notes': 'Notes'
  };
  return fieldMap[fieldName] || fieldName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
};

// Utility function to format field values for display
const formatFieldValue = (fieldName, value) => {
  if (value === null || value === undefined) return 'N/A';
  
  switch (fieldName) {
    case 'is_player_card':
      return value ? 'Yes' : 'No';
    case 'features':
      return value === 'none' || !value ? 'None' : value;
    default:
      return value || 'N/A';
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

// TCDB Verification display component
function TCDBVerification({ tcdbData, card }) {
  if (!tcdbData || !tcdbData.verified) {
    return (
      <div className="tcdb-verification">
        <h4>🔍 TCDB Verification</h4>
        <p style={{ color: '#dc2626', fontSize: '0.875rem' }}>
          {tcdbData?.error ? `${tcdbData.error}` : 'No matches found in TCDB'}
        </p>
      </div>
    );
  }

  const { best_match, results, enhanced_fields } = tcdbData;
  
  return (
    <div className="tcdb-verification">
      <h4>✅ TCDB Verification</h4>
      
      {/* Show enhanced fields */}
      {enhanced_fields && enhanced_fields.length > 0 && (
        <div className="tcdb-enhancements">
          <p style={{ color: '#059669', fontSize: '0.875rem', fontWeight: '500' }}>
            ✨ Enhanced from TCDB: {enhanced_fields.join(', ')}
          </p>
        </div>
      )}
      
      {/* Show year discrepancy warning */}
      {card._year_discrepancy && (
        <div className="tcdb-warning">
          <p style={{ color: '#d97706', fontSize: '0.875rem', fontWeight: '500' }}>
            ⚠️ Year mismatch: Extracted {card._year_discrepancy.extracted}, TCDB shows {card._year_discrepancy.tcdb}
          </p>
          <p style={{ color: '#6b7280', fontSize: '0.8125rem' }}>
            {card._year_discrepancy.note}
          </p>
        </div>
      )}
      
      <div className="tcdb-best-match">
        <h5>Best Match:</h5>
        <div className="tcdb-match-card">
          <a href={best_match.tcdb_url} target="_blank" rel="noopener noreferrer" className="tcdb-link">
            <strong>{best_match.title}</strong>
          </a>
          <div className="tcdb-match-details">
            <span>Set: {best_match.set}</span>
            {best_match.year && <span> • Year: {best_match.year}</span>}
            {best_match.team && <span> • Team: {best_match.team}</span>}
          </div>
        </div>
      </div>
      
      {results.length > 1 && (
        <details className="tcdb-all-matches">
          <summary>View all {results.length} matches</summary>
          <div className="tcdb-matches-list">
            {results.slice(1).map((match, index) => (
              <div key={index} className="tcdb-match-item">
                <a href={match.tcdb_url} target="_blank" rel="noopener noreferrer" className="tcdb-link">
                  {match.title}
                </a>
                <div className="tcdb-match-details">
                  <span>{match.set}</span>
                  {match.year && <span> • {match.year}</span>}
                  {match.team && <span> • {match.team}</span>}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

// Zoomable image component
function ZoomableImage({ src, alt, className }) {
  const [isZoomed, setIsZoomed] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  
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
  
  const handleWheel = (e) => {
    if (isZoomed) {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.2 : 0.2;
      const newZoom = Math.max(1, Math.min(5, zoomLevel + delta));
      setZoomLevel(newZoom);
      
      if (newZoom === 1) {
        setIsZoomed(false);
        setPosition({ x: 0, y: 0 });
      }
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
      setPosition({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y
      });
    }
  };
  
  const handleMouseUp = () => {
    setIsDragging(false);
  };
  
  return (
    <div className="zoomable-image-container">
      <img 
        src={src}
        alt={alt}
        className={`${className} ${isZoomed ? 'zoomed' : ''}`}
        style={{
          transform: `scale(${zoomLevel}) translate(${position.x / zoomLevel}px, ${position.y / zoomLevel}px)`,
          cursor: isZoomed ? (isDragging ? 'grabbing' : 'grab') : 'zoom-in'
        }}
        onClick={handleImageClick}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      />
      {isZoomed && (
        <div className="zoom-controls">
          <button onClick={() => setZoomLevel(Math.min(5, zoomLevel + 0.5))}>+</button>
          <span>{Math.round(zoomLevel * 100)}%</span>
          <button onClick={() => setZoomLevel(Math.max(1, zoomLevel - 0.5))}>-</button>
          <button onClick={handleZoomOut}>Reset</button>
        </div>
      )}
      {!isZoomed && (
        <div className="zoom-hint">Click to zoom, wheel to zoom in/out when zoomed</div>
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
            <span>{feature}</span>
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
  const [isEditing, setIsEditing] = useState(false);
  const [editedData, setEditedData] = useState([]);
  const [lastSaved, setLastSaved] = useState(null);
  const [autoSaving, setAutoSaving] = useState(false);
  const [fieldOptions, setFieldOptions] = useState(null);
  const [verificationMode, setVerificationMode] = useState('entire'); // 'entire' or 'single'
  const [currentCardIndex, setCurrentCardIndex] = useState(0);

  useEffect(() => {
    fetchPendingCards();
    fetchFieldOptions();
  }, []);

  const fetchFieldOptions = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/field-options');
      const data = await response.json();
      setFieldOptions(data);
    } catch (error) {
      console.error('Error fetching field options:', error);
    }
  };

  const fetchPendingCards = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/pending-cards');
      const data = await response.json();
      setPendingCards(data);
      setLoading(false);
    } catch (error) {
      console.error('Error fetching pending cards:', error);
      setLoading(false);
    }
  };

  const handleAction = async (action) => {
    if (pendingCards.length === 0) return;
    
    setProcessing(true);
    const currentCard = pendingCards[currentIndex];
    
    try {
      let endpoint, requestBody;
      
      if (verificationMode === 'single') {
        // Single card verification
        const modifiedCardData = isEditing ? editedData[currentCardIndex] : currentCard.data[currentCardIndex];
        endpoint = `http://localhost:3001/api/${action}-card/${currentCard.id}/${currentCardIndex}`;
        requestBody = action === 'pass' && isEditing ? { modifiedData: modifiedCardData } : {};
      } else {
        // Entire photo verification
        endpoint = `http://localhost:3001/api/${action}/${currentCard.id}`;
        requestBody = action === 'pass' && isEditing ? { modifiedData: editedData } : {};
      }
      
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(requestBody),
      });
      
      if (response.ok) {
        const result = await response.json();
        
        if (verificationMode === 'single' && result.remainingCards > 0) {
          // Update the current card data and reset to first card if we removed one
          const updatedCards = [...pendingCards];
          updatedCards[currentIndex].data.splice(currentCardIndex, 1);
          setPendingCards(updatedCards);
          
          // Reset to first card if current index is out of bounds
          if (currentCardIndex >= updatedCards[currentIndex].data.length) {
            setCurrentCardIndex(0);
          }
          
          alert(result.message);
        } else {
          // Remove the entire card entry or move to next
          const newCards = pendingCards.filter((_, index) => index !== currentIndex);
          setPendingCards(newCards);
          
          // Adjust current index if necessary
          if (currentIndex >= newCards.length) {
            setCurrentIndex(Math.max(0, newCards.length - 1));
          }
          
          setCurrentCardIndex(0);
          alert(result.message || 'Card processed successfully');
        }
        
        // Reset edit state
        setIsEditing(false);
        setEditedData([]);
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

  const startEditing = () => {
    const currentCard = pendingCards[currentIndex];
    
    if (verificationMode === 'single') {
      // Edit only the current card
      const processedCard = { ...currentCard.data[currentCardIndex] };
      const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
      textFields.forEach(field => {
        if (processedCard[field] && typeof processedCard[field] === 'string') {
          processedCard[field] = processedCard[field].toLowerCase();
        }
      });
      setEditedData([processedCard]);
    } else {
      // Edit all cards
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
  };

  const cancelEditing = () => {
    setIsEditing(false);
    setEditedData([]);
    setLastSaved(null);
  };

  const autoSaveProgress = async (dataToSave = null) => {
    if (pendingCards.length === 0) return;
    
    const currentCard = pendingCards[currentIndex];
    const saveData = dataToSave || editedData;
    
    if (saveData.length === 0) return;
    
    setAutoSaving(true);
    
    try {
      const response = await fetch(`http://localhost:3001/api/save-progress/${currentCard.id}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ data: saveData }),
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
    // Convert text fields to lowercase for consistency
    const textFields = ['name', 'sport', 'brand', 'team', 'card_set'];
    const processedValue = textFields.includes(field) && typeof value === 'string' 
      ? value.toLowerCase() 
      : value;
    newData[cardIndex] = { ...newData[cardIndex], [field]: processedValue };
    setEditedData(newData);
    
    // Auto-save with debouncing (save 2 seconds after last edit)
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
      is_player_card: true,
      features: 'none',
      condition: 'near_mint',
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

  const handleReprocess = async () => {
    if (pendingCards.length === 0) return;
    
    setReprocessing(true);
    const currentCard = pendingCards[currentIndex];
    
    try {
      const response = await fetch(`http://localhost:3001/api/reprocess/${currentCard.id}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
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

  const goToPrevious = () => {
    if (isEditing || reprocessing) {
      alert('Please save or cancel your edits first');
      return;
    }
    setCurrentIndex(Math.max(0, currentIndex - 1));
  };

  const goToNext = () => {
    if (isEditing || reprocessing) {
      alert('Please save or cancel your edits first');
      return;
    }
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
      <header className="App-header">
        <div className="header-top">
          <h1>Trading Card Verification</h1>
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
        {isEditing && <p className="edit-mode">EDIT MODE</p>}
      </header>

      <div className="card-container">
        <div className="image-section">
          <ZoomableImage 
            src={`http://localhost:3001/images/pending_verification/${currentCard.imageFile}`}
            alt="Trading card"
            className="card-image"
          />
        </div>

        <div className="data-section">
          <h3>Extracted Card Data:</h3>
          {!isEditing && (
            <div className="top-controls">
              <button onClick={startEditing} className="edit-button">
                Edit Data
              </button>
              <button 
                onClick={handleReprocess} 
                className="reprocess-button"
                disabled={reprocessing}
              >
                {reprocessing ? 'Re-processing...' : 'Re-process'}
              </button>
            </div>
          )}
          
          {isEditing && (
            <div className="edit-controls-top">
              <button onClick={addNewCard} className="add-card-button">
                + Add Card
              </button>
              <div className="save-status">
                {autoSaving && <span className="saving">Saving...</span>}
                {!autoSaving && lastSaved && (
                  <span className="saved">
                    Saved {new Date(lastSaved).toLocaleTimeString()}
                  </span>
                )}
                {!autoSaving && !lastSaved && isEditing && (
                  <span className="unsaved">Unsaved changes</span>
                )}
              </div>
            </div>
          )}
          
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
                        />
                      </div>
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
                          <option value={true}>Yes</option>
                          <option value={false}>No</option>
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
                          value={card.condition} 
                          onChange={(e) => updateCardField(index, 'condition', e.target.value)}
                        >
                          <option value="gem_mint">Gem Mint (10)</option>
                          <option value="mint">Mint (9)</option>
                          <option value="near_mint">Near Mint (8)</option>
                          <option value="excellent">Excellent (7)</option>
                          <option value="very_good">Very Good (6)</option>
                          <option value="good">Good (5)</option>
                          <option value="fair">Fair (4)</option>
                          <option value="poor">Poor (3)</option>
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
                        <span>{formatFieldValue('features', card.features)}</span>
                        <ConfidenceIndicator confidence={card._confidence?.features} fieldName="features" />
                      </p>
                    </>
                  )}
                </div>
                
                {/* TCDB Verification Section */}
                {card._tcdb_verification && (
                  <TCDBVerification tcdbData={card._tcdb_verification} card={card} />
                )}
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
                onClick={() => setCurrentCardIndex(Math.max(0, currentCardIndex - 1))} 
                disabled={currentCardIndex === 0 || isEditing || reprocessing}
                className="nav-button"
              >
                ← Previous Card
              </button>
              <button 
                onClick={() => setCurrentCardIndex(Math.min(currentCard.data.length - 1, currentCardIndex + 1))} 
                disabled={currentCardIndex === currentCard.data.length - 1 || isEditing || reprocessing}
                className="nav-button"
              >
                Next Card →
              </button>
            </>
          )}
          
          <button 
            onClick={goToPrevious} 
            disabled={currentIndex === 0 || isEditing || reprocessing}
            className="nav-button"
          >
            ← Previous Photo
          </button>
          <button 
            onClick={goToNext} 
            disabled={currentIndex === pendingCards.length - 1 || isEditing || reprocessing}
            className="nav-button"
          >
            Next Photo →
          </button>
        </div>

        {isEditing ? (
          <div className="edit-controls">
            <button 
              onClick={cancelEditing}
              className="cancel-button"
            >
              Cancel
            </button>
            <button 
              onClick={() => handleAction('fail')}
              disabled={processing || reprocessing}
              className="fail-button"
            >
              {processing ? 'Processing...' : 'Fail'}
            </button>
            <button 
              onClick={() => handleAction('pass')}
              disabled={processing || reprocessing}
              className="pass-button"
            >
              {processing ? 'Processing...' : 'Save & Pass'}
            </button>
          </div>
        ) : (
          <div className="action-buttons">
            <button 
              onClick={() => handleAction('fail')}
              disabled={processing || reprocessing}
              className="fail-button"
            >
              {processing ? 'Processing...' : 'Fail'}
            </button>
            <button 
              onClick={() => handleAction('pass')}
              disabled={processing || reprocessing}
              className="pass-button"
            >
              {processing ? 'Processing...' : 'Pass'}
            </button>
          </div>
        )}
        
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
