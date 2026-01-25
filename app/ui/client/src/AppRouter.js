import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import MainPage from './MainPage';
import App from './App';
import DatabaseBrowser from './DatabaseBrowser';
import SystemLogs from './SystemLogs';
import RawScanPreview from './RawScanPreview';
import GlobalProgressBar from './GlobalProgressBar';

function AppRouter() {
  return (
    <Router>
      {/* Global processing status bar - visible on all pages */}
      <GlobalProgressBar />
      <Routes>
        <Route path="/" element={<MainPage />} />
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
