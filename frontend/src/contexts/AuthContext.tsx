import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type WhoAmI } from "../lib/api";

interface AuthContextValue {
  whoami: WhoAmI | null;
  loading: boolean;
  error: string | null;
}

const AuthContext = createContext<AuthContextValue>({
  whoami: null,
  loading: true,
  error: null,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [whoami, setWhoami] = useState<WhoAmI | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .whoami()
      .then((w) => {
        if (!cancelled) setWhoami(w);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AuthContext.Provider value={{ whoami, loading, error }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
