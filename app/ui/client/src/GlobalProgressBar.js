import React, { useState, useEffect } from 'react';
import './MainPage.css'; // Use same styles as MainPage

function GlobalProgressBar() {
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

          pollTimeout = setTimeout(pollProcessingStatus, 1500);
        } else if (bgProcessing) {
          setBgProcessing(false);
          setBgProgress(100);
          setTimeout(() => {
            setBgProgress(0);
            setBgCurrentFile('');
            setBgSubstep('');
          }, 2000);
          pollTimeout = setTimeout(pollProcessingStatus, 5000);
        } else {
          pollTimeout = setTimeout(pollProcessingStatus, 5000);
        }
      } catch (error) {
        if (!cancelled) {
          pollTimeout = setTimeout(pollProcessingStatus, 5000);
        }
      }
    };

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

  return (
    <div
      className={`top-progress ${bgProcessing ? 'show' : ''}`}
      role="status"
      aria-live="polite"
    >
      <div className="top-progress-inner">
        <div className="top-progress-info">
          <div className="top-progress-title">
            <span className="progress-spinner"></span>
            {bgTotal > 0 ? (
              <>PROCESSING {Math.min(bgCurrent + 1, bgTotal)} OF {bgTotal}</>
            ) : (
              <>PROCESSING</>
            )}
          </div>
          <div className="top-progress-file">
            {bgCurrentFile || bgSubstep ? (
              <>{bgCurrentFile}{bgSubstep ? ` · ${bgSubstep}` : ''}</>
            ) : '\u00A0'}
          </div>
        </div>
        <div className="top-progress-percent">{bgProgress}%</div>
        <div className="top-progress-actions">
          <button
            className="cancel-processing"
            type="button"
            onClick={handleCancel}
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
  );
}

export default GlobalProgressBar;
