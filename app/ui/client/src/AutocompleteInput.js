import React, { useState, useRef } from 'react';

// Autocomplete input component with real-time suggestions from database
function AutocompleteInput({ field, value, onChange, placeholder, className }) {
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
    } catch (error) {
      console.error('Error fetching autocomplete suggestions:', error);
    }
    setLoading(false);
  };

  const handleInputChange = (e) => {
    const newValue = e.target.value;
    onChange(newValue);

    // Debounce autocomplete requests (300ms)
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    timeoutRef.current = setTimeout(() => {
      fetchSuggestions(newValue);
    }, 300);
  };

  const handleSuggestionClick = (suggestion) => {
    onChange(suggestion);
    setShowSuggestions(false);
    setSuggestions([]);
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
          {suggestions.map((suggestion, idx) => (
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
              {suggestion}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default AutocompleteInput;
