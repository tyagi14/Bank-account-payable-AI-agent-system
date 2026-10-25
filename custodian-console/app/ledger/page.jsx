"use client";
import { useEffect, useState } from "react";
import { LINKS, api, money } from "../../lib/api";

export default function Ledger() {
  const [accounts, setAccounts] = useState([]);
  const [entries, setEntries] = useState([]);
  const [costs, setCosts] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = () => Promise.all([api("/ledger/accounts"), api("/ledger/entries?limit=50"), api("/costs")])
      .then(([a, e, c]) => { setAccounts(a); setEntries(e); setCosts(c); }).catch((e) => setError(e.message));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  return (
    <>
      <h1>Ledger &amp; cost</h1>
      {error && <p className="deny">{error}</p>}
      <div className="grid">
        <div className="panel">
          <h2>Balances</h2>
          <table><tbody>{accounts.map((a) => <tr key={a.id}><td>{a.id}</td><td className="muted">{a.kind}</td><td>{money(a.balance_cents)}</td></tr>)}</tbody></table>
        </div>
        <div className="panel">
          <h2>LLM spend vs. daily cap (enforced by the gateway)</h2>
          <table>
            <thead><tr><th>Agent key</th><th>Spend</th><th>Cap</th><th>Routes</th></tr></thead>
            <tbody>{costs.map((c) => <tr key={c.agent}><td>{c.agent}</td><td>{c.spend_usd != null ? `$${c.spend_usd.toFixed(4)}` : c.error}</td>
              <td>{c.max_budget_usd != null ? `$${c.max_budget_usd}` : "-"}</td><td className="muted">{(c.models || []).join(", ")}</td></tr>)}</tbody>
          </table>
          <p className="row"><a href={LINKS.grafana} target="_blank">Grafana</a><a href={LINKS.langfuse} target="_blank">Langfuse traces</a></p>
        </div>
      </div>
      <div className="panel">
        <h2>Journal</h2>
        <table>
          <thead><tr><th>Time</th><th>Description</th><th>Postings</th><th>Key</th></tr></thead>
          <tbody>{entries.map((e) => (
            <tr key={e.id}><td>{new Date(e.created_at).toLocaleString()}</td><td>{e.description}</td>
              <td>{e.postings.map((p, i) => <div key={i}>{p.account_id}: {money(p.amount_cents)}</div>)}</td><td className="muted">{e.idempotency_key}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </>
  );
}
