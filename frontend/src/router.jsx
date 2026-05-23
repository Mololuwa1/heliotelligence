import { useState, useEffect, createContext, useContext } from 'react';

const RouterCtx = createContext({ path: '/', navigate: () => {} });
const ParamsCtx = createContext({});

function getPath() {
  const hash = window.location.hash.replace(/^#/, '');
  return hash || '/';
}

export function Router({ children }) {
  const [path, setPath] = useState(getPath);

  useEffect(() => {
    const handler = () => setPath(getPath());
    window.addEventListener('hashchange', handler);
    return () => window.removeEventListener('hashchange', handler);
  }, []);

  function navigate(to) {
    window.location.hash = to;
  }

  return (
    <RouterCtx.Provider value={{ path, navigate }}>
      {children}
    </RouterCtx.Provider>
  );
}

export function useRouter() {
  return useContext(RouterCtx);
}

export function useParams() {
  return useContext(ParamsCtx);
}

function matchPattern(pattern, path) {
  if (pattern === '/') return path === '/' ? {} : null;
  const pp = pattern.split('/').filter(Boolean);
  const tp = path.split('/').filter(Boolean);
  if (pp.length !== tp.length) return null;
  const params = {};
  for (let i = 0; i < pp.length; i++) {
    if (pp[i].startsWith(':')) {
      params[pp[i].slice(1)] = decodeURIComponent(tp[i]);
    } else if (pp[i] !== tp[i]) {
      return null;
    }
  }
  return params;
}

export function Route({ path: pattern, element }) {
  const { path } = useRouter();
  const params = matchPattern(pattern, path);
  if (params === null) return null;
  return <ParamsCtx.Provider value={params}>{element}</ParamsCtx.Provider>;
}
