import { useParams } from '../router.jsx';
import SitePage from '../components/site/SitePage.jsx';
import EmptyState from '../components/shared/EmptyState.jsx';

export default function Site() {
  const { siteId } = useParams();
  if (!siteId) return <EmptyState title="Site not found" />;
  return <SitePage siteId={siteId} />;
}
