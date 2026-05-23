import { Router, Route } from './router.jsx';
import { TimeRangeProvider } from './contexts/TimeRangeContext.jsx';
import Sidebar from './components/layout/Sidebar.jsx';
import Portfolio from './pages/Portfolio.jsx';
import Site from './pages/Site.jsx';
import DigitalTwin from './pages/DigitalTwin.jsx';
import TwinAssets from './pages/TwinAssets.jsx';
import TwinAnalytics from './pages/TwinAnalytics.jsx';
import TwinAlerts from './pages/TwinAlerts.jsx';
import TwinReports from './pages/TwinReports.jsx';
import TwinSettings from './pages/TwinSettings.jsx';
import Alerts from './pages/Alerts.jsx';

export default function App() {
  return (
    <Router>
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
          </main>
        </div>
      </TimeRangeProvider>
    </Router>
  );
}
