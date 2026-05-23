import { useParams } from '../router.jsx';
import TwinReportsPage from '../components/twin/TwinReportsPage.jsx';
import EmptyState from '../components/shared/EmptyState.jsx';

export default function TwinReports() {
  const { siteId } = useParams();
  if (!siteId) return <EmptyState title="Site not found" />;
  return <TwinReportsPage siteId={siteId} />;
}
