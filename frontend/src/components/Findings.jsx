function pages(c) {
  return c.page_end !== c.page_start ? `${c.page_start}–${c.page_end}` : `${c.page_start}`;
}

function Quote({ title, claim, citation }) {
  return (
    <div className="citation-card">
      <span className="citation-source">
        {title} — {citation.section_type}, p.{pages(citation)}
      </span>
      <p className="citation-snippet">“{claim}”</p>
    </div>
  );
}

export function ContradictionCard({ c }) {
  return (
    <div className="finding-card">
      <p className="finding-explanation">{c.explanation}</p>
      <div className="finding-pair">
        <Quote title={c.paper_a_title} claim={c.claim_a} citation={c.paper_a_citation} />
        <Quote title={c.paper_b_title} claim={c.claim_b} citation={c.paper_b_citation} />
      </div>
    </div>
  );
}

// Findings the backend produced automatically when papers were uploaded.
export function FlagsPanel({ flags, onStatus }) {
  const visible = flags.filter((f) => f.type === "contradiction" && f.payload?.claim_a);
  if (visible.length === 0) return null;
  return (
    <section className="panel flags-panel">
      <h2>
        Possible contradictions found on upload{" "}
        <span className="badge">{visible.filter((f) => f.status === "new").length} new</span>
      </h2>
      {visible.map((f) => (
        <div key={f.flag_id} className={`flag-row flag-row--${f.status}`}>
          <ContradictionCard c={f.payload} />
          <span className="flag-actions">
            {f.status === "new" && (
              <button type="button" className="btn-link" onClick={() => onStatus(f.flag_id, "seen")}>
                Mark seen
              </button>
            )}
            <button type="button" className="btn-link-danger" onClick={() => onStatus(f.flag_id, "dismissed")}>
              Dismiss
            </button>
          </span>
        </div>
      ))}
    </section>
  );
}
