"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { ImageViewer } from "@/components/ImageViewer";
import { useToast } from "@/components/Toast";
import { Badge, Card, ConfidenceBadge, ErrorNotice, PageHeader, Spinner } from "@/components/ui";
import { fetcher, HttpError, send } from "@/lib/fetcher";
import { blankLine, formFromTask, serverErrors, toSubmission, validateForm, type FormError, type ReviewForm } from "@/lib/review-form";
import type { ReviewTask } from "@/lib/types";
import { claimNext } from "../claim";

const RENEW_EVERY_MS = 60_000;

function useLeaseCountdown(expiresAt: string | null): number | null {
  const [left, setLeft] = useState<number | null>(null);
  useEffect(() => {
    if (!expiresAt) return;
    const tick = () => setLeft(Math.max(0, Math.round((new Date(expiresAt).getTime() - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [expiresAt]);
  return left;
}

export default function ReviewWorkspace({ params }: { params: { taskId: string } }) {
  const router = useRouter();
  const toast = useToast();
  const { data: task, error, isLoading } = useSWR<ReviewTask>(`reviews/${params.taskId}`, fetcher, { revalidateOnFocus: false });
  const [form, setForm] = useState<ReviewForm | null>(null);
  const [errors, setErrors] = useState<FormError[]>([]);
  const [leaseUntil, setLeaseUntil] = useState<string | null>(null);
  const [leaseLost, setLeaseLost] = useState(false);
  const [state, setState] = useState<"editing" | "submitting" | "done">("editing");
  const formRef = useRef(form);
  formRef.current = form;

  useEffect(() => {
    if (task && !form) {
      setForm(formFromTask(task));
      setLeaseUntil(task.lease_expires_at);
    }
  }, [task, form]);

  const onLeaseError = useCallback((e: unknown) => {
    if (e instanceof HttpError && e.status === 409) setLeaseLost(true);
  }, []);

  // Keep the lease alive while the tab is visible and the task is open.
  useEffect(() => {
    if (!task || state === "done" || leaseLost) return;
    const renew = () => {
      if (document.visibilityState !== "visible") return;
      send<{ lease_expires_at: string }>("POST", `reviews/${task.task_id}/renew`)
        .then((r) => setLeaseUntil(r.lease_expires_at))
        .catch(onLeaseError);
    };
    const t = setInterval(renew, RENEW_EVERY_MS);
    document.addEventListener("visibilitychange", renew);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", renew); };
  }, [task, state, leaseLost, onLeaseError]);

  const secondsLeft = useLeaseCountdown(leaseUntil);

  const submit = useCallback(async () => {
    const f = formRef.current;
    if (!task || !f || state !== "editing") return;
    const local = validateForm(f);
    setErrors(local);
    if (local.length) return;
    setState("submitting");
    try {
      await send("POST", `reviews/${task.task_id}/submit`, toSubmission(f));
      setState("done");
      toast("Submitted — stock updated", "ok");
    } catch (e) {
      setState("editing");
      if (e instanceof HttpError && e.status === 422) setErrors(serverErrors(e.body?.detail));
      else if (e instanceof HttpError && e.status === 409) setLeaseLost(true);
      else toast(String(e), "bad");
    }
  }, [task, state, toast]);

  const release = useCallback(async () => {
    if (!task || state !== "editing") return;
    try {
      await send("POST", `reviews/${task.task_id}/release`);
      toast("Released back to the queue");
    } catch (e) {
      onLeaseError(e);
    }
    router.push("/reviews");
  }, [task, state, toast, router, onLeaseError]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); void submit(); }
      if (e.key === "Escape") { e.preventDefault(); void release(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [submit, release]);

  async function next() {
    try {
      const t = await claimNext();
      if (t) router.push(`/reviews/${t.task_id}`);
      else { toast("Queue empty"); router.push("/reviews"); }
    } catch (e) {
      toast(String(e), "bad");
    }
  }

  if (isLoading) return <Spinner />;
  if (error) return <ErrorNotice error={error} />;
  if (!task || !form) return null;

  const update = (patch: Partial<ReviewForm>) => setForm({ ...form, ...patch });
  const updateLine = (key: string, patch: Partial<ReviewForm["line_items"][number]>) =>
    update({ line_items: form.line_items.map((l) => (l.key === key ? { ...l, ...patch } : l)) });
  const lineError = (line_no: number, field: string) => errors.find((e) => e.line_no === line_no && e.field === field);
  const formErrors = errors.filter((e) => e.line_no === null);
  const location = task.capture.payload.location_id ?? "";

  return (
    <>
      <PageHeader title="Review"
        subtitle={<>Capture <Link className="font-mono text-accent hover:underline" href={`/captures/${task.capture_id}`}>{task.capture_id.slice(0, 8)}</Link> · {task.capture.station_id} · model {task.extraction.model_id} / {task.extraction.prompt_version}</>}
        actions={
          <>
            <Badge tone={task.reason === "audit_sample" ? "accent" : "warn"}>{task.reason.replace("_", " ")}</Badge>
            {secondsLeft !== null && state === "editing" && !leaseLost && (
              <Badge tone={secondsLeft < 60 ? "bad" : "default"}>lease {Math.floor(secondsLeft / 60)}:{String(secondsLeft % 60).padStart(2, "0")}</Badge>
            )}
          </>
        } />

      {leaseLost && <ErrorNotice error="Your lease on this task expired or was taken over. Your edits were not saved — claim the next task." />}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card title="Packing slip"><ImageViewer src={task.image_url} alt="packing slip" /></Card>

        <Card title="Corrections" actions={<span className="text-xs text-muted">min confidence <ConfidenceBadge value={task.extraction.min_confidence} /></span>}>
          {state === "done" ? (
            <div className="space-y-3 text-center">
              <p className="text-ok">Submitted. Stock and ground truth are updated.</p>
              <div className="flex justify-center gap-2">
                <button className="btn btn-primary" onClick={next}>Claim next</button>
                <Link className="btn" href="/reviews">Back to queue</Link>
              </div>
            </div>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); void submit(); }} className="space-y-4">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="supplier">Supplier <ConfidenceBadge value={form.supplier_confidence} /></label>
                  <input id="supplier" className="input" value={form.supplier} onChange={(e) => update({ supplier: e.target.value })} />
                </div>
                <div>
                  <label className="label" htmlFor="po">PO number <ConfidenceBadge value={form.po_confidence} /></label>
                  <input id="po" className="input font-mono" value={form.po_number} onChange={(e) => update({ po_number: e.target.value })} />
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr><th className="th w-10">#</th><th className="th">SKU</th><th className="th w-24">Qty</th><th className="th">Location</th><th className="th w-8" /></tr>
                  </thead>
                  <tbody>
                    {form.line_items.map((l) => (
                      <tr key={l.key}>
                        <td className="td tabular-nums text-muted">{l.line_no}</td>
                        <td className="td">
                          <div className="flex items-center gap-1">
                            <input className={`input font-mono ${lineError(l.line_no, "sku") ? "border-bad" : ""}`} value={l.sku}
                              onChange={(e) => updateLine(l.key, { sku: e.target.value })} aria-label={`line ${l.line_no} sku`} />
                            <ConfidenceBadge value={l.confidence.sku} />
                          </div>
                          {(l.part_number || l.description) && <div className="mt-0.5 text-xs text-muted">{l.part_number} {l.description}</div>}
                          {lineError(l.line_no, "sku") && <div className="text-xs text-bad">{lineError(l.line_no, "sku")?.error}</div>}
                        </td>
                        <td className="td">
                          <div className="flex items-center gap-1">
                            <input className={`input tabular-nums ${lineError(l.line_no, "qty") ? "border-bad" : ""}`} inputMode="numeric" value={l.qty}
                              onChange={(e) => updateLine(l.key, { qty: e.target.value })} aria-label={`line ${l.line_no} qty`} />
                            <ConfidenceBadge value={l.confidence.qty} />
                          </div>
                          {lineError(l.line_no, "qty") && <div className="text-xs text-bad">{lineError(l.line_no, "qty")?.error}</div>}
                        </td>
                        <td className="td">
                          <input className={`input font-mono ${lineError(l.line_no, "location_id") ? "border-bad" : ""}`} value={l.location_id}
                            onChange={(e) => updateLine(l.key, { location_id: e.target.value })} aria-label={`line ${l.line_no} location`} />
                          {lineError(l.line_no, "location_id") && <div className="text-xs text-bad">{lineError(l.line_no, "location_id")?.error}</div>}
                        </td>
                        <td className="td">
                          <button type="button" className="btn btn-danger px-2" aria-label={`remove line ${l.line_no}`}
                            onClick={() => update({ line_items: form.line_items.filter((x) => x.key !== l.key) })}>×</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button type="button" className="btn" onClick={() => update({ line_items: [...form.line_items, blankLine(form, location)] })}>+ Add line</button>

              <div>
                <label className="label" htmlFor="notes">Notes (optional)</label>
                <textarea id="notes" className="input" rows={2} value={form.notes} onChange={(e) => update({ notes: e.target.value })} />
              </div>

              {formErrors.map((e, i) => <ErrorNotice key={i} error={`${e.field}: ${e.error}`} />)}

              <div className="flex flex-wrap items-center gap-2">
                <button type="submit" className="btn btn-primary" disabled={state !== "editing" || leaseLost}>
                  {state === "submitting" ? "Submitting…" : "Submit (⌘/Ctrl+Enter)"}
                </button>
                <button type="button" className="btn" onClick={release} disabled={state !== "editing" || leaseLost}>Release (Esc)</button>
                {leaseLost && <button type="button" className="btn" onClick={next}>Claim next</button>}
              </div>
              {task.extraction.output?.raw_text && (
                <details className="text-sm">
                  <summary className="cursor-pointer text-muted">Model transcription</summary>
                  <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-bg p-2 text-xs">{task.extraction.output.raw_text}</pre>
                </details>
              )}
            </form>
          )}
        </Card>
      </div>
    </>
  );
}
