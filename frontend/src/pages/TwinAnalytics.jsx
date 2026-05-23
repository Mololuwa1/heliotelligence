import { useParams } from '../router.jsx';
import TwinAnalyticsPage from '../components/twin/TwinAnalyticsPage.jsx';
import EmptyState from '../components/shared/EmptyState.jsx';

export default function TwinAnalytics() {
  const { siteId } = useParams();
  if (!siteId) return <EmptyState title="Site not found" />;
  return <TwinAnalyticsPage siteId={siteId} />;
}
