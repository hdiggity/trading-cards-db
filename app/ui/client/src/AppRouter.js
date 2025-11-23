import React, { useState } from 'react';
import MainPage from './MainPage';
import App from './App';
import DatabaseBrowser from './DatabaseBrowser';
import SystemLogs from './SystemLogs';
import RawScanPreview from './RawScanPreview';

function AppRouter() {
  const [currentView, setCurrentView] = useState('main');
  const [navKey, setNavKey] = useState(0);

  const handleNavigate = (view) => {
    setCurrentView(view);
    // Increment key to force remount and data refresh when navigating back
    setNavKey(k => k + 1);
  };

  switch (currentView) {
    case 'verify':
      return <App key={`verify-${navKey}`} onNavigate={handleNavigate} />;
    case 'database':
      return <DatabaseBrowser key={`db-${navKey}`} onNavigate={handleNavigate} />;
    case 'logs':
      return <SystemLogs key={`logs-${navKey}`} onNavigate={handleNavigate} />;
    case 'raw-preview':
      return <RawScanPreview key={`raw-${navKey}`} onNavigate={handleNavigate} />;
    case 'main':
    default:
      return <MainPage key={`main-${navKey}`} onNavigate={handleNavigate} />;
  }
}

export default AppRouter;
