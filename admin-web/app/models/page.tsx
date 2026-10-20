"use client";

/* eslint react-hooks/set-state-in-effect: off -- These effects initiate external HTTP reads; state changes occur in async response/error handlers. */

import { useCallback, useEffect, useState } from "react";
import { useAdmin, type ModelPayload } from "@/components/admin-provider";

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "Not reported";
  return typeof value === "string" || typeof value === "number" || typeof value === "boolean" ? String(value) : JSON.stringify(value);
}

export default function ModelsPage() {
  const { isConnected, requestJson } = useAdmin();
  const [payload, setPayload] = useState<ModelPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPayload(await requestJson<ModelPayload>("/api/v1/admin/models"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load model registry.");
    } finally {
      setLoading(false);
    }
  }, [requestJson]);

  useEffect(() => { if (isConnected) void refresh(); }, [isConnected, refresh]);

  return (
    <>
      <section className="welcome-row"><div><div className="eyebrow">MODEL GOVERNANCE</div><h2>Models & readiness</h2><p>Inspect registered artifact provenance and the runtime components reported by FastAPI.</p></div><button className="button button-secondary" type="button" onClick={() => void refresh()} disabled={!isConnected || loading}>{loading ? "Loading…" : "↻ Refresh"}</button></section>
      {!isConnected ? <div className="notice notice-info"><strong>Admin connection required</strong><span>Enter a valid administrator bearer key in the sidebar to load the model registry.</span></div> : null}
      {error ? <div className="notice notice-error" role="alert"><strong>Request failed</strong><span>{error}</span></div> : null}

      {payload ? <>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">RUNTIME STATUS</span><h3>Runtime components</h3></div><span className="panel-note">Reported by the running backend</span></div>
          <div className="runtime-grid">{Object.entries(payload.runtime_components ?? {}).map(([name, value]) => <div className="runtime-item" key={name}><span>{name}</span><strong>{displayValue(value)}</strong></div>)}
            {Object.keys(payload.runtime_components ?? {}).length === 0 ? <div className="empty-state"><strong>No runtime component status returned</strong><span>Check backend health and model configuration.</span></div> : null}
          </div>
        </section>
        <section className="panel table-panel">
          <div className="table-toolbar"><div><h3>Artifact registry</h3><p>{payload.registry.length} registered model versions</p></div></div>
          <div className="table-wrap"><table><thead><tr><th>Model</th><th>Version</th><th>License / permitted use</th><th>Preprocessing</th><th>Artifact SHA-256</th><th>Status</th></tr></thead><tbody>
            {payload.registry.map((model) => <tr key={`${model.model_id}:${model.model_version}`}>
              <td><strong>{model.model_id}</strong><small className="cell-subtext">{model.artifact_path}</small></td>
              <td>{model.model_version}</td>
              <td><strong>{model.license_name}</strong><small className="cell-subtext">{model.permitted_use}</small></td>
              <td>{model.preprocessing_id}</td>
              <td><code className="hash-cell">{model.artifact_sha256}</code></td>
              <td><span className={model.active ? "pill pill-success" : "pill pill-muted"}>{model.active ? "Active" : "Inactive"}</span></td>
            </tr>)}
            {payload.registry.length === 0 ? <tr><td colSpan={6}><div className="empty-state"><strong>Registry is empty</strong><span>The running service has not registered model artifacts.</span></div></td></tr> : null}
          </tbody></table></div>
        </section>
      </> : null}
      <div className="notice notice-warning"><strong>Registry presence is not model validation</strong><span>Before live attendance, verify the exact weight files and licenses, test real inference, calibrate thresholds on separate holdout data, and evaluate presentation attacks. A metadata entry alone is not evidence of accuracy.</span></div>
    </>
  );
}
