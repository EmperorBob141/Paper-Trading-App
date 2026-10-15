import { useEffect, useState } from "react";
import { api } from "../api.js";
import { parseUtc } from "../format.js";

/** Whether the stock market is open, and when it next opens or closes. Refreshes itself when that changes. */
export default function useMarketStatus() {
  const [status, setStatus] = useState(null);
  useEffect(() => {
    let timer;
    let alive = true;
    const load = () =>
      api.marketStatus().then((s) => {
        if (!alive) return;
        setStatus(s);
        // Check again right after the next open or close, or in 10 minutes at most.
        const next = parseUtc(s.is_open ? s.closes_at : s.opens_at).getTime() - Date.now();
        timer = setTimeout(load, Math.min(Math.max(next + 2_000, 5_000), 600_000));
      }).catch(() => {
        timer = setTimeout(load, 60_000);
      });
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);
  return status;
}
