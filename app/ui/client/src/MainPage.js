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
  const [bgProcessing, setBgProcessing] = useState(false);
  const [bgProgress, setBgProgress] = useState(0);
  const [bgLogFile, setBgLogFile] = useState(null);
  const [rawStart, setRawStart] = useState(0);
  const [pendingStart, setPendingStart] = useState(0);
  const [learningInsights, setLearningInsights] = useState(null);
  const rawStartRef = React.useRef(0);

  useEffect(() => {
    fetchStats();
    fetchPendingCount();
    fetchRawScanCount();
    fetchLearningInsights();
    // Detect background processing if page reloads mid-run
    (async () => {
      try {
        const r = await fetch('http://localhost:3001/api/processing-status');
        const s = await r.json();
        if (s.active) {
          setBgProcessing(true);
          setBgLogFile(s.logFile || null);
          setBgProgress(10);
          // Seed baselines for progress approximation
          const base = (await fetchRawScanCount()) || 1;
          rawStartRef.current = base;
          setRawStart(prev => prev || base);
        }
      } catch {}
    })();
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
      return data.length;
    } catch (error) {
      console.error('Error fetching pending count:', error);
      return pendingCount;
    }
  };

  const fetchRawScanCount = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/raw-scan-count');
      const data = await response.json();
      setRawScanCount(data.count);
      return data.count;
    } catch (error) {
      console.error('Error fetching raw scan count:', error);
      return rawScanCount;
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
      const response = await fetch('http://localhost:3001/api/process-raw-scans', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
      const result = await response.json();
      if (response.ok) {
        setBgProcessing(true);
        setBgProgress(8);
        setBgLogFile(result.logFile || null);
        const startRaw = rawScanCount || (await fetchRawScanCount()) || 1;
        rawStartRef.current = startRaw;
        setRawStart(startRaw);
        setPendingStart(pendingCount);
        // Poll counts for progress for ~2 minutes or until raw scan count hits 0
        const start = Date.now();
        const poll = async () => {
          const _ = await fetchPendingCount();
          const currentRaw = await fetchRawScanCount();
          // Also check server process status
          let active = true;
          try {
            const rs = await fetch('http://localhost:3001/api/processing-status');
            const st = await rs.json();
            active = !!st.active;
          } catch {}

          // progress heuristic based on raw scans remaining
          const base = rawStartRef.current || rawStart || 1;
          const done = Math.max(0, base - currentRaw);
          const pctCount = Math.min(100, Math.max(10, Math.round((done / base) * 100)));

          // Time-based smoothing so single-file runs don’t appear stuck at 10%
          const elapsedSec = (Date.now() - start) / 1000;
          // Climb smoothly up to ~97% over ~15 minutes while active
          const pctTime = Math.min(97, 10 + Math.round((elapsedSec / 900) * 87));

          const pct = Math.max(pctCount, pctTime);
          setBgProgress(pct);

          const finished = currentRaw === 0;
          const longTimeout = Date.now() - start >= 30 * 60 * 1000; // 30 minutes safety cap

          if (!finished && active && !longTimeout) {
            setTimeout(poll, 4000);
          } else {
            // If process ended (either finished or inactive), finalize the UI
            setBgProcessing(false);
            setBgProgress(100);
          }
        };
        setTimeout(poll, 3000);
      } else {
        alert(`Processing failed to start: ${result.error}\n\nDetails: ${result.details || 'No additional details'}`);
      }
    } catch (error) {
      console.error('Error processing raw scans:', error);
      alert('Error triggering raw scan processing');
    }
    setProcessing(false);
  };

  // Update progress reactively as counts change
  useEffect(() => {
    if (!bgProcessing) return;
    if (rawStart > 0) {
      rawStartRef.current = rawStart;
      const done = Math.max(0, rawStart - rawScanCount);
      const pct = Math.min(100, Math.max(10, Math.round((done / rawStart) * 100)));
      setBgProgress(pct);
    }
    if (rawScanCount === 0 && bgProcessing) {
      setBgProcessing(false);
      setBgProgress(100);
    }
  }, [rawScanCount, bgProcessing, rawStart]);

  const handleUploadComplete = (fileCount) => {
    // Refresh raw scan count after upload
    fetchRawScanCount();
  };

  return (
    <div className="main-page">
      {/* Top drop-down progress bar */}
      <div 
        className={`top-progress ${bgProcessing ? 'show' : ''}`}
        role="status"
        aria-live="polite"
      >
        <div className="top-progress-inner">
          <div className="top-progress-title">Processing raw scans… {bgProgress}%</div>
          <div className="progress-track top">
            <div className="progress-bar" style={{ width: `${bgProgress}%` }} />
          </div>
        </div>
      </div>
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
            disabled={rawScanCount === 0 || processing || bgProcessing}
          >
            <div className="button-content">
              <h3>process raw scans {rawScanCount > 0 && `(${rawScanCount})`}</h3>
            </div>
            {(processing || bgProcessing) && <div className="spinner" />}
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

          {/* Upload history removed for streamlined UI */}
        </div>
      </div>
      {/* Old inline banner removed in favor of top drop-down */}

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
