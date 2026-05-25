import { createContext, useContext, useEffect, useState } from 'react';
import { onAuthStateChanged, signInWithEmailAndPassword, signInWithPopup, GoogleAuthProvider, signOut } from 'firebase/auth';
import { auth } from '../firebase.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(undefined); // undefined = loading
  const [token, setToken] = useState(null);

  useEffect(() => {
    return onAuthStateChanged(auth, async (firebaseUser) => {
      if (firebaseUser) {
        const idToken = await firebaseUser.getIdToken();
        setToken(idToken);
        setUser(firebaseUser);
      } else {
        setToken(null);
        setUser(null);
      }
    });
  }, []);

  // Refresh token before it expires (Firebase tokens last 1 hour)
  useEffect(() => {
    if (!user) return;
    const interval = setInterval(async () => {
      try {
        const idToken = await user.getIdToken(/* forceRefresh */ true);
        setToken(idToken);
      } catch {
        // Token refresh failed — user will be signed out by onAuthStateChanged
      }
    }, 55 * 60 * 1000); // refresh every 55 minutes
    return () => clearInterval(interval);
  }, [user]);

  async function loginWithEmail(email, password) {
    return signInWithEmailAndPassword(auth, email, password);
  }

  async function loginWithGoogle() {
    const provider = new GoogleAuthProvider();
    return signInWithPopup(auth, provider);
  }

  const logout = () => signOut(auth);

  return (
    <AuthContext.Provider value={{ user, token, loginWithEmail, loginWithGoogle, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
