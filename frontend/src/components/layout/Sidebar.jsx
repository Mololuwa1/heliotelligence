import { useRouter } from '../../router.jsx';
import { useAuth } from '../../contexts/AuthContext.jsx';
import StatusDot from '../shared/StatusDot.jsx';

const BRACON_ASH = {
  id: '5ab83b40-553c-5ddd-976f-71f6cb5d490f',
  name: 'Bracon Ash',
  capacity_kwp: 28524,
};

const NAV = [
  {
    label: 'Portfolio',
    href: '/',
    icon: (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </svg>
    ),
  },
  {
    label: 'Alerts',
    href: '/alerts',
    icon: (
      <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
      </svg>
    ),
  },
];

export default function Sidebar() {
  const { path, navigate } = useRouter();
  const { user, logout } = useAuth();

  function isActive(href) {
    if (href === '/') return path === '/';
    return path.startsWith(href);
  }

  return (
    <aside className="w-64 flex-shrink-0 bg-[#0F1629] border-r border-[#2D3F55] flex flex-col h-screen sticky top-0">
      {/* Logo */}
      <div className="px-6 py-5 border-b border-[#2D3F55]">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-amber-400 flex items-center justify-center">
            <svg className="h-5 w-5 text-[#0F1629]" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2.25a.75.75 0 01.75.75v2.25a.75.75 0 01-1.5 0V3a.75.75 0 01.75-.75zM7.5 12a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM18.894 6.166a.75.75 0 00-1.06-1.06l-1.591 1.59a.75.75 0 101.06 1.061l1.591-1.59zM21.75 12a.75.75 0 01-.75.75h-2.25a.75.75 0 010-1.5H21a.75.75 0 01.75.75zM17.834 18.894a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 10-1.061 1.06l1.59 1.591zM12 18a.75.75 0 01.75.75V21a.75.75 0 01-1.5 0v-2.25A.75.75 0 0112 18zM7.758 17.303a.75.75 0 00-1.061-1.06l-1.591 1.59a.75.75 0 001.06 1.061l1.591-1.59zM6 12a.75.75 0 01-.75.75H3a.75.75 0 010-1.5h2.25A.75.75 0 016 12zM6.697 7.757a.75.75 0 001.06-1.06l-1.59-1.591a.75.75 0 00-1.061 1.06l1.59 1.591z" />
            </svg>
          </div>
          <div>
            <p className="text-white font-semibold text-sm leading-none">Heliotelligence</p>
            <p className="text-slate-500 text-xs mt-0.5">Digital Twin Platform</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map(item => (
          <button
            key={item.href}
            onClick={() => navigate(item.href)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
              isActive(item.href)
                ? 'bg-amber-400/10 text-amber-400'
                : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
          >
            {item.icon}
            {item.label}
          </button>
        ))}

        {/* Site section */}
        <div className="pt-4 pb-1">
          <p className="px-3 text-xs font-medium text-slate-600 uppercase tracking-wider">Sites</p>
        </div>
        <button
          onClick={() => navigate(`/site/${BRACON_ASH.id}`)}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
            path.startsWith(`/site/${BRACON_ASH.id}`)
              ? 'bg-amber-400/10 text-amber-400'
              : 'text-slate-400 hover:text-white hover:bg-white/5'
          }`}
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
          </svg>
          <span className="flex-1 text-left truncate">{BRACON_ASH.name}</span>
          <StatusDot status="normal" size="sm" />
        </button>

        {/* Sub-nav for site */}
        {path.startsWith(`/site/${BRACON_ASH.id}`) && (
          <div className="ml-8 space-y-1">
            <button
              onClick={() => navigate(`/site/${BRACON_ASH.id}`)}
              className={`w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors ${
                path === `/site/${BRACON_ASH.id}`
                  ? 'text-amber-400'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              Analytics
            </button>
            <button
              onClick={() => navigate(`/site/${BRACON_ASH.id}/twin`)}
              className={`w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors ${
                path === `/site/${BRACON_ASH.id}/twin`
                  ? 'text-amber-400'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              Digital Twin
            </button>
          </div>
        )}
        {/* Admin section */}
        <div className="mx-0 mt-4 mb-1 border-t border-[#2D3F55]" />
        <div className="px-3 py-1 text-xs text-slate-600 uppercase tracking-wider font-semibold">Admin</div>
        <button
          onClick={() => navigate('/admin')}
          className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
            path.startsWith('/admin')
              ? 'bg-amber-400/10 text-amber-400'
              : 'text-slate-400 hover:text-white hover:bg-white/5'
          }`}
        >
          <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.203-.107-.397.165-.71.505-.781.929l-.149.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.505-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.108-1.204l-.526-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          Site Management
        </button>
      </nav>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-[#2D3F55] space-y-2">
        {user && (
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-slate-500 truncate">{user.email ?? user.uid}</p>
            <button
              onClick={logout}
              title="Sign out"
              className="text-slate-600 hover:text-slate-300 transition-colors shrink-0"
            >
              <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
              </svg>
            </button>
          </div>
        )}
        <p className="text-xs text-slate-600">v0.1.0 · {BRACON_ASH.capacity_kwp.toLocaleString()} kWp</p>
      </div>
    </aside>
  );
}
