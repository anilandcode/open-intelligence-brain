import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, ClipboardCheck, Play, Trash2, TriangleAlert } from "lucide-react";
import type { EvalQuestion, EvalReport, EvalRun } from "./api";
import { useBrainClient } from "./client";

const message = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback);
const percent = (value: number | null | undefined) => (typeof value === "number" ? `${Math.round(value * 100)}%` : "–");

/** The person's own questions with known answers, and how the Brain scores on them. */
export function EvalPanel({ version }: { version: number }) {
  const client = useBrainClient();
  const [questions, setQuestions] = useState<EvalQuestion[] | null>(null);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [report, setReport] = useState<EvalReport | null>(null);
  const [label, setLabel] = useState("");
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    Promise.all([client.evalQuestions(), client.evalRuns()])
      .then(([nextQuestions, nextRuns]) => { if (live) { setQuestions(nextQuestions); setRuns(nextRuns); setError(""); } })
      .catch((requestError) => { if (live) { setQuestions([]); setError(message(requestError, "Could not load the question set.")); } });
    return () => { live = false; };
  }, [client, version, reload]);

  const refresh = useCallback(() => setReload((value) => value + 1), []);

  async function run() {
    setRunning(true); setError("");
    try { setReport(await client.runEval(label.trim())); setLabel(""); refresh(); }
    catch (requestError) { setError(message(requestError, "The run failed.")); }
    finally { setRunning(false); }
  }

  async function remove(id: string) {
    try { await client.deleteEvalQuestion(id); refresh(); }
    catch (requestError) { setError(message(requestError, "Could not remove the question.")); }
  }

  if (!questions) return null;
  const failures = report?.results.filter((result) => !result.passed) ?? [];
  return (
    <section className="eval-panel panel-card" aria-labelledby="eval-heading">
      <header className="eval-header">
        <div><h2 id="eval-heading"><ClipboardCheck size={17} aria-hidden="true" /> Test questions</h2><p className="section-sub">Questions with known answers. Run them after any change to see whether the Brain answers better or worse.</p></div>
        <div className="eval-run"><label className="sr-only" htmlFor="eval-label">Run label</label><input id="eval-label" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Label this run (optional)" maxLength={120} /><button className="primary-button" type="button" onClick={run} disabled={running || questions.length === 0}><Play size={15} aria-hidden="true" />{running ? "Running…" : `Run ${questions.length}`}</button></div>
      </header>
      {error && <div className="alert alert--error" role="alert">{error}</div>}
      {questions.length === 0 && !error && <p className="section-sub">No test questions yet. Ask a question above and choose “Save as test question”. Aim for 30 to 50, including some the Brain should not answer.</p>}
      {report && (
        <div className="eval-report" aria-live="polite">
          <dl className="eval-metrics">
            <div><dt>Passed</dt><dd>{report.summary.passed}/{report.summary.questions}</dd></div>
            <div><dt>Answered correctly</dt><dd>{report.summary.answered_correctly}/{report.summary.answerable}</dd></div>
            <div><dt>Found in top 8</dt><dd>{percent(report.summary.recall_at_8 as number | null)}</dd></div>
            <div><dt>Abstained correctly</dt><dd>{report.summary.abstained_correctly}/{report.summary.abstain_questions}</dd></div>
            <div className={report.summary.false_answers ? "eval-bad" : ""}><dt>False answers</dt><dd>{report.summary.false_answers}</dd></div>
            {report.summary.stale_questions > 0 && <div><dt>Need updating</dt><dd>{report.summary.stale_questions}</dd></div>}
          </dl>
          {failures.length > 0 ? <ul className="eval-failures">{failures.map((result) => <li key={result.id}><TriangleAlert size={14} aria-hidden="true" /><span><strong>{result.question}</strong><small>{result.reason}</small></span></li>)}</ul> : <p className="eval-ok"><CheckCircle2 size={15} aria-hidden="true" /> Every question passed.</p>}
        </div>
      )}
      {questions.length > 0 && (
        <details className="eval-questions">
          <summary>{questions.length} {questions.length === 1 ? "question" : "questions"}</summary>
          <ul>{questions.map((question) => <li key={question.id}><span>{question.question}<small>{question.expect_abstain ? "Should not answer" : `${question.expected_ids.length} expected ${question.expected_ids.length === 1 ? "item" : "items"}`}</small></span><button type="button" className="ghost-icon" aria-label={`Remove: ${question.question}`} onClick={() => remove(question.id)}><Trash2 size={15} /></button></li>)}</ul>
        </details>
      )}
      {runs.length > 0 && (
        <table className="eval-runs">
          <caption className="sr-only">Earlier runs</caption>
          <thead><tr><th scope="col">Run</th><th scope="col">Passed</th><th scope="col">Found in top 8</th><th scope="col">False answers</th></tr></thead>
          <tbody>{runs.slice(0, 6).map((entry) => <tr key={entry.id}><td>{entry.label || new Date(entry.created_at).toLocaleString()}</td><td>{entry.summary.passed}/{entry.summary.questions}</td><td>{percent(entry.summary.recall_at_8 as number | null)}</td><td>{entry.summary.false_answers}</td></tr>)}</tbody>
        </table>
      )}
    </section>
  );
}
