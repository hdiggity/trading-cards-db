import React, { useState } from 'react';
import MainPage from './MainPage';
import App from './App';
import DatabaseBrowser from './DatabaseBrowser';
import SystemLogs from './SystemLogs';
import RawScanPreview from './RawScanPreview';

function AppRouter() {
  const [currentView, setCurrentView] = useState('main');

  const handleNavigate = (view) => {
    setCurrentView(view);
  };

  switch (currentView) {
    case 'verify':
      return <App onNavigate={handleNavigate} />;
    case 'database':
      return <DatabaseBrowser onNavigate={handleNavigate} />;
    case 'logs':
      return <SystemLogs onNavigate={handleNavigate} />;
    case 'raw-preview':
      return <RawScanPreview onNavigate={handleNavigate} />;
    case 'main':
    default:
      return <MainPage onNavigate={handleNavigate} />;
  }
}

export default AppRouter;
