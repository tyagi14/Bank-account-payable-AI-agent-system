"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export default function Audit() {
  const [entries, setEntries] = useState([]);
  const [verify, setVerify] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { api("/audit/entries?limit=200").then(setEntries); }, []);

  async function check() {
    setBusy(true);
    try { setVerify(await api("/audit/verify")); } catch (e) { setVerify({ error: e.message }); } finally { setBusy(false); }
  }

  return (
    <>
      <h1>Audit log</h1>
      <div className="panel">
        <div className="row"><button disabled={busy} onClick={check}>{busy ? "Verifying..." : "Verify chain integrity"}</button>
          {verify && !verify.error && <b className={verify.valid ? "valid" : "invalid"}>{verify.valid ? "INTACT" : "BROKEN"} - {verify.entries_checked} entries checked (hash chain + byte-for-byte WORM comparison)</b>}</div>
        {verify && (verify.error || !verify.valid) && <pre>{JSON.stringify(verify, null, 2)}</pre>}
      </div>
      <div className="panel">
        <table>
          <thead><tr><th>#</th><th>Time</th><th>Event</th><th>Actor</th><th>Run</th><th>entry_hash / prev_hash</th><th></th></tr></thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.seq}>
                <td>{e.seq}</td><td>{new Date(e.ts).toLocaleString()}</td>
                <td className={e.event_type.includes("tamper") ? "deny" : ""}>{e.event_type}</td><td>{e.actor}</td>
                <td>{e.thread_id ? e.thread_id.slice(0, 8) : ""}</td>
                <td className="muted"><code>{e.entry_hash.slice(0, 16)}</code><br /><code>{e.prev_hash.slice(0, 16)}</code></td>
                <td><details><summary>payload</summary><pre>{JSON.stringify(e.payload, null, 2)}</pre></details></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
