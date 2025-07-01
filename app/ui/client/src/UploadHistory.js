import React, { useState, useEffect } from 'react';
import './UploadHistory.css';

function UploadHistory({ onNavigate }) {
  const [uploads, setUploads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchUploadHistory();
  }, []);

  const fetchUploadHistory = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/upload-history');
      if (response.ok) {
        const data = await response.json();
        setUploads(data.uploads || []);
      } else {
        setError('Failed to fetch upload history');
      }
    } catch (error) {
      console.error('Error fetching upload history:', error);
      setError('Error fetching upload history');
    }
    setLoading(false);
  };

  const formatTimestamp = (timestamp) => {
    return new Date(timestamp).toLocaleString();
  };

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed': return '#1a1a1a';
      case 'processing': return '#525252';
      case 'pending_verification': return '#737373';
      case 'failed': return '#737373';
      default: return '#a3a3a3';
    }
  };

  const getStatusLabel = (status) => {
    switch (status) {
      case 'completed': return 'completed';
      case 'processing': return 'processing';
      case 'pending_verification': return 'pending verification';
      case 'failed': return 'failed';
      default: return status || 'unknown';
    }
  };

  if (loading) {
    return (
      <div className="upload-history">
        <div className="loading">loading upload history...</div>
      </div>
    );
  }

  return (
    <div className="upload-history">
      <header className="upload-header">
        <div className="header-top">
          <h1>Upload History</h1>
          <button 
            className="back-button" 
            onClick={() => onNavigate('main')}
          >
            ← Back to Main
          </button>
        </div>
      </header>

      {error && (
        <div className="error-banner">
          {error}
        </div>
      )}

      <div className="upload-content">
        {uploads.length === 0 ? (
          <div className="no-uploads">
            <p>no upload history found</p>
            <p>process some raw scans to see upload history here</p>
          </div>
        ) : (
          <div className="uploads-list">
            {uploads.map((upload, index) => (
              <div key={index} className="upload-entry">
                <div className="upload-header-info">
                  <div className="upload-filename">{upload.filename}</div>
                  <div className="upload-timestamp">{formatTimestamp(upload.upload_timestamp)}</div>
                </div>
                
                <div className="upload-details">
                  <div className="upload-status">
                    <span 
                      className="status-label"
                      style={{ color: getStatusColor(upload.status) }}
                    >
                      {getStatusLabel(upload.status)}
                    </span>
                  </div>
                  
                  {upload.file_path && (
                    <div className="upload-path">
                      <strong>path:</strong> {upload.file_path}
                    </div>
                  )}
                  
                  {upload.error_message && (
                    <div className="upload-error">
                      <strong>error:</strong> {upload.error_message}
                    </div>
                  )}
                  
                  {upload.processing_notes && (
                    <div className="upload-notes">
                      <strong>notes:</strong> {upload.processing_notes}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default UploadHistory;