import { useParams } from '../router.jsx';
import TwinAssetsPage from '../components/twin/TwinAssetsPage.jsx';
import EmptyState from '../components/shared/EmptyState.jsx';

export default function TwinAssets() {
  const { siteId } = useParams();
  if (!siteId) return <EmptyState title="Site not found" />;
  return <TwinAssetsPage siteId={siteId} />;
}
