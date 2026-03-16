import React, { useState, useRef } from 'react';
import apiBase from './utils/apiBase';
import './StorageUpload.css';

function StorageUpload({ onAddedToPending }) {
  const [state, setState] = useState('idle'); // idle | analyzing | done | error
  const [recommendations, setRecommendations] = useState('');
  const [savedFile, setSavedFile] = useState(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [addedToPending, setAddedToPending] = useState(false);
  const fileInputRef = useRef(null);

  const analyze = async (file) => {
    setState('analyzing');
    setRecommendations('');
    setErrorMsg('');
    setAddedToPending(false);

    const formData = new FormData();
    formData.append('image', file);

    try {
      const response = await fetch(`${apiBase}/api/storage-analysis`, {
        method: 'POST',
        body: formData,
      });
      const result = await response.json();
      if (!response.ok) {
        setErrorMsg(result.error || 'Analysis failed');
        setState('error');
        return;
      }
      setRecommendations(result.recommendations);
      setSavedFile(result.file);
      setState('done');
    } catch (err) {
      setErrorMsg(`Analysis failed: ${err.message}`);
      setState('error');
    }
  };

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    e.target.value = '';
    analyze(file);
  };

  const handleRedo = () => {
    fileInputRef.current?.click();
  };

  const handleAddToPending = async () => {
    if (!savedFile) return;
    try {
      const response = await fetch(`${apiBase}/api/storage-add-to-pending`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file: savedFile }),
      });
      const result = await response.json();
      if (!response.ok) {
        setErrorMsg(result.error || 'Failed to add to pending');
        return;
      }
      setAddedToPending(true);
      if (onAddedToPending) onAddedToPending();
    } catch (err) {
      setErrorMsg(`Failed: ${err.message}`);
    }
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
        <button
          className="action-button storage"
          onClick={() => fileInputRef.current?.click()}
        >
          <div className="button-content">
            <h3>UPLOAD + STORAGE</h3>
          </div>
        </button>
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
              <button className="storage-action-btn" onClick={handleRedo}>
                REDO
              </button>
              {state === 'done' && !addedToPending && (
                <button className="storage-action-btn primary" onClick={handleAddToPending}>
                  ADD TO PENDING PROCESSING
                </button>
              )}
              {addedToPending && (
                <span className="storage-added-label">ADDED TO PENDING</span>
              )}
              <button
                className="storage-action-btn"
                onClick={() => { setState('idle'); setSavedFile(null); setAddedToPending(false); }}
              >
                CLOSE
              </button>
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
