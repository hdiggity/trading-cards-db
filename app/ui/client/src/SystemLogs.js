import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import apiBase from './utils/apiBase';
import './SystemLogs.css';

function SystemLogs() {
  const navigate = useNavigate();
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedLog, setSelectedLog] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [totals, setTotals] = useState(null);

  useEffect(() => {
    fetchLogs();
  }, []);

  useEffect(() => {
    let interval;
    if (autoRefresh) {
      interval = setInterval(fetchLogs, 5000);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [autoRefresh]);

  const fetchLogs = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${apiBase}/api/system-logs`);

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      setLogs(data.logs || []);
      setTotals(data.totals || null);
      setError(null);
    } catch (err) {
      console.error('Error fetching logs:', err);
      setError(`FAILED TO FETCH LOGS: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const formatTimestamp = (timestamp) => {
    try {
      return new Date(timestamp).toLocaleString();
    } catch {
      return timestamp || 'UNKNOWN TIME';
    }
  };

  const getLogLevelIcon = (level) => {
    switch (level?.toLowerCase()) {
      case 'error': return 'ERR';
      case 'warn': case 'warning': return 'WRN';
      case 'info': return 'INF';
      case 'debug': return 'DBG';
      case 'success': return 'SUC';
      default: return 'LOG';
    }
  };

  const getLogLevelClass = (level) => {
    switch (level?.toLowerCase()) {
      case 'error': return 'log-error';
      case 'warn': case 'warning': return 'log-warning';
      case 'info': return 'log-info';
      case 'debug': return 'log-debug';
      case 'success': return 'log-success';
      default: return 'log-default';
    }
  };

  const copyLogToClipboard = (log) => {
    const logText = `[${formatTimestamp(log.timestamp)}] ${log.level}: ${log.message}\n${log.details || ''}`;
    navigator.clipboard.writeText(logText);
  };

  const exportAllLogs = () => {
    const allLogsText = logs.map(log =>
      `[${formatTimestamp(log.timestamp)}] ${log.level}: ${log.message}\n${log.details || ''}\n---`
    ).join('\n');

    const blob = new Blob([allLogsText], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `system-logs-${new Date().toISOString().split('T')[0]}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  if (loading && logs.length === 0) {
    return (
      <div className="system-logs">
        <div className="logs-header">
          <h2>SYSTEM LOGS</h2>
          <button onClick={() => navigate('/')} className="back-button">
            ← BACK
          </button>
        </div>
        <div className="loading">LOADING SYSTEM LOGS...</div>
      </div>
    );
  }

  return (
    <div className="system-logs">
      <div className="logs-header">
        <h2>SYSTEM LOGS</h2>
        <div className="logs-controls">
          <label>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            AUTO-REFRESH (5S)
          </label>
          <button onClick={fetchLogs} disabled={loading}>
            {loading ? 'REFRESHING...' : 'REFRESH'}
          </button>
          <button onClick={exportAllLogs} disabled={logs.length === 0}>
            EXPORT ALL
          </button>
          <button onClick={() => navigate('/')} className="back-button">
            ← BACK
          </button>
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <strong>ERROR:</strong> {error}
        </div>
      )}

      <div className="logs-content">
        <div className="logs-stats">
          <div className="stats-item">
            <span className="stats-label">TOTAL LOGS:</span>
            <span className="stats-value">{logs.length}</span>
          </div>
          {totals && (
            <>
              <div className="stats-item">
                <span className="stats-label">UPLOADS IN DB:</span>
                <span className="stats-value">{totals.uploadsTotal}</span>
              </div>
              <div className="stats-item">
                <span className="stats-label">VERIFIED:</span>
                <span className="stats-value">{totals.uploadsVerified}</span>
              </div>
              <div className="stats-item">
                <span className="stats-label">PENDING:</span>
                <span className="stats-value">{totals.uploadsPending}</span>
              </div>
            </>
          )}
          <div className="stats-item">
            <span className="stats-label">ERRORS:</span>
            <span className="stats-value error-count">
              {logs.filter(log => log.level?.toLowerCase() === 'error').length}
            </span>
          </div>
          <div className="stats-item">
            <span className="stats-label">WARNINGS:</span>
            <span className="stats-value warning-count">
              {logs.filter(log => log.level?.toLowerCase() === 'warning' || log.level?.toLowerCase() === 'warn').length}
            </span>
          </div>
        </div>

        {logs.length === 0 ? (
          <div className="no-logs">
            <p>NO SYSTEM LOGS FOUND.</p>
            <p>LOGS WILL APPEAR HERE WHEN THE SYSTEM PROCESSES CARDS OR ENCOUNTERS ERRORS.</p>
          </div>
        ) : (
          <div className="logs-list">
            {logs.map((log, index) => (
              <div
                key={index}
                className={`log-entry ${getLogLevelClass(log.level)} ${selectedLog === index ? 'selected' : ''}`}
                onClick={() => setSelectedLog(selectedLog === index ? null : index)}
              >
                <div className="log-header">
                  <span className="log-icon">{getLogLevelIcon(log.level)}</span>
                  <span className="log-level">{(log.level || 'INFO').toUpperCase()}</span>
                  <span className="log-timestamp">{formatTimestamp(log.timestamp)}</span>
                  <button
                    className="copy-log-button"
                    onClick={(e) => {
                      e.stopPropagation();
                      copyLogToClipboard(log);
                    }}
                    title="COPY LOG TO CLIPBOARD"
                  >
                    COPY
                  </button>
                </div>
                <div className="log-message">{log.message}</div>
                {selectedLog === index && log.details && (
                  <div className="log-details">
                    <strong>DETAILS:</strong>
                    <pre>{log.details}</pre>
                  </div>
                )}
                {selectedLog === index && log.stackTrace && (
                  <div className="log-stack-trace">
                    <strong>STACK TRACE:</strong>
                    <pre>{log.stackTrace}</pre>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="logs-help">
        <h3>HOW TO USE SYSTEM LOGS</h3>
        <ul>
          <li><strong>DEBUGGING:</strong> COPY ERROR LOGS AND PASTE THEM WHEN REPORTING ISSUES</li>
          <li><strong>PROCESSING:</strong> CHECK LOGS WHEN CARD PROCESSING FAILS</li>
          <li><strong>MONITORING:</strong> WATCH FOR WARNINGS ABOUT SLOW OPERATIONS OR API ISSUES</li>
          <li><strong>EXPORT:</strong> USE "EXPORT ALL" TO SAVE LOGS FOR ANALYSIS</li>
        </ul>
      </div>
    </div>
  );
}

export default SystemLogs;
