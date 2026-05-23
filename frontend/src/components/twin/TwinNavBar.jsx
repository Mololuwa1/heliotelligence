import { useEffect, useState } from 'react';
import { useRouter } from '../../router.jsx';

const NAV_ITEMS = [
  { label: 'Overview',  path: '' },
  { label: 'Assets',    path: '/assets' },
  { label: 'Analytics', path: '/analytics' },
  { label: 'Alerts',    path: '/alerts' },
  { label: 'Reports',   path: '/reports' },
  { label: 'Settings',  path: '/settings' },
];

export default function TwinNavBar({ activePage, siteId, siteName }) {
  const { navigate } = useRouter();
  const [utc, setUtc] = useState('');

  useEffect(() => {
    function tick() {
      setUtc(new Date().toUTCString().slice(17, 25) + ' UTC');
    }
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex items-center px-5 py-0 bg-[#060D1A] border-b border-[#1E2A3A] flex-shrink-0" style={{ height: 56 }}>
      {/* Left: branding */}
      <div className="flex flex-col justify-center mr-8 min-w-max">
        <span className="text-white font-bold text-xs tracking-widest uppercase leading-none">Solar Farm Digital Twin</span>
        <span className="text-amber-400 text-xs leading-none mt-0.5">{siteName ?? '—'}</span>
      </div>

      {/* Centre: tabs */}
      <nav className="flex gap-1 flex-1">
        {NAV_ITEMS.map(({ label, path }) => (
          <button
            key={label}
            onClick={() => navigate(`/site/${siteId}/twin${path}`)}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors font-medium border-b-2 ${
              activePage === label
                ? 'text-amber-400 bg-amber-400/10 border-amber-400'
                : 'text-slate-400 hover:text-white hover:bg-white/5 border-transparent'
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* Right: weather + clock + back */}
      <div className="flex items-center gap-4 ml-4 flex-shrink-0">
        <div className="flex items-center gap-1.5 text-xs text-slate-400">
          <svg className="h-4 w-4 text-amber-400" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2.25a.75.75 0 01.75.75v2.25a.75.75 0 01-1.5 0V3a.75.75 0 01.75-.75zM7.5 12a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM18.894 6.166a.75.75 0 00-1.06-1.06l-1.591 1.59a.75.75 0 101.06 1.061l1.591-1.59zM21.75 12a.75.75 0 01-.75.75h-2.25a.75.75 0 010-1.5H21a.75.75 0 01.75.75zM17.834 18.894a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 10-1.061 1.06l1.59 1.591zM12 18a.75.75 0 01.75.75V21a.75.75 0 01-1.5 0v-2.25A.75.75 0 0112 18zM7.758 17.303a.75.75 0 00-1.061-1.06l-1.591 1.59a.75.75 0 001.06 1.061l1.591-1.59zM6 12a.75.75 0 01-.75.75H3a.75.75 0 010-1.5h2.25A.75.75 0 016 12zM6.697 7.757a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 00-1.061 1.06l1.59 1.591z" />
          </svg>
          <span>—</span>
        </div>
        <span className="font-mono text-xs text-slate-500">{utc}</span>
        <button
          onClick={() => navigate(`/site/${siteId}`)}
          className="text-xs text-slate-500 hover:text-white border border-[#1E2A3A] rounded px-2 py-1 transition-colors"
        >
          ← Analytics
        </button>
      </div>
    </div>
  );
}
