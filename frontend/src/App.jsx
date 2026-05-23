import { Router, Route } from './router.jsx';
import { TimeRangeProvider } from './contexts/TimeRangeContext.jsx';
import Sidebar from './components/layout/Sidebar.jsx';
import Portfolio from './pages/Portfolio.jsx';
import Site from './pages/Site.jsx';
import DigitalTwin from './pages/DigitalTwin.jsx';
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
            <Route path="/alerts" element={<Alerts />} />
          </main>
        </div>
      </TimeRangeProvider>
    </Router>
  );
}
