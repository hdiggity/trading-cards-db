import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './MainPage.css';
import UploadDropZone from './UploadDropZone';

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
      </header>

      <div className="stats-section">
        <h2>COLLECTION TOTALS</h2>
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-number">{stats.total_cards}</div>
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
            <div className="stat-number">{stats.total_quantity}</div>
            <div className="stat-label">TOTAL QUANTITY</div>
          </div>
          <div className="stat-card">
            <div className="stat-number">${stats.total_value?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
            <div className="stat-label">TOTAL VALUE</div>
          </div>
        </div>
      </div>

      <div className="actions-section">
        <h2>ACTIONS</h2>
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
            className="action-button logs"
            onClick={() => navigate('/logs')}
          >
            <div className="button-content">
              <h3>SYSTEM LOGS</h3>
            </div>
          </button>

          {/* Upload history removed for streamlined UI */}
        </div>
      </div>

      <div className="upload-section">
        <h2>UPLOAD PHOTOS</h2>
        <UploadDropZone onUploadComplete={handleUploadComplete} />
      </div>

      {/* System status section at bottom */}
      <div className="system-status-section">
        <div className="status-card">
          <div className="status-header">
            <h3>SYSTEM STATUS</h3>
            <span className={`status-badge ${systemHealth?.status || 'unknown'}`}>
              {systemHealth?.status === 'healthy' ? '● HEALTHY' :
               systemHealth?.status === 'degraded' ? '● DEGRADED' :
               systemHealth?.status === 'error' ? '● ERROR' : '● UNKNOWN'}
            </span>
          </div>
          <div className="status-checks">
            <div className="status-check" title={systemHealth?.checks?.database?.message || ''}>
              <span className="status-check-label">DATABASE</span>
              <span className={`status-check-value ${systemHealth?.checks?.database?.status || 'unknown'}`}>
                {systemHealth?.checks?.database?.status === 'healthy' ? '✓ HEALTHY' :
                 systemHealth?.checks?.database?.status === 'warning' ? '⚠ WARNING' :
                 systemHealth?.checks?.database?.status === 'error' ? '✗ ERROR' : '- UNKNOWN'}
              </span>
              {systemHealth?.checks?.database?.message && (
                <span className="status-detail">{systemHealth.checks.database.message}</span>
              )}
            </div>
            <div className="status-check" title={systemHealth?.checks?.openai_config?.message || ''}>
              <span className="status-check-label">OPENAI API</span>
              <span className={`status-check-value ${systemHealth?.checks?.openai_config?.status || 'unknown'}`}>
                {systemHealth?.checks?.openai_config?.status === 'healthy' ? '✓ CONFIGURED' :
                 systemHealth?.checks?.openai_config?.status === 'error' ? '✗ ERROR' : '- UNKNOWN'}
              </span>
              {systemHealth?.checks?.openai_config?.message && (
                <span className="status-detail">{systemHealth.checks.openai_config.message}</span>
              )}
            </div>
            <div className="status-check" title={systemHealth?.checks?.directories?.message || ''}>
              <span className="status-check-label">FILESYSTEM</span>
              <span className={`status-check-value ${systemHealth?.checks?.directories?.status || 'unknown'}`}>
                {systemHealth?.checks?.directories?.status === 'healthy' ? '✓ HEALTHY' :
                 systemHealth?.checks?.directories?.status === 'warning' ? '⚠ WARNING' :
                 systemHealth?.checks?.directories?.status === 'error' ? '✗ ERROR' : '- UNKNOWN'}
              </span>
              {systemHealth?.checks?.directories?.message && (
                <span className="status-detail">{systemHealth.checks.directories.message}</span>
              )}
            </div>
            <div className="status-check" title={systemHealth?.checks?.python?.message || ''}>
              <span className="status-check-label">PYTHON</span>
              <span className={`status-check-value ${systemHealth?.checks?.python?.status || 'unknown'}`}>
                {systemHealth?.checks?.python?.status === 'healthy' ? `✓ ${systemHealth?.checks?.python?.version || 'HEALTHY'}` :
                 systemHealth?.checks?.python?.status === 'error' ? '✗ ERROR' : '- UNKNOWN'}
              </span>
            </div>
          </div>
        </div>

        {/* Recent activity feed */}
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

    </div>
  );
}

export default MainPage;
