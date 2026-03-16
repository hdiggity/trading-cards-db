import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import LandingPage from './LandingPage';
import MainPage from './MainPage';
import App from './App';
import DatabaseBrowser from './DatabaseBrowser';
import SystemLogs from './SystemLogs';
import RawScanPreview from './RawScanPreview';
import GlobalProgressBar from './GlobalProgressBar';

const basename = process.env.REACT_APP_BASE_PATH || '/';

function AppRouter() {
  return (
    <Router basename={basename}>
      {/* Global processing status bar - visible on all pages */}
      <GlobalProgressBar />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/dashboard" element={<MainPage />} />
        <Route path="/verification" element={<App />} />
        <Route path="/database" element={<DatabaseBrowser />} />
        <Route path="/logs" element={<SystemLogs />} />
        <Route path="/raw-preview" element={<RawScanPreview />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
}

export default AppRouter;
