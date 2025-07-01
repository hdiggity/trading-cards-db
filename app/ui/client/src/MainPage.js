import React, { useState, useEffect } from 'react';
import './MainPage.css';
import UploadDropZone from './UploadDropZone';

function MainPage({ onNavigate }) {
  const [stats, setStats] = useState({
    total_cards: 0,
    total_quantity: 0,
    unique_players: 0,
    unique_years: 0,
    unique_brands: 0
  });
  const [pendingCount, setPendingCount] = useState(0);
  const [rawScanCount, setRawScanCount] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [learningInsights, setLearningInsights] = useState(null);

  useEffect(() => {
    fetchStats();
    fetchPendingCount();
    fetchRawScanCount();
    fetchLearningInsights();
  }, []);

  const fetchStats = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/database-stats');
      const data = await response.json();
      setStats(data);
    } catch (error) {
      console.error('Error fetching stats:', error);
    }
  };

  const fetchPendingCount = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/pending-cards');
      const data = await response.json();
      setPendingCount(data.length);
    } catch (error) {
      console.error('Error fetching pending count:', error);
    }
  };

  const fetchRawScanCount = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/raw-scan-count');
      const data = await response.json();
      setRawScanCount(data.count);
    } catch (error) {
      console.error('Error fetching raw scan count:', error);
    }
  };

  const fetchLearningInsights = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/learning-insights');
      const data = await response.json();
      setLearningInsights(data);
    } catch (error) {
      console.error('Error fetching learning insights:', error);
    }
  };

  const handleProcessRawScans = async () => {
    if (rawScanCount === 0) {
      alert('No raw scans found to process. Please add images to the images/raw_scans/ directory.');
      return;
    }

    setProcessing(true);
    try {
      const response = await fetch('http://localhost:3001/api/process-raw-scans', {
        method: 'POST'
      });
      
      const result = await response.json();
      
      if (response.ok) {
        alert(`Processing completed successfully!\n\n${result.output}`);
        // Refresh counts after processing
        fetchPendingCount();
        fetchRawScanCount();
      } else {
        alert(`Processing failed: ${result.error}\n\nDetails: ${result.details || 'No additional details'}`);
      }
    } catch (error) {
      console.error('Error processing raw scans:', error);
      alert('Error triggering raw scan processing');
    }
    setProcessing(false);
  };

  const handleUploadComplete = (fileCount) => {
    // Refresh raw scan count after upload
    fetchRawScanCount();
  };

  return (
    <div className="main-page">
      <header className="main-header">
        <h1>Trading Cards Database</h1>
      </header>

      <div className="stats-section">
        <h2>Collection</h2>
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-number">{stats.total_cards}</div>
            <div className="stat-label">cards</div>
          </div>
          <div className="stat-card">
            <div className="stat-number">{stats.unique_years}</div>
            <div className="stat-label">years</div>
          </div>
          <div className="stat-card">
            <div className="stat-number">{stats.unique_brands}</div>
            <div className="stat-label">brands</div>
          </div>
          <div className="stat-card">
            <div className="stat-number">{stats.total_quantity}</div>
            <div className="stat-label">quantity</div>
          </div>
        </div>
      </div>

      <div className="upload-section">
        <h2>Upload Photos</h2>
        <UploadDropZone onUploadComplete={handleUploadComplete} />
      </div>

      <div className="actions-section">
        <h2>Actions</h2>
        <div className="action-buttons">
          <button 
            className="action-button process"
            onClick={handleProcessRawScans}
            disabled={rawScanCount === 0 || processing}
          >
            <div className="button-content">
              <h3>process raw scans {rawScanCount > 0 && `(${rawScanCount})`}</h3>
            </div>
          </button>

          <button 
            className="action-button verify"
            onClick={() => onNavigate('verify')}
            disabled={pendingCount === 0}
          >
            <div className="button-content">
              <h3>verify cards {pendingCount > 0 && `(${pendingCount})`}</h3>
            </div>
          </button>

          <button 
            className="action-button database"
            onClick={() => onNavigate('database')}
          >
            <div className="button-content">
              <h3>browse database</h3>
            </div>
          </button>

          <button 
            className="action-button logs"
            onClick={() => onNavigate('logs')}
          >
            <div className="button-content">
              <h3>system logs</h3>
            </div>
          </button>

          <button 
            className="action-button upload-history"
            onClick={() => onNavigate('upload-history')}
          >
            <div className="button-content">
              <h3>upload history</h3>
            </div>
          </button>
        </div>
      </div>

      {learningInsights && learningInsights.total_corrections > 0 && (
        <div className="learning-section">
          <h2>AI Learning Progress</h2>
          <div className="learning-stats">
            <div className="learning-stat">
              <div className="stat-number">{learningInsights.total_corrections}</div>
              <div className="stat-label">user corrections learned</div>
            </div>
            <div className="learning-improvements">
              <h3>recent improvements:</h3>
              <ul>
                {learningInsights.year_corrections?.length > 0 && (
                  <li>improved copyright year detection accuracy</li>
                )}
                {learningInsights.name_corrections?.length > 0 && (
                  <li>better player name identification</li>
                )}
                {learningInsights.condition_corrections?.length > 0 && (
                  <li>more accurate condition assessment</li>
                )}
                {learningInsights.features_patterns?.length > 0 && (
                  <li>enhanced feature recognition</li>
                )}
                {Object.keys(learningInsights.brand_specific_issues || {}).length > 0 && (
                  <li>brand-specific accuracy improvements</li>
                )}
              </ul>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

export default MainPage;