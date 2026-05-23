import { useParams } from '../router.jsx';
import TwinAlertsPage from '../components/twin/TwinAlertsPage.jsx';
import EmptyState from '../components/shared/EmptyState.jsx';

export default function TwinAlerts() {
  const { siteId } = useParams();
  if (!siteId) return <EmptyState title="Site not found" />;
  return <TwinAlertsPage siteId={siteId} />;
}
