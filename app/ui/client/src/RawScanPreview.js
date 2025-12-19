import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './RawScanPreview.css';

function RawScanPreview() {
  const navigate = useNavigate();
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch('http://localhost:3001/api/raw-scans');
        const data = await r.json();
        setFiles(data.files || []);
      } catch (e) {
        setFiles([]);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="raw-preview">
      <header className="raw-header">
        <h1>raw scan preview</h1>
        <button className="back-button" onClick={() => navigate('/')}>← Back</button>
      </header>
      {loading ? (
        <div className="loading">Loading raw scans…</div>
      ) : files.length === 0 ? (
        <div className="empty">No raw scans found in cards/raw_scans</div>
      ) : (
        <div className="grid">
          {files.map((f, idx) => (
            <figure key={idx} className="tile">
              <img src={`http://localhost:3001${f.url}`} alt={f.name} />
              <figcaption>
                <div className="name">{f.name}</div>
                <div className="meta">{f.size ? `${(f.size/1024).toFixed(0)} KB` : ''}</div>
              </figcaption>
            </figure>
          ))}
        </div>
      )}
    </div>
  );
}

export default RawScanPreview;
