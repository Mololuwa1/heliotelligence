import { Router, Route } from './router.jsx';
import { TimeRangeProvider } from './contexts/TimeRangeContext.jsx';
import { AuthProvider, useAuth } from './contexts/AuthContext.jsx';
import Sidebar from './components/layout/Sidebar.jsx';
import LoginPage from './components/auth/LoginPage.jsx';
import Portfolio from './pages/Portfolio.jsx';
import Site from './pages/Site.jsx';
import DigitalTwin from './pages/DigitalTwin.jsx';
import TwinAssets from './pages/TwinAssets.jsx';
import TwinAnalytics from './pages/TwinAnalytics.jsx';
import TwinAlerts from './pages/TwinAlerts.jsx';
import TwinReports from './pages/TwinReports.jsx';
import TwinSettings from './pages/TwinSettings.jsx';
import Alerts from './pages/Alerts.jsx';
import Admin from './pages/Admin.jsx';
import AdminOnboard from './pages/AdminOnboard.jsx';

function ProtectedApp() {
  const { user } = useAuth();

  // Still checking auth state
  if (user === undefined) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  // Not signed in
  if (user === null) {
    return <LoginPage />;
  }

  // Signed in — render the full app
  return (
    <TimeRangeProvider>
      <div className="flex h-screen bg-[#111827] overflow-hidden">
        <Sidebar />
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <Route path="/" element={<Portfolio />} />
          <Route path="/site/:siteId" element={<Site />} />
          <Route path="/site/:siteId/twin" element={<DigitalTwin />} />
          <Route path="/site/:siteId/twin/assets" element={<TwinAssets />} />
          <Route path="/site/:siteId/twin/analytics" element={<TwinAnalytics />} />
          <Route path="/site/:siteId/twin/alerts" element={<TwinAlerts />} />
          <Route path="/site/:siteId/twin/reports" element={<TwinReports />} />
          <Route path="/site/:siteId/twin/settings" element={<TwinSettings />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/admin/onboard" element={<AdminOnboard />} />
        </main>
      </div>
    </TimeRangeProvider>
  );
}

export default function App() {
  return (
    <Router>
      <AuthProvider>
        <ProtectedApp />
      </AuthProvider>
    </Router>
  );
}
