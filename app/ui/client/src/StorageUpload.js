import React, { useState, useRef } from 'react';
import apiBase from './utils/apiBase';
import './StorageUpload.css';

function StorageUpload({ onUploaded }) {
  const [state, setState] = useState('idle'); // idle | uploading | uploaded | analyzing | done | error
  const [recommendations, setRecommendations] = useState('');
  const [savedFilename, setSavedFilename] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const fileInputRef = useRef(null);

  const handleFileSelect = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    e.target.value = '';

    setState('uploading');
    setErrorMsg('');

    const formData = new FormData();
    formData.append('image', file);

    try {
      const response = await fetch(`${apiBase}/api/upload`, {
        method: 'POST',
        body: formData,
      });
      const result = await response.json();
      if (!response.ok) {
        setErrorMsg(result.error || 'Upload failed');
        setState('error');
        return;
      }
      setSavedFilename(result.filename);
      setState('uploaded');
      if (onUploaded) onUploaded();
    } catch (err) {
      setErrorMsg(`Upload failed: ${err.message}`);
      setState('error');
    }
  };

  const analyze = async () => {
    if (!savedFilename) return;
    setState('analyzing');
    setRecommendations('');
    setErrorMsg('');

    try {
      const response = await fetch(`${apiBase}/api/storage-analysis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: savedFilename }),
      });
      const result = await response.json();
      if (!response.ok) {
        setErrorMsg(result.error || 'Analysis failed');
        setState('error');
        return;
      }
      setRecommendations(result.recommendations);
      setState('done');
    } catch (err) {
      setErrorMsg(`Analysis failed: ${err.message}`);
      setState('error');
    }
  };

  const reset = () => {
    setState('idle');
    setSavedFilename(null);
    setRecommendations('');
    setErrorMsg('');
  };

  const renderRecommendations = (text) => {
    return text.split('\n').map((line, i) => {
      if (!line.trim()) return <div key={i} className="storage-spacer" />;
      const parts = line.split('|');
      if (parts.length >= 3) {
        return (
          <div key={i} className="storage-card-row">
            {parts.map((part, j) => {
              const trimmed = part.trim();
              const isStorage = trimmed.toLowerCase().startsWith('storage:');
              return (
                <span key={j} className={`storage-part${isStorage ? ' storage-highlight' : ''}`}>
                  {trimmed}
                </span>
              );
            })}
          </div>
        );
      }
      return <div key={i} className="storage-card-row">{line}</div>;
    });
  };

  return (
    <div className="storage-upload-container">
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*,.heic,.heif"
        style={{ display: 'none' }}
        onChange={handleFileSelect}
      />

      {state === 'idle' && (
        <button className="action-button storage" onClick={() => fileInputRef.current?.click()}>
          <div className="button-content">
            <h3>UPLOAD + STORAGE</h3>
          </div>
        </button>
      )}

      {state === 'uploading' && (
        <div className="storage-analyzing">
          <div className="storage-spinner" />
          <span>uploading...</span>
        </div>
      )}

      {state === 'uploaded' && (
        <div className="storage-results">
          <div className="storage-results-header">
            <span className="storage-results-title">UPLOADED</span>
            <div className="storage-results-actions">
              <button className="storage-action-btn primary" onClick={analyze}>
                GET STORAGE RECOMMENDATIONS
              </button>
              <button className="storage-action-btn" onClick={reset}>
                CLOSE
              </button>
            </div>
          </div>
          <div className="storage-recs-body">
            <div className="storage-card-row">{savedFilename} added to processing queue.</div>
          </div>
        </div>
      )}

      {state === 'analyzing' && (
        <div className="storage-analyzing">
          <div className="storage-spinner" />
          <span>analyzing cards...</span>
        </div>
      )}

      {(state === 'done' || state === 'error') && (
        <div className="storage-results">
          <div className="storage-results-header">
            <span className="storage-results-title">STORAGE RECOMMENDATIONS</span>
            <div className="storage-results-actions">
              <button className="storage-action-btn" onClick={analyze}>REDO</button>
              <button className="storage-action-btn" onClick={reset}>CLOSE</button>
            </div>
          </div>
          {state === 'error' ? (
            <div className="storage-error">{errorMsg}</div>
          ) : (
            <div className="storage-recs-body">
              {renderRecommendations(recommendations)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default StorageUpload;
