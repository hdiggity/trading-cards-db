import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './MainPage.css';

function MainPage() {
  const navigate = useNavigate();
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
  const [systemHealth, setSystemHealth] = useState(null);
  const [recentActivity, setRecentActivity] = useState([]);
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
  const fileInputRef = React.useRef(null);

  useEffect(() => {
    const loadData = async () => {
      try {
        await Promise.all([
          fetchStats(),
          fetchPendingCount(),
          fetchRawScanCount(),
          fetchSystemHealth(),
          fetchRecentActivity()
        ]);
      } catch (error) {
        console.error('Error loading main page data:', error);
      }

      // Detect background processing if page reloads mid-run
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
      } catch (error) {
        console.error('Error checking processing status:', error);
      }
    };

    loadData();
  }, []);

  const fetchStats = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/database-stats');
      if (!response.ok) throw new Error(`Stats fetch failed: ${response.status}`);
      const data = await response.json();
      setStats(data);
      console.log('[MainPage] Loaded stats:', data);
    } catch (error) {
      console.error('Error fetching stats:', error);
    }
  };

  const fetchPendingCount = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/pending-cards');
      if (!response.ok) throw new Error(`Pending cards fetch failed: ${response.status}`);
      const data = await response.json();
      setPendingCount(data.length);
      console.log('[MainPage] Loaded pending count:', data.length);
      return data.length;
    } catch (error) {
      console.error('Error fetching pending count:', error);
      setPendingCount(0);
      return 0;
    }
  };

  const fetchRawScanCount = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/raw-scan-count');
      if (!response.ok) throw new Error(`Raw scan count fetch failed: ${response.status}`);
      const data = await response.json();
      setRawScanCount(data.count);
      console.log('[MainPage] Loaded raw scan count:', data.count);
      return data.count;
    } catch (error) {
      console.error('Error fetching raw scan count:', error);
      return rawScanCount;
    }
  };

  const fetchSystemHealth = async () => {
    try {
      const response = await fetch('http://localhost:3001/health');
      if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
      const data = await response.json();
      setSystemHealth(data);
      console.log('[MainPage] Loaded system health:', data);
    } catch (error) {
      console.error('Error fetching system health:', error);
      setSystemHealth({ status: 'error', checks: {} });
    }
  };

  const fetchRecentActivity = async () => {
    try {
      const response = await fetch('http://localhost:3001/api/recent-activity?limit=10');
      if (!response.ok) throw new Error(`Recent activity fetch failed: ${response.status}`);
      const data = await response.json();
      setRecentActivity(data.activity || []);
      console.log('[MainPage] Loaded recent activity:', data.activity?.length || 0, 'items');
    } catch (error) {
      console.error('Error fetching recent activity:', error);
      setRecentActivity([]);
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
          // Check server process status with real-time progress
          let active = true;
          let serverProgress = null;
          let currentFile = '';
          let current = 0;
          let total = 0;
          let substep = '';
          try {
            const rs = await fetch('http://localhost:3001/api/processing-status');
            const st = await rs.json();
            active = !!st.active;
            if (typeof st.progress === 'number') serverProgress = st.progress;
            if (st.currentFile) currentFile = st.currentFile;
            if (typeof st.current === 'number') current = st.current;
            if (typeof st.total === 'number') total = st.total;
            if (st.substep) substep = st.substepDetail ? `${st.substep}: ${st.substepDetail}` : st.substep;
          } catch {}

          // Update progress from server (prefer server-reported progress)
          if (serverProgress !== null) {
            setBgProgress(serverProgress);
          }
          setBgCurrentFile(currentFile);
          setBgCurrent(current);
          setBgSubstep(substep);
          if (total > 0) setBgTotal(total);

          // Refresh counts less frequently to reduce overhead
          if (current % 3 === 0 || !active) {
            await fetchPendingCount();
            await fetchRawScanCount();
          }

          const longTimeout = Date.now() - start >= 60 * 60 * 1000; // 60 min safety cap

          if (active && !longTimeout) {
            setTimeout(poll, 1500); // Poll every 1.5 seconds for smoother updates
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

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelect = async (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;

    try {
      const formData = new FormData();
      files.forEach(file => formData.append('images', file));

      const response = await fetch('http://localhost:3001/api/upload', {
        method: 'POST',
        body: formData
      });

      if (response.ok) {
        const result = await response.json();
        alert(`Successfully uploaded ${result.count} image(s)`);
        fetchRawScanCount();
        e.target.value = ''; // Reset input
      } else {
        const error = await response.json();
        alert(`Upload failed: ${error.error || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Upload error:', error);
      alert('Upload failed. Check console for details.');
    }
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
              <>PROCESSING {bgCurrent} OF {bgTotal} ({bgProgress}%)</>
            ) : (
              <>PROCESSING RAW SCANS... {bgProgress}%</>
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
              CANCEL
            </button>
          </div>
          <div className="progress-track top">
            <div className="progress-bar" style={{ width: `${bgProgress}%` }} />
          </div>
        </div>
      </div>
      <header className="main-header">
        <h1>TRADING CARDS DATABASE</h1>

        {/* Collection totals banner */}
        <div className="stats-banner">
          <div className="stat-card">
            <div className="stat-number">{stats.total_quantity}</div>
            <div className="stat-label">CARDS</div>
          </div>
          <div className="stat-card hoverable">
            <div className="stat-number">{stats.unique_years}</div>
            <div className="stat-label">YEARS</div>
            {Array.isArray(stats.years_summary) && stats.years_summary.length > 0 && (
              <div className="hover-preview" role="tooltip" aria-label="TOP YEARS">
                <div className="hover-title">TOP YEARS</div>
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
            <div className="stat-label">BRANDS</div>
            {Array.isArray(stats.brands_summary) && stats.brands_summary.length > 0 && (
              <div className="hover-preview" role="tooltip" aria-label="TOP BRANDS">
                <div className="hover-title">TOP BRANDS</div>
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
            <div className="stat-label">SPORTS</div>
            {Array.isArray(stats.sports_summary) && stats.sports_summary.length > 0 && (
              <div className="hover-preview" role="tooltip" aria-label="TOP SPORTS">
                <div className="hover-title">TOP SPORTS</div>
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
            <div className="stat-number">${stats.total_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
            <div className="stat-label">TOTAL VALUE</div>
          </div>
        </div>
      </header>

      <div className="actions-section">
        <div className="action-buttons">
          <div className="process-section">
            <div className="process-header">
              <h3>PROCESS SCANS</h3>
              <span className="process-available">{rawScanCount} AVAILABLE (OLDEST FIRST)</span>
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
                ALL
              </button>
              <input
                type="number"
                className="process-count-input"
                placeholder="CUSTOM"
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
                  <>PROCESSING... <div className="spinner-sm" /></>
                ) : (
                  <>START PROCESSING {processCount || rawScanCount} IMAGE{(processCount || rawScanCount) !== '1' && (processCount || rawScanCount) !== 1 ? 'S' : ''}</>
                )}
              </button>
              <button
                className="process-preview-btn"
                type="button"
                onClick={() => navigate('/raw-preview')}
                disabled={rawScanCount === 0}
              >
                PREVIEW
              </button>
            </div>
          </div>

          <button
            className="action-button verify"
            onClick={() => navigate('/verification')}
            disabled={pendingCount === 0}
          >
            <div className="button-content">
              <h3>VERIFY CARDS {pendingCount > 0 && `(${pendingCount})`}</h3>
            </div>
          </button>

          <button
            className="action-button database"
            onClick={() => navigate('/database')}
          >
            <div className="button-content">
              <h3>BROWSE DATABASE</h3>
            </div>
          </button>

          <button
            className="action-button upload"
            onClick={handleUploadClick}
          >
            <div className="button-content">
              <h3>UPLOAD PHOTOS</h3>
            </div>
          </button>

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*,.heic,.heif"
            multiple
            style={{ display: 'none' }}
            onChange={handleFileSelect}
          />

          {/* Upload history removed for streamlined UI */}
        </div>
      </div>

      {/* Recent activity feed - centered */}
      <div className="recent-activity-section">
        <div className="activity-card">
          <h3>RECENT ACTIVITY</h3>
          {recentActivity.length > 0 ? (
            <div className="activity-list">
              {recentActivity.map((activity, idx) => (
                <div key={idx} className="activity-item">
                  <span className={`activity-action ${activity.action}`}>
                    {activity.action === 'pass' ? '✓' : activity.action === 'fail' ? '✗' : '↶'}
                  </span>
                  <span className="activity-description">
                    {activity.action === 'pass' ? 'PASSED' :
                     activity.action === 'fail' ? 'FAILED' :
                     activity.action === 'undo' ? 'UNDONE' : activity.action.toUpperCase()}
                    {activity.cardNumber ? ` #${activity.cardNumber}` : ''}
                    {activity.cardCount > 1 ? ` (${activity.cardCount} cards)` : ''}
                  </span>
                  <span className="activity-time">
                    {new Date(activity.timestamp).toLocaleString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      hour: 'numeric',
                      minute: '2-digit'
                    })}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="activity-empty">NO RECENT ACTIVITY</div>
          )}
        </div>
      </div>

      {/* System status button at bottom */}
      <div className="system-status-footer">
        <button
          className="system-status-button"
          onClick={() => navigate('/logs')}
          title="View system logs and status"
        >
          <span className={`status-indicator ${systemHealth?.status || 'unknown'}`}>
            {systemHealth?.status === 'healthy' ? '●' :
             systemHealth?.status === 'degraded' ? '●' :
             systemHealth?.status === 'error' ? '●' : '●'}
          </span>
          SYSTEM STATUS
        </button>
      </div>

    </div>
  );
}

export default MainPage;
