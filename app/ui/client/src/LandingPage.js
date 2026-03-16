import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import './LandingPage.css';

function LandingPage() {
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    // proxy already authenticated us — check without requiring a local JWT
    fetch('/api/auth/me')
      .then(r => {
        if (r.ok) navigate('/dashboard', { replace: true });
        else setChecking(false);
      })
      .catch(() => setChecking(false));
  }, [navigate]);

  if (checking) return null;

  return (
    <div className="landing-page">
      <main className="landing-main">
        <p className="landing-sub">trading cards</p>
        <div className="landing-actions">
          <button className="landing-continue" onClick={() => navigate('/dashboard')}>
            enter
          </button>
        </div>
      </main>

    </div>
  );
}

export default LandingPage;
