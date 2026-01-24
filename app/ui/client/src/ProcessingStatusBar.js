import React, { useState, useEffect } from 'react';

// Global processing status bar component - shows on all pages
function ProcessingStatusBar() {
  const [bgProcessing, setBgProcessing] = useState(false);
  const [bgProgress, setBgProgress] = useState(0);
  const [bgCurrentFile, setBgCurrentFile] = useState('');
  const [bgCurrent, setBgCurrent] = useState(0);
  const [bgTotal, setBgTotal] = useState(0);
  const [bgSubstep, setBgSubstep] = useState('');

  useEffect(() => {
    let cancelled = false;
    let pollTimeout = null;

    const pollProcessingStatus = async () => {
      if (cancelled) return;

      try {
        const response = await fetch('http://localhost:3001/api/processing-status');
        const status = await response.json();

        if (status.active) {
          setBgProcessing(true);
          if (typeof status.progress === 'number') setBgProgress(status.progress);
          if (status.currentFile) setBgCurrentFile(status.currentFile);
          if (typeof status.current === 'number') setBgCurrent(status.current);
          if (typeof status.total === 'number') setBgTotal(status.total);
          if (status.substep) setBgSubstep(status.substepDetail ? `${status.substep}: ${status.substepDetail}` : status.substep);

          // Continue polling while active
          pollTimeout = setTimeout(pollProcessingStatus, 1500);
        } else if (bgProcessing) {
          // Processing just finished
          setBgProcessing(false);
          setBgProgress(100);
          // Reset progress after a moment
          setTimeout(() => {
            setBgProgress(0);
            setBgCurrentFile('');
            setBgSubstep('');
          }, 2000);
          // Poll less frequently when not active
          pollTimeout = setTimeout(pollProcessingStatus, 5000);
        } else {
          // Not processing, poll less frequently
          pollTimeout = setTimeout(pollProcessingStatus, 5000);
        }
      } catch (error) {
        // On error, continue polling less frequently
        if (!cancelled) {
          pollTimeout = setTimeout(pollProcessingStatus, 5000);
        }
      }
    };

    // Start polling
    pollProcessingStatus();

    return () => {
      cancelled = true;
      if (pollTimeout) clearTimeout(pollTimeout);
    };
  }, [bgProcessing]);

  const handleCancel = async () => {
    try {
      await fetch('http://localhost:3001/api/cancel-processing', { method: 'POST' });
    } catch (e) {
      console.error('cancel failed', e);
    }
    setBgProcessing(false);
  };

  if (!bgProcessing) return null;

  return (
    <div className="global-progress-bar" role="status" aria-live="polite" style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 10000,
      background: 'linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%)',
      color: 'white',
      padding: '8px 16px',
      boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
      display: 'flex',
      alignItems: 'center',
      gap: '16px',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      fontSize: '13px'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span className="progress-spinner" style={{
          display: 'inline-block',
          width: '14px',
          height: '14px',
          border: '2px solid rgba(255,255,255,0.3)',
          borderTopColor: 'white',
          borderRadius: '50%',
          animation: 'spin 1s linear infinite'
        }} />
        <strong>
          {bgTotal > 0 ? (
            <>PROCESSING {Math.min(bgCurrent + 1, bgTotal)} OF {bgTotal}</>
          ) : (
            <>PROCESSING</>
          )}
        </strong>
      </div>
      <div style={{ flex: 1, opacity: 0.9, fontSize: '12px' }}>
        {bgCurrentFile || bgSubstep ? (
          <>{bgCurrentFile}{bgSubstep ? ` · ${bgSubstep}` : ''}</>
        ) : '\u00A0'}
      </div>
      <div style={{ fontWeight: 'bold', minWidth: '40px', textAlign: 'right' }}>
        {bgProgress}%
      </div>
      <button
        onClick={handleCancel}
        style={{
          background: 'rgba(255,255,255,0.2)',
          border: '1px solid rgba(255,255,255,0.3)',
          color: 'white',
          padding: '4px 12px',
          borderRadius: '4px',
          cursor: 'pointer',
          fontSize: '11px',
          fontWeight: 'bold'
        }}
        title="Cancel processing"
      >
        CANCEL
      </button>
      <div style={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        height: '3px',
        background: 'rgba(255,255,255,0.2)'
      }}>
        <div style={{
          width: `${bgProgress}%`,
          height: '100%',
          background: '#4ade80',
          transition: 'width 0.3s ease'
        }} />
      </div>
      <style>{`
        @keyframes spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}

export default ProcessingStatusBar;
