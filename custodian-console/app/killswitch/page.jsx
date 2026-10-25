"use client";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";

const SCOPES = { global: "Global stop (everything)", agent: "Pause one agent", thread: "Halt one run", tool: "Freeze one action fleet-wide" };

export default function KillSwitch() {
  const { user, token, login } = useAuth();
  const [switches, setSwitches] = useState([]);
  const [form, setForm] = useState({ scope: "global", target: "", reason: "" });
  const [message, setMessage] = useState("");

  const load = () => api("/killswitch").then(setSwitches).catch((e) => setMessage(e.message));
  useEffect(() => { load(); const t = setInterval(load, 4000); return () => clearInterval(t); }, []);

  async function operate(operation, scope, target, reason) {
    if (operation === "trip" && !window.confirm(`Trip the ${scope} kill switch${target && target !== "*" ? ` for ${target}` : ""}?`)) return;
    try {
      await api(`/killswitch/${operation}`, { method: "POST", token, body: JSON.stringify({ scope, target: target || "*", reason: reason || "manual" }) });
      setMessage(`${operation} ${scope} ok`); load();
    } catch (e) { setMessage(e.message); }
  }

  const active = switches.filter((s) => !s.reset_at);
  return (
    <>
      <h1>Kill switch</h1>
      {!user && <p className="panel">Operating the kill switch needs a finance_controller or cfo login. <button onClick={login}>Log in</button></p>}
      {message && <p className="panel">{message}</p>}
      <div className="panel">
        <h2>Trip manually</h2>
        <div className="row">
          <select style={{ width: 240 }} value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
            {Object.entries(SCOPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          {form.scope !== "global" && <input style={{ width: 260 }} placeholder={form.scope === "tool" ? "e.g. ExecutePayment" : form.scope === "agent" ? "e.g. approval" : "run thread id"}
            value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value })} />}
          <input style={{ width: 260 }} placeholder="reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <button className="danger" disabled={!user} onClick={() => operate("trip", form.scope, form.target, form.reason)}>Trip</button>
        </div>
      </div>
      <div className="panel">
        <h2>Active ({active.length})</h2>
        <table><tbody>{active.map((s) => (
          <tr key={s.id}><td><b className="deny">{s.scope}</b> {s.target}</td><td>{s.reason}</td><td className="muted">{s.trigger} by {s.tripped_by}</td>
            <td><button className="secondary" disabled={!user} onClick={() => operate("reset", s.scope, s.target)}>Reset</button></td></tr>
        ))}</tbody></table>
      </div>
      <div className="panel">
        <h2>History (manual and automatic trips)</h2>
        <table>
          <thead><tr><th>Tripped</th><th>Scope</th><th>Trigger</th><th>Reason</th><th>By</th><th>Reset</th></tr></thead>
          <tbody>{switches.map((s) => (
            <tr key={s.id}><td>{new Date(s.tripped_at).toLocaleString()}</td><td>{s.scope} {s.target}</td><td>{s.trigger}</td><td>{s.reason}</td>
              <td>{s.tripped_by}</td><td>{s.reset_at ? `${new Date(s.reset_at).toLocaleString()} by ${s.reset_by}` : <b className="deny">active</b>}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </>
  );
}
