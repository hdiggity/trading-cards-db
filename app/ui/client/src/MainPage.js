import React, { useState, useEffect } from 'react';
import './MainPage.css';
import UploadDropZone from './UploadDropZone';

function MainPage({ onNavigate }) {
  const [stats, setStats] = useState({
    total_cards: 0,
    total_quantity: 0,
    unique_players: 0,
    unique_years: 0,
    unique_brands: 0,
    unique_sports: 0,
    total_value: 0,
    years_summary: [],
    brands_summary: [],
    sports_summary: []
  });
  const [pendingCount, setPendingCount] = useState(0);
  const [rawScanCount, setRawScanCount] = useState(0);
  const [processCount, setProcessCount] = useState('');
  const [processing, setProcessing] = useState(false);
  const [bgProcessing, setBgProcessing] = useState(false);
  const [bgProgress, setBgProgress] = useState(0);
  const [bgCurrentFile, setBgCurrentFile] = useState('');
  const [bgCurrent, setBgCurrent] = useState(0);
  const [bgTotal, setBgTotal] = useState(0);
  const [bgLogFile, setBgLogFile] = useState(null); // eslint-disable-line no-unused-vars
  const [bgSubstep, setBgSubstep] = useState('');
  const [rawStart, setRawStart] = useState(0);
  const [pendingStart, setPendingStart] = useState(0); // eslint-disable-line no-unused-vars
  const rawStartRef = React.useRef(0);

  useEffect(() => {
    fetchStats();
    fetchPendingCount();
    fetchRawScanCount();
    // Detect background processing if page reloads mid-run
    (async () => {
      try {
        const r = await fetch('http://localhost:3001/api/processing-status');
        const s = await r.json();
        if (s.active) {
          setBgProcessing(true);
          setBgLogFile(s.logFile || null);
          if (typeof s.progress === 'number') setBgProgress(s.progress);
          else setBgProgress(10);
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


  const handleProcessRawScans = async () => {
    if (rawScanCount === 0) {
      alert('No raw scans found to process. Please add images to the cards/unprocessed_bulk_back/ directory.');
      return;
    }

    const countToProcess = processCount ? parseInt(processCount, 10) : null;

    setProcessing(true);
    try {
      const response = await fetch('http://localhost:3001/api/process-raw-scans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ count: countToProcess })
      });
      const result = await response.json();
      if (response.ok) {
        setBgProcessing(true);
        setBgProgress(8);
        setBgLogFile(result.logFile || null);
        const startRaw = rawScanCount || (await fetchRawScanCount()) || 1;
        rawStartRef.current = startRaw;
        setRawStart(startRaw);
        setPendingStart(pendingCount);
        // Poll for progress updates
        const start = Date.now();
        setBgTotal(result.count || rawScanCount);
        const poll = async () => {
          await fetchPendingCount();
          await fetchRawScanCount();
          // Check server process status with real-time progress
          let active = true;
          let serverProgress = null;
          let currentFile = '';
          let current = 0;
          let total = 0;
          let substep = '';
          try {
            const rs = await fetch('/api/processing-status');
            const st = await rs.json();
            active = !!st.active;
            if (typeof st.progress === 'number') serverProgress = st.progress;
            if (st.currentFile) currentFile = st.currentFile;
            if (typeof st.current === 'number') current = st.current;
            if (typeof st.total === 'number') total = st.total;
            if (st.substep) substep = st.substepDetail ? `${st.substep}: ${st.substepDetail}` : st.substep;
          } catch {}

          // Update progress from server
          if (serverProgress !== null) {
            setBgProgress(serverProgress);
          }
          setBgCurrentFile(currentFile);
          setBgCurrent(current);
          setBgSubstep(substep);
          if (total > 0) setBgTotal(total);

          const longTimeout = Date.now() - start >= 60 * 60 * 1000; // 60 min safety cap

          if (active && !longTimeout) {
            setTimeout(poll, 2000); // Poll every 2 seconds for smoother updates
          } else {
            // Process ended
            setBgProcessing(false);
            setBgProgress(100);
            setBgCurrentFile('');
            setBgSubstep('');
            fetchRawScanCount(); // Refresh count
            fetchPendingCount();
          }
        };
        setTimeout(poll, 1000);
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
      setBgProgress((cur) => Math.max(cur, pct));
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
          <div className="top-progress-title">
            {bgTotal > 0 ? (
              <>Processing {bgCurrent} of {bgTotal} ({bgProgress}%)</>
            ) : (
              <>Processing raw scans… {bgProgress}%</>
            )}
          </div>
          {(bgCurrentFile || bgSubstep) && (
            <div className="top-progress-file">
              {bgCurrentFile}{bgCurrentFile && bgSubstep ? ' — ' : ''}{bgSubstep}
            </div>
          )}
          <div className="top-progress-actions">
            <button 
              className="cancel-processing"
              type="button"
              onClick={async () => {
                try {
                  const r = await fetch('http://localhost:3001/api/cancel-processing', { method: 'POST' });
                  if (!r.ok) throw new Error('request failed');
                } catch (e) {
                  console.error('cancel failed', e);
                }
                setBgProcessing(false);
                setProcessing(false);
              }}
              title="Cancel background processing"
            >
              cancel
            </button>
          </div>
          <div className="progress-track top">
            <div className="progress-bar" style={{ width: `${bgProgress}%` }} />
          </div>
        </div>
      </div>
      <header className="main-header">
        <h1>trading cards database</h1>
      </header>

      <div className="stats-section">
        <h2>collection totals</h2>
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-number">{stats.total_cards}</div>
            <div className="stat-label">cards</div>
          </div>
          <div className="stat-card hoverable">
            <div className="stat-number">{stats.unique_years}</div>
            <div className="stat-label">years</div>
            {Array.isArray(stats.years_summary) && stats.years_summary.length > 0 && (
              <div className="hover-preview" role="tooltip" aria-label="top years">
                <div className="hover-title">top years</div>
                <ul>
                  {stats.years_summary.map((y, idx) => (
                    <li key={idx}>
                      <span className="hover-key">{y.year}</span>
                      <span className="hover-dot" />
                      <span className="hover-value">{y.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div className="stat-card hoverable">
            <div className="stat-number">{stats.unique_brands}</div>
            <div className="stat-label">brands</div>
            {Array.isArray(stats.brands_summary) && stats.brands_summary.length > 0 && (
              <div className="hover-preview" role="tooltip" aria-label="top brands">
                <div className="hover-title">top brands</div>
                <ul>
                  {stats.brands_summary.map((b, idx) => (
                    <li key={idx}>
                      <span className="hover-key">{b.brand || 'unknown'}</span>
                      <span className="hover-dot" />
                      <span className="hover-value">{b.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div className="stat-card hoverable">
            <div className="stat-number">{stats.unique_sports}</div>
            <div className="stat-label">sports</div>
            {Array.isArray(stats.sports_summary) && stats.sports_summary.length > 0 && (
              <div className="hover-preview" role="tooltip" aria-label="top sports">
                <div className="hover-title">top sports</div>
                <ul>
                  {stats.sports_summary.map((s, idx) => (
                    <li key={idx}>
                      <span className="hover-key">{s.sport || 'unknown'}</span>
                      <span className="hover-dot" />
                      <span className="hover-value">{s.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <div className="stat-card">
            <div className="stat-number">{stats.total_quantity}</div>
            <div className="stat-label">total quantity</div>
          </div>
          <div className="stat-card">
            <div className="stat-number">${stats.total_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
            <div className="stat-label">total value</div>
          </div>
        </div>
      </div>

      <div className="actions-section">
        <h2>actions</h2>
        <div className="action-buttons">
          <div className="process-section">
            <div className="process-header">
              <h3>process scans</h3>
              <span className="process-available">{rawScanCount} available (oldest first)</span>
            </div>
            <div className="process-quick-select">
              {[1, 5, 10, 25].map(n => (
                <button
                  key={n}
                  className={`quick-btn ${processCount === String(n) ? 'active' : ''}`}
                  onClick={() => setProcessCount(String(n))}
                  disabled={rawScanCount < n || processing || bgProcessing}
                >
                  {n}
                </button>
              ))}
              <button
                className={`quick-btn ${processCount === '' ? 'active' : ''}`}
                onClick={() => setProcessCount('')}
                disabled={rawScanCount === 0 || processing || bgProcessing}
              >
                all
              </button>
              <input
                type="number"
                className="process-count-input"
                placeholder="custom"
                min="1"
                max={rawScanCount}
                value={processCount}
                onChange={(e) => setProcessCount(e.target.value)}
                disabled={rawScanCount === 0 || processing || bgProcessing}
              />
            </div>
            <div className="process-actions">
              <button
                className="process-main-btn"
                onClick={handleProcessRawScans}
                disabled={rawScanCount === 0 || processing || bgProcessing}
              >
                {(processing || bgProcessing) ? (
                  <>processing... <div className="spinner-sm" /></>
                ) : (
                  <>start processing {processCount || rawScanCount} image{(processCount || rawScanCount) !== '1' && (processCount || rawScanCount) !== 1 ? 's' : ''}</>
                )}
              </button>
              <button
                className="process-preview-btn"
                type="button"
                onClick={() => onNavigate('raw-preview')}
                disabled={rawScanCount === 0}
              >
                preview
              </button>
            </div>
          </div>

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

      <div className="upload-section">
        <h2>upload photos</h2>
        <UploadDropZone onUploadComplete={handleUploadComplete} />
      </div>
      {/* Old inline banner removed in favor of top drop-down */}


    </div>
  );
}

export default MainPage;
