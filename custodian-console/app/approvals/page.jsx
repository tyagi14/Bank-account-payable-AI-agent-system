"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, money } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export default function Approvals() {
  const { user, token, login } = useAuth();
  const [runs, setRuns] = useState([]);
  const [message, setMessage] = useState("");

  const load = () => api("/approvals").then(setRuns).catch((e) => setMessage(e.message));
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, []);

  async function decide(id, approved) {
    const comment = window.prompt(approved ? "Approval note (optional)" : "Reason for denial") ?? "";
    try {
      await api(`/runs/${id}/decision`, { method: "POST", token, body: JSON.stringify({ approved, comment }) });
      setMessage(`${approved ? "Approved" : "Denied"} ${id}; the policy service still checks your authority for this amount.`);
      load();
    } catch (e) { setMessage(e.message); }
  }

  return (
    <>
      <h1>Approval queue</h1>
      {!user && <p className="panel">Log in with Keycloak to approve or deny. <button onClick={login}>Log in</button></p>}
      {message && <p className="panel">{message}</p>}
      <div className="panel">
        <table>
          <thead><tr><th>Run</th><th>Vendor</th><th>Amount</th><th>Risk</th><th>Why it needs a human</th><th></th></tr></thead>
          <tbody>
            {runs.length === 0 && <tr><td colSpan={6} className="muted">Nothing waiting.</td></tr>}
            {runs.map((r) => (
              <tr key={r.thread_id}>
                <td><Link href={`/runs/${r.thread_id}`}>{r.thread_id.slice(0, 8)}</Link></td>
                <td>{r.summary.vendor}</td><td>{money(r.summary.amount_cents)}</td><td>{r.summary.risk_score}</td>
                <td>{(r.summary.escalation_reasons || []).map((x, i) => <div key={i}>{x}</div>)}</td>
                <td className="row"><button disabled={!user} onClick={() => decide(r.thread_id, true)}>Approve</button>
                  <button disabled={!user} className="danger" onClick={() => decide(r.thread_id, false)}>Deny</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
