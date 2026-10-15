import { useEffect, useState } from "react";
import { api } from "../api.js";
import { money, num, TZ } from "../format.js";

const longDate = (d) =>
  new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
const shortDay = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const utc = (iso) => new Date(iso.endsWith("Z") ? iso : `${iso}Z`).getTime();

function countdown(ms) {
  if (ms <= 0) return "any moment now";
  const days = Math.floor(ms / 86_400_000);
  const hours = Math.floor((ms % 86_400_000) / 3_600_000);
  if (days >= 2) return `in ${days} days`;
  if (days === 1) return `in 1 day, ${hours} hour${hours === 1 ? "" : "s"}`;
  const mins = Math.max(1, Math.floor((ms % 3_600_000) / 60_000));
  return hours ? `in ${hours} hour${hours === 1 ? "" : "s"}` : `in ${mins} minute${mins === 1 ? "" : "s"}`;
}

/** The quarterly 2% deposit: what it is, the next payout, and a bar that fills as the date approaches. */
export default function DepositCard({ refreshKey, onPaid }) {
  const [info, setInfo] = useState(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    api.deposits().then(setInfo).catch(() => {});
  }, [refreshKey]);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(id);
  }, []);

  // When the payout moment passes, reload so the deposit is credited and the next countdown starts.
  useEffect(() => {
    if (!info) return;
    const ms = utc(info.next_at) - Date.now();
    if (ms > 2_147_000_000) return; // longer than setTimeout allows; the minute tick re-renders anyway
    const id = setTimeout(() => {
      api.deposits().then((d) => {
        setInfo(d);
        onPaid?.();
      }).catch(() => {});
    }, ms > 0 ? ms + 5_000 : 120_000); // if it's overdue (e.g. no market data yet), check again every 2 minutes
    return () => clearTimeout(id);
  }, [info, onPaid]);

  if (!info) return null;
  const start = utc(info.countdown_start);
  const end = utc(info.next_at);
  const progress = Math.min(1, Math.max(0, (now - start) / (end - start)));
  const last = info.history[0];

  return (
    <section className="card deposit-card">
      <h3>Quarterly deposits</h3>
      <p className="muted small deposit-about">
        Every {info.every_months} months, {num(info.rate_pct)}% of your account value is added to your cash on the 1st of
        the month. The amount is based on your account value at the last market close before the payout. Deposits are new
        money, so they don't count toward your returns.
      </p>

      <div className="deposit-next">
        <div>
          <div className="muted small">Next deposit</div>
          <div className="deposit-date">{longDate(info.next_date)}</div>
          <div className="muted small">{countdown(end - now)}</div>
        </div>
        <div className="r">
          <div className="muted small">Estimate</div>
          <div className="deposit-amount">{money(info.estimate)}</div>
          <div className="muted small">{num(info.rate_pct)}% of {money(info.estimate_basis.value)}</div>
        </div>
      </div>

      <div
        className="deposit-bar"
        role="progressbar"
        aria-label="Time until the next deposit"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
      >
        <div className="deposit-fill" style={{ width: `${progress * 100}%` }} />
      </div>
      <div className="deposit-bar-labels muted small">
        <span>{last ? `Last paid ${shortDay(last.pay_date)}` : `Opened ${new Date(start).toLocaleDateString("en-US", { timeZone: TZ, month: "short", day: "numeric" })}`}</span>
        <span>{Math.floor(progress * 100)}%</span>
        <span>{shortDay(info.next_date)}</span>
      </div>
      <p className="muted small deposit-foot">
        Estimate uses your value at the {shortDay(info.estimate_basis.d)} close. The final amount uses the last close before{" "}
        {shortDay(info.next_date)}.
        {info.total > 0 && <> You've received {money(info.total)} in deposits so far.</>}
      </p>
    </section>
  );
}
