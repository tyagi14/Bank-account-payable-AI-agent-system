"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function Policies() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { api("/policies").then(setData).catch((e) => setError(e.message)); }, []);
  if (error) return <p className="deny">{error}</p>;
  if (!data) return <p className="muted">Loading...</p>;
  return (
    <>
      <h1>Policies</h1>
      <div className="panel">
        <h2>Temporal rules (enforced by policy-service/temporal.py)</h2>
        <table><tbody>{data.temporal_enforced.map((r) => (
          <tr key={r.rule_id}><td><b>{r.rule_id}</b></td><td>at most {r.limit - 1} prior approvals per vendor in {r.window_hours}h; the {r.limit}th is denied</td>
            <td className="muted">{r.actions.join(", ")}</td><td className="muted">{r.source_file}</td></tr>))}</tbody></table>
        {Object.entries(data.temporal).map(([name, text]) => <details key={name}><summary>{name}</summary><pre>{text}</pre></details>)}
      </div>
      <div className="panel">
        <h2>Agent clearances and data classifications</h2>
        <table><tbody>
          {Object.entries(data.entities.agents).map(([a, v]) => <tr key={a}><td>agent {a}</td><td>{v.trustTier}</td><td>clearance {v.clearance}</td></tr>)}
          {Object.entries(data.entities.dataAssets).map(([a, v]) => <tr key={a}><td>data {a}</td><td>{v.classification}</td><td className="muted">{v.description}</td></tr>)}
        </tbody></table>
      </div>
      {Object.entries(data.cedar).map(([name, text]) => (
        <div className="panel" key={name}><h2>{name}</h2><pre>{text}</pre></div>
      ))}
    </>
  );
}
