"use client";
import { use, useEffect, useState } from "react";
import { API } from "../../../lib/api";

function Event({ e }) {
  const d = e.detail || {};
  let summary = "";
  if (e.kind === "policy") summary = `${d.action}: ${d.decision.toUpperCase()}`;
  else if (e.kind === "outcome") summary = `${d.task_state} / ${d.stage}: ${d.reason}`;
  else if (e.kind === "guardrail") summary = d.violation ? `VIOLATION ${d.categories.join(", ")}` : "clean";
  else if (e.kind === "risk") summary = `risk score ${d.risk_score}`;
  else if (e.kind === "decision") summary = `${d.decision} (confidence ${d.confidence})`;
  else if (e.kind === "critic") summary = d.agrees ? "critic agrees" : "critic DISAGREES";
  else if (e.kind === "dry_run") summary = d.valid ? "dry-run valid" : `dry-run INVALID: ${d.errors.join("; ")}`;
  else if (e.kind === "hold") summary = `settlement hold ${d.seconds}s`;
  return (
    <div className={`event ${e.kind}`}>
      <div className="row"><b>{e.agent}</b><span className="tag">{e.kind}</span>
        <span className={d.decision || (d.valid === false ? "invalid" : "")}>{summary}</span>
        <span className="muted">{new Date(e.ts).toLocaleTimeString()}</span></div>
      {e.kind === "policy" && <div className="muted">{(d.reasons || []).join(" | ")} {JSON.stringify(d.checks)}</div>}
      <details><summary className="muted">detail</summary><pre>{JSON.stringify(d, null, 2)}</pre></details>
    </div>
  );
}

export default function Run({ params }) {
  const { id } = use(params);
  const [events, setEvents] = useState([]);
  const [run, setRun] = useState({});

  useEffect(() => {
    const ws = new WebSocket(`${API.replace(/^http/, "ws")}/runs/${id}/ws`);
    ws.onmessage = (msg) => {
      const e = JSON.parse(msg.data);
      if (e.kind === "run") setRun(e);
      else setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev, e]));
    };
    return () => ws.close();
  }, [id]);

  return (
    <>
      <h1>Run {id}</h1>
      <div className="panel row">
        <span>State: <b className={run.task_state}>{run.task_state || "..."}</b></span>
        <span>Stage: <b>{run.stage || "..."}</b></span>
      </div>
      <div className="panel">
        <h2>Live agent steps</h2>
        {events.length === 0 && <p className="muted">Waiting for the first step...</p>}
        {events.map((e) => <Event key={e.id} e={e} />)}
      </div>
    </>
  );
}
