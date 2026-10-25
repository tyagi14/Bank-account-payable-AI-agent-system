"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function Pipeline() {
  const router = useRouter();
  const [runs, setRuns] = useState([]);
  const [text, setText] = useState("");
  const [file, setFile] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const load = () => api("/runs?limit=50").then(setRuns).catch((e) => setError(e.message));
    load();
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, []);

  async function submit(kind) {
    setBusy(true); setError("");
    try {
      let res;
      if (kind === "text") res = await api("/runs", { method: "POST", body: JSON.stringify({ ocr_text: text }) });
      else {
        const form = new FormData();
        form.append("file", file);
        res = await api("/runs/image", { method: "POST", body: form });
      }
      router.push(`/runs/${res.thread_id}`);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <>
      <h1>Invoice pipeline</h1>
      <div className="grid">
        <div className="panel">
          <h2>Submit pasted OCR text</h2>
          <p className="muted">Skips OCR; goes straight to the guardrail and extraction.</p>
          <textarea rows={8} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste receipt / invoice text" />
          <p><button disabled={busy || !text.trim()} onClick={() => submit("text")}>Run pipeline</button></p>
        </div>
        <div className="panel">
          <h2>Upload an invoice image</h2>
          <p className="muted">PNG or JPEG. OCR runs in a fresh, network-less, Landlock-restricted container.</p>
          <input type="file" accept="image/png,image/jpeg" onChange={(e) => setFile(e.target.files[0] || null)} />
          <p><button disabled={busy || !file} onClick={() => submit("image")}>Upload and run</button></p>
        </div>
      </div>
      {error && <p className="deny">{error}</p>}
      <div className="panel">
        <h2>Recent runs</h2>
        <table>
          <thead><tr><th>Submitted</th><th>Source</th><th>State</th><th>Stage</th><th>Vendor</th><th>Total</th><th>Outcome</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.thread_id}>
                <td><Link href={`/runs/${r.thread_id}`}>{new Date(r.created_at).toLocaleString()}</Link></td>
                <td>{r.source}</td><td className={r.task_state}>{r.task_state}</td><td>{r.stage}</td>
                <td>{r.summary.vendor || "-"}</td><td>{r.summary.total ?? "-"}</td><td className="muted">{r.summary.outcome || r.summary.error || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
