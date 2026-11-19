import { useState } from "react";
import { api } from "../api";
import { renderRich } from "./Rich";

const DOC_TYPES = [
  ["literature_review", "Literature review"],
  ["related_work", "Related work section"],
  ["survey", "Survey"],
  ["gap_section", "Research-gap section"],
];
const STRUCTURES = [
  ["thematic", "By theme"],
  ["chronological", "Chronological"],
  ["methodological", "By method"],
];
const LENGTHS = [
  ["short", "Short (~150 words / section)"],
  ["medium", "Medium (~300)"],
  ["long", "Long (~500)"],
];
const TONES = [
  ["academic", "Academic"],
  ["concise", "Concise"],
  ["accessible", "Accessible"],
];

function Select({ label, value, onChange, options }) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, t]) => (
          <option key={v} value={v}>{t}</option>
        ))}
      </select>
    </label>
  );
}

export default function ReviewBuilder({ workspaceId, papers, selected, getToken, onClose }) {
  const [form, setForm] = useState({
    topic: "", own_research: "", instructions: "", headings: "",
    doc_type: "literature_review", structure: "thematic", length: "medium", tone: "academic",
  });
  const [outline, setOutline] = useState(null);       // {title, sections:[{heading, goal, paper_ids}]}
  const [raw, setRaw] = useState([]);                 // sections with stable citation numbers
  const [draft, setDraft] = useState(null);           // assembled + renumbered
  const [busy, setBusy] = useState("");               // "", "outline", "write", or "section:<i>"
  const [feedback, setFeedback] = useState({});       // per-section revision notes
  const [error, setError] = useState("");

  const set = (k) => (v) => setForm((f) => ({ ...f, [k]: v }));

  function options() {
    const headings = form.headings.split("\n").map((h) => h.trim()).filter(Boolean);
    return {
      topic: form.topic.trim(),
      own_research: form.own_research.trim() || null,
      instructions: form.instructions.trim() || null,
      paper_ids: Array.from(selected),
      doc_type: form.doc_type, structure: form.structure, length: form.length, tone: form.tone,
      sections: headings.length ? headings : null,
    };
  }

  async function run(label, fn) {
    setBusy(label);
    setError("");
    try {
      await fn(await getToken());
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }

  const planOutline = () =>
    run("outline", async (t) => {
      setDraft(null);
      setOutline(await api.reviewOutline(t, workspaceId, options()));
    });

  const writeAll = () =>
    run("write", async (t) => {
      const d = await api.reviewFull(t, workspaceId, options(), outline);
      setRaw(d.raw_sections);
      setDraft(d);
      setOutline({ title: d.title, sections: outline?.sections || d.sections.map((s) => ({ heading: s.heading, goal: "", paper_ids: [] })) });
    });

  const regenerate = (i) =>
    run(`section:${i}`, async (t) => {
      const plan = outline?.sections?.[i] || { heading: raw[i].heading, goal: "", paper_ids: [] };
      const updated = await api.reviewSection(t, workspaceId, {
        options: options(),
        section: plan,
        previous_headings: raw.slice(0, i).map((s) => s.heading),
        feedback: feedback[i]?.trim() || null,
        previous_text: raw[i].content,
      });
      const next = raw.map((s, j) => (j === i ? updated : s));
      setRaw(next);
      setFeedback((f) => ({ ...f, [i]: "" }));
      setDraft(await api.reviewAssemble(t, workspaceId, options(), outline?.title || draft.title, next));
    });

  function updatePlan(i, patch) {
    setOutline((o) => ({ ...o, sections: o.sections.map((s, j) => (j === i ? { ...s, ...patch } : s)) }));
  }
  const removePlan = (i) => setOutline((o) => ({ ...o, sections: o.sections.filter((_, j) => j !== i) }));
  const addPlan = () => setOutline((o) => ({ ...o, sections: [...o.sections, { heading: "New section", goal: "", paper_ids: [] }] }));
  const movePlan = (i, d) =>
    setOutline((o) => {
      const s = [...o.sections];
      const j = i + d;
      if (j < 0 || j >= s.length) return o;
      [s[i], s[j]] = [s[j], s[i]];
      return { ...o, sections: s };
    });

  function download() {
    const blob = new Blob([draft.markdown], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${(draft.title || "review").replace(/[^\w]+/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const noPapers = selected.size === 0 || papers.length === 0;

  return (
    <section className="panel review-panel">
      <div className="gap-panel-head">
        <h2>Review builder</h2>
        <button type="button" className="btn-link btn-link--muted" onClick={onClose}>Close</button>
      </div>
      <p className="muted">Uses the {selected.size} selected paper(s). Plan the structure, edit it, then write.</p>

      <label className="field">
        <span>Topic / your research idea</span>
        <textarea rows={2} value={form.topic} onChange={(e) => set("topic")(e.target.value)}
          placeholder="e.g. Retrieval-augmented generation for scientific question answering" />
      </label>
      <div className="field-row">
        <Select label="Document type" value={form.doc_type} onChange={set("doc_type")} options={DOC_TYPES} />
        <Select label="Organise" value={form.structure} onChange={set("structure")} options={STRUCTURES} />
        <Select label="Length" value={form.length} onChange={set("length")} options={LENGTHS} />
        <Select label="Tone" value={form.tone} onChange={set("tone")} options={TONES} />
      </div>
      <label className="field">
        <span>Your own research / contribution (optional — described as yours, never cited)</span>
        <textarea rows={3} value={form.own_research} onChange={(e) => set("own_research")(e.target.value)} />
      </label>
      <label className="field">
        <span>Your own section headings, one per line (optional — skips automatic outlining)</span>
        <textarea rows={3} value={form.headings} onChange={(e) => set("headings")(e.target.value)}
          placeholder={"Introduction\nPrior approaches\nOpen problems"} />
      </label>
      <label className="field">
        <span>Extra instructions (optional)</span>
        <input type="text" value={form.instructions} onChange={(e) => set("instructions")(e.target.value)}
          placeholder="e.g. emphasise limitations; use British spelling" />
      </label>

      <div className="review-actions">
        <button type="button" className="btn-primary" onClick={planOutline}
          disabled={!form.topic.trim() || noPapers || !!busy}>
          {busy === "outline" ? "Planning…" : outline ? "Re-plan outline" : "1. Plan outline"}
        </button>
        <button type="button" className="btn-primary" onClick={writeAll}
          disabled={!form.topic.trim() || noPapers || !!busy}>
          {busy === "write" ? "Writing all sections…" : outline ? "2. Write review" : "Write review now (auto outline)"}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {outline && !draft && (
        <div className="outline">
          <h3>Outline — {outline.title}</h3>
          {outline.sections.map((s, i) => (
            <div key={i} className="outline-row">
              <input type="text" value={s.heading} onChange={(e) => updatePlan(i, { heading: e.target.value })} />
              <input type="text" value={s.goal} placeholder="What should this section achieve?"
                onChange={(e) => updatePlan(i, { goal: e.target.value })} />
              <span className="outline-actions">
                <button type="button" className="btn-link" onClick={() => movePlan(i, -1)}>↑</button>
                <button type="button" className="btn-link" onClick={() => movePlan(i, 1)}>↓</button>
                <button type="button" className="btn-link-danger" onClick={() => removePlan(i)}>Remove</button>
              </span>
            </div>
          ))}
          <button type="button" className="btn-link" onClick={addPlan}>+ Add section</button>
        </div>
      )}

      {draft && (
        <div className="draft">
          <div className="gap-panel-head">
            <h3>{draft.title}</h3>
            <span>
              <button type="button" className="btn-link" onClick={() => navigator.clipboard?.writeText(draft.markdown)}>Copy markdown</button>
              <button type="button" className="btn-link" onClick={download}>Download .md</button>
            </span>
          </div>
          {draft.warnings.length > 0 && (
            <ul className="warnings">{draft.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          )}
          {draft.sections.map((s, i) => (
            <div key={i} className="draft-section">
              <h4 className="answer-heading">{s.heading}</h4>
              <div className="answer-text">{renderRich(s.content)}</div>
              <div className="regen-row">
                <input type="text" placeholder="Feedback for this section (optional): shorter, focus on datasets…"
                  value={feedback[i] || ""} onChange={(e) => setFeedback((f) => ({ ...f, [i]: e.target.value }))} />
                <button type="button" className="btn-link" disabled={!!busy} onClick={() => regenerate(i)}>
                  {busy === `section:${i}` ? "Rewriting…" : "Regenerate"}
                </button>
              </div>
            </div>
          ))}
          {draft.references.length > 0 && (
            <div className="references">
              <h4 className="answer-heading">References</h4>
              {draft.references.map((r) => <p key={r.number} className="reference">{r.formatted}</p>)}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
