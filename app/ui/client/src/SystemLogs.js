import React, { useState, useEffect } from 'react';
import './SystemLogs.css';

function SystemLogs({ onNavigate }) {
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
      interval = setInterval(fetchLogs, 5000); // Refresh every 5 seconds
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [autoRefresh]);

  const fetchLogs = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/system-logs');
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      setLogs(data.logs || []);
      setTotals(data.totals || null);
      setError(null);
    } catch (err) {
      console.error('Error fetching logs:', err);
      setError(`Failed to fetch logs: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const formatTimestamp = (timestamp) => {
    try {
      return new Date(timestamp).toLocaleString();
    } catch {
      return timestamp || 'Unknown time';
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
    navigator.clipboard.writeText(logText).then(() => {
      alert('Log copied to clipboard');
    });
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
          <h2>system logs</h2>
          <button onClick={() => onNavigate('main')} className="back-button">
            ← Back to Main
          </button>
        </div>
        <div className="loading">Loading system logs...</div>
      </div>
    );
  }

  return (
    <div className="system-logs">
      <div className="logs-header">
        <h2>system logs</h2>
        <div className="logs-controls">
          <label>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto-refresh (5s)
          </label>
          <button onClick={fetchLogs} disabled={loading}>
            {loading ? 'Refreshing...' : 'Refresh'}
          </button>
          <button onClick={exportAllLogs} disabled={logs.length === 0}>
            Export All
          </button>
          <button onClick={() => onNavigate('main')} className="back-button">
            ← Back to Main
          </button>
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <strong>Error:</strong> {error}
        </div>
      )}

      <div className="logs-content">
        <div className="logs-stats">
          <div className="stats-item">
            <span className="stats-label">Total Logs:</span>
            <span className="stats-value">{logs.length}</span>
          </div>
          {totals && (
            <>
              <div className="stats-item">
                <span className="stats-label">Uploads in DB:</span>
                <span className="stats-value">{totals.uploadsTotal}</span>
              </div>
              <div className="stats-item">
                <span className="stats-label">Verified:</span>
                <span className="stats-value">{totals.uploadsVerified}</span>
              </div>
              <div className="stats-item">
                <span className="stats-label">Pending:</span>
                <span className="stats-value">{totals.uploadsPending}</span>
              </div>
            </>
          )}
          <div className="stats-item">
            <span className="stats-label">Errors:</span>
            <span className="stats-value error-count">
              {logs.filter(log => log.level?.toLowerCase() === 'error').length}
            </span>
          </div>
          <div className="stats-item">
            <span className="stats-label">Warnings:</span>
            <span className="stats-value warning-count">
              {logs.filter(log => log.level?.toLowerCase() === 'warning' || log.level?.toLowerCase() === 'warn').length}
            </span>
          </div>
        </div>

        {logs.length === 0 ? (
          <div className="no-logs">
            <p>No system logs found.</p>
            <p>Logs will appear here when the system processes cards or encounters errors.</p>
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
                    title="Copy log to clipboard"
                  >
                    Copy
                  </button>
                </div>
                <div className="log-message">{log.message}</div>
                {selectedLog === index && log.details && (
                  <div className="log-details">
                    <strong>Details:</strong>
                    <pre>{log.details}</pre>
                  </div>
                )}
                {selectedLog === index && log.stackTrace && (
                  <div className="log-stack-trace">
                    <strong>Stack Trace:</strong>
                    <pre>{log.stackTrace}</pre>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="logs-help">
        <h3>how to use system logs</h3>
        <ul>
          <li><strong>For Claude:</strong> Copy error logs and paste them when reporting issues for more accurate debugging</li>
          <li><strong>Debug Processing:</strong> Check logs when card processing fails to understand what went wrong</li>
          <li><strong>Monitor Performance:</strong> Watch for warnings about slow operations or API issues</li>
          <li><strong>Export Data:</strong> Use "Export All" to save logs for detailed analysis</li>
        </ul>
      </div>
    </div>
  );
}

export default SystemLogs;
