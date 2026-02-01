import React, { useState, useEffect } from 'react';
import './MainPage.css'; // Use same styles as MainPage

function GlobalProgressBar() {
  // Card processing state
  const [bgProcessing, setBgProcessing] = useState(false);
  const [bgProgress, setBgProgress] = useState(0);
  const [bgCurrentFile, setBgCurrentFile] = useState('');
  const [bgCurrent, setBgCurrent] = useState(0);
  const [bgTotal, setBgTotal] = useState(0);
  const [bgSubstep, setBgSubstep] = useState('');

  // Price refresh state
  const [priceRefreshing, setPriceRefreshing] = useState(false);
  const [priceProgress, setPriceProgress] = useState(0);
  const [priceCurrent, setPriceCurrent] = useState(0);
  const [priceTotal, setPriceTotal] = useState(0);
  const [priceUpdated, setPriceUpdated] = useState(0);

  // Poll for card processing status
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

          pollTimeout = setTimeout(pollProcessingStatus, 800);
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

  // Poll for price refresh status
  useEffect(() => {
    let cancelled = false;
    let pollTimeout = null;

    const pollPriceStatus = async () => {
      if (cancelled) return;

      try {
        const response = await fetch('http://localhost:3001/api/price-refresh-status');
        const status = await response.json();

        if (status.active) {
          setPriceRefreshing(true);
          if (typeof status.progress === 'number') setPriceProgress(status.progress);
          if (typeof status.current === 'number') setPriceCurrent(status.current);
          if (typeof status.total === 'number') setPriceTotal(status.total);
          if (typeof status.updated === 'number') setPriceUpdated(status.updated);

          pollTimeout = setTimeout(pollPriceStatus, 1000);
        } else if (priceRefreshing) {
          setPriceRefreshing(false);
          setPriceProgress(100);
          setTimeout(() => {
            setPriceProgress(0);
            setPriceCurrent(0);
            setPriceTotal(0);
          }, 2000);
          pollTimeout = setTimeout(pollPriceStatus, 5000);
        } else {
          pollTimeout = setTimeout(pollPriceStatus, 5000);
        }
      } catch (error) {
        if (!cancelled) {
          pollTimeout = setTimeout(pollPriceStatus, 5000);
        }
      }
    };

    pollPriceStatus();

    return () => {
      cancelled = true;
      if (pollTimeout) clearTimeout(pollTimeout);
    };
  }, [priceRefreshing]);

  const handleCancelProcessing = async () => {
    try {
      await fetch('http://localhost:3001/api/cancel-processing', { method: 'POST' });
    } catch (e) {
      console.error('cancel failed', e);
    }
    setBgProcessing(false);
  };

  const handleCancelPriceRefresh = async () => {
    try {
      await fetch('http://localhost:3001/api/cancel-price-refresh', { method: 'POST' });
    } catch (e) {
      console.error('cancel price refresh failed', e);
    }
    setPriceRefreshing(false);
  };

  return (
    <>
      {/* Card Processing Banner */}
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
              onClick={handleCancelProcessing}
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

      {/* Price Refresh Banner */}
      <div
        className={`top-progress price-refresh ${priceRefreshing ? 'show' : ''}`}
        style={{ top: bgProcessing ? '70px' : '0' }}
        role="status"
        aria-live="polite"
      >
        <div className="top-progress-inner">
          <div className="top-progress-info">
            <div className="top-progress-title">
              <span className="progress-spinner"></span>
              {priceTotal > 0 ? (
                <>REFRESHING PRICES {priceCurrent} OF {priceTotal}</>
              ) : (
                <>REFRESHING PRICES</>
              )}
            </div>
            <div className="top-progress-file">
              {priceUpdated > 0 ? `${priceUpdated} cards updated` : 'Starting...'}
            </div>
          </div>
          <div className="top-progress-percent">{priceProgress}%</div>
          <div className="top-progress-actions">
            <button
              className="cancel-processing"
              type="button"
              onClick={handleCancelPriceRefresh}
              title="Cancel price refresh"
            >
              CANCEL
            </button>
          </div>
          <div className="progress-track top">
            <div className="progress-bar" style={{ width: `${priceProgress}%` }} />
          </div>
        </div>
      </div>
    </>
  );
}

export default GlobalProgressBar;
