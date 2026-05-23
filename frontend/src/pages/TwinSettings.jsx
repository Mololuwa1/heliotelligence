import { useParams } from '../router.jsx';
import TwinSettingsPage from '../components/twin/TwinSettingsPage.jsx';
import EmptyState from '../components/shared/EmptyState.jsx';

export default function TwinSettings() {
  const { siteId } = useParams();
  if (!siteId) return <EmptyState title="Site not found" />;
  return <TwinSettingsPage siteId={siteId} />;
}
