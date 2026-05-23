import { useParams } from '../router.jsx';
import DigitalTwinPage from '../components/twin/DigitalTwinPage.jsx';
import EmptyState from '../components/shared/EmptyState.jsx';

export default function DigitalTwin() {
  const { siteId } = useParams();
  if (!siteId) return <EmptyState title="Site not found" />;
  return <DigitalTwinPage siteId={siteId} />;
}
