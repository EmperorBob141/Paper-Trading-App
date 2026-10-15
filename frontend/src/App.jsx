import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api.js";
import TopBar from "./components/TopBar.jsx";
import AuthPage from "./pages/AuthPage.jsx";
import Portfolio from "./pages/Portfolio.jsx";
import Stock from "./pages/Stock.jsx";
import History from "./pages/History.jsx";
import Performance from "./pages/Performance.jsx";

const UserContext = createContext(null);
export const useUser = () => useContext(UserContext);

export default function App() {
  const [user, setUser] = useState(undefined); // undefined = still checking, null = logged out

  const refreshUser = useCallback(
    () => api.me().then(setUser).catch(() => setUser(null)),
    []
  );
  useEffect(() => {
    refreshUser();
  }, [refreshUser]);

  if (user === undefined) return <div className="splash">Loading…</div>;
  if (!user) return <AuthPage onLogin={refreshUser} />;

  const logout = async () => {
    await api.logout().catch(() => {});
    setUser(null);
  };

  return (
    <UserContext.Provider value={{ user, refreshUser, logout }}>
      <TopBar />
      <main className="page">
        <Routes>
          <Route path="/" element={<Portfolio />} />
          <Route path="/stock/:symbol" element={<Stock />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/history" element={<History />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </UserContext.Provider>
  );
}
