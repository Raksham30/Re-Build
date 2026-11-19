"""
Review builder: outline -> grounded sections -> assembled, renumbered draft.

Design:
  * Outline first (cheap "standard" tier) so the user can edit structure before any expensive
    writing happens; or supply your own headings and skip it.
  * Each section is written by the "strong" tier from (a) per-paper overviews and (b) hybrid-retrieved
    excerpts for THAT section's topic, so claims are grounded in the right passages.
  * Citations are [n] where n is a stable per-paper number (position in the selected library).
    Every [n] the model emits is checked against the papers actually shown for that section;
    unknown numbers are stripped and reported -- no invented references survive.
  * assemble() renumbers by first appearance and builds the reference list from cited papers only,
    so sections can be regenerated independently and re-assembled without any LLM call.
"""
from __future__ import annotations
import json
import re
from concurrent.futures import ThreadPoolExecutor

from app.schemas import (
    Paper, ReviewDraft, ReviewOptions, ReviewOutline, ReviewReference, ReviewSection, ReviewSectionPlan,
)
from app.services import generation, indexing, storage
from app.services.llm_router import Task

WORDS = {"short": 150, "medium": 300, "long": 500}
TONE = {
    "academic": "formal academic prose suitable for a journal paper",
    "concise": "tight, concise academic prose; no filler",
    "accessible": "clear prose for an educated non-specialist; define jargon briefly",
}
STRUCTURE = {
    "thematic": "organise the discussion by THEMES, not paper by paper",
    "chronological": "organise the discussion chronologically, showing how the approaches evolved",
    "methodological": "organise the discussion by METHOD / approach family, comparing their trade-offs",
}
MAX_SECTIONS = 8
_CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


class ReviewError(ValueError):
    """User-facing problem (e.g. no processed papers selected)."""


# ------------------------------------------------------------------ helpers
def resolve_papers(workspace_id: str, options: ReviewOptions) -> list[Paper]:
    """Indexed papers in scope, in stable library order. A paper's reference number is its 1-based position here."""
    wanted = set(options.paper_ids) if options.paper_ids is not None else None
    papers = [p for p in storage.list_papers(workspace_id)
              if p.status == "indexed" and (wanted is None or p.paper_id in wanted)]
    if not papers:
        raise ReviewError("No processed papers selected. Upload at least one PDF and wait until it shows 'indexed'.")
    return papers


def _label(p: Paper) -> str:
    return p.title or p.filename


def _overview(workspace_id: str, papers: list[Paper]) -> dict[str, str]:
    exts = storage.get_extractions(workspace_id, [p.paper_id for p in papers])
    out = {}
    for p in papers:
        e = exts.get(p.paper_id)
        if not e:
            out[p.paper_id] = "(no extracted summary)"
            continue
        parts = []
        if e.summary:
            parts.append(f"summary: {e.summary[:350]}")
        for name, vals in (("methods", e.methods), ("datasets", e.datasets),
                           ("key results", e.key_results[:3]), ("limitations", e.limitations[:2])):
            if vals:
                parts.append(f"{name}: {'; '.join(vals)}"[:400])
        out[p.paper_id] = " | ".join(parts) or "(no extracted summary)"
    return out


def _parse_json(text: str) -> dict | None:
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    a, b = t.find("{"), t.rfind("}")
    if a == -1 or b <= a:
        return None
    try:
        return json.loads(t[a:b + 1])
    except json.JSONDecodeError:
        return None


# ------------------------------------------------------------------ outline
def _fallback_outline(options: ReviewOptions) -> ReviewOutline:
    if options.doc_type == "related_work":
        heads = ["Related Work"]
    elif options.doc_type == "gap_section":
        heads = ["Limitations of Existing Work", "Identified Research Gaps"]
    else:
        heads = ["Introduction", "Background and Related Approaches", "Comparative Analysis",
                 "Open Challenges and Research Gaps", "Conclusion"]
    if options.own_research and options.doc_type != "related_work":
        heads.insert(-1 if len(heads) > 2 else len(heads), "Positioning of the Proposed Work")
    return ReviewOutline(title=options.topic[:120], sections=[ReviewSectionPlan(heading=h) for h in heads])


def build_outline(workspace_id: str, options: ReviewOptions) -> ReviewOutline:
    if options.sections:
        return ReviewOutline(title=options.topic[:120],
                             sections=[ReviewSectionPlan(heading=h.strip()) for h in options.sections if h.strip()][:MAX_SECTIONS])
    papers = resolve_papers(workspace_id, options)
    overview = _overview(workspace_id, papers)
    listing = "\n".join(f"[{i}] \"{_label(p)}\" -- {overview[p.paper_id]}" for i, p in enumerate(papers, 1))
    system = (
        "You plan the structure of a {dt} document. Reply with ONLY a JSON object, no prose, in this shape: "
        '{{"title": str, "sections": [{{"heading": str, "goal": str, "papers": [int, ...]}}]}}. '
        "Use 3-{mx} sections. 'goal' is one sentence on what the section must accomplish. 'papers' lists the "
        "numbers of the papers most relevant to that section (use only the numbers given). Do not include a "
        "References section. {struct}. {own}"
    ).format(
        dt=options.doc_type.replace("_", " "), mx=MAX_SECTIONS, struct=STRUCTURE[options.structure].capitalize(),
        own=("The author has their own research; include one section positioning it against the literature."
             if options.own_research else ""),
    )
    user = (f"Topic: {options.topic}\n" + (f"Extra instructions: {options.instructions}\n" if options.instructions else "")
            + f"\nPapers:\n{listing}")
    raw = generation.generate(system, user, max_tokens=1200, task=Task.REVIEW_OUTLINE)
    data = _parse_json(raw)
    if not data or not isinstance(data.get("sections"), list) or not data["sections"]:
        return _fallback_outline(options)

    plans = []
    for sec in data["sections"][:MAX_SECTIONS]:
        if not isinstance(sec, dict) or not str(sec.get("heading", "")).strip():
            continue
        ids = []
        for n in sec.get("papers") or []:
            if isinstance(n, int) and 1 <= n <= len(papers):
                ids.append(papers[n - 1].paper_id)
        plans.append(ReviewSectionPlan(heading=str(sec["heading"]).strip(), goal=str(sec.get("goal", "")).strip(), paper_ids=ids))
    if not plans:
        return _fallback_outline(options)
    return ReviewOutline(title=str(data.get("title") or options.topic)[:200], sections=plans)


# ------------------------------------------------------------------ sections
def validate_citations(text: str, allowed: set[int]) -> tuple[str, list[str]]:
    """Strips citation numbers the model was never given; returns (clean_text, warnings)."""
    removed: set[int] = set()

    def fix(m: re.Match) -> str:
        nums = [int(n) for n in re.split(r"\s*,\s*", m.group(1))]
        keep = [n for n in nums if n in allowed]
        removed.update(n for n in nums if n not in allowed)
        return f"[{', '.join(map(str, keep))}]" if keep else ""

    clean = _CITE.sub(fix, text)
    clean = re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r" {2,}", " ", clean))
    warnings = [f"Removed citation(s) {sorted(removed)}: not among this section's sources."] if removed else []
    return clean, warnings


def write_section(workspace_id: str, options: ReviewOptions, plan: ReviewSectionPlan,
                  previous_headings: list[str] | None = None, feedback: str | None = None,
                  previous_text: str | None = None) -> ReviewSection:
    papers = resolve_papers(workspace_id, options)
    number = {p.paper_id: i for i, p in enumerate(papers, 1)}
    scope = [p for p in papers if not plan.paper_ids or p.paper_id in set(plan.paper_ids)] or papers
    scope_ids = [p.paper_id for p in scope]
    overview = _overview(workspace_id, scope)

    chunks = indexing.search_chunks(f"{options.topic}. {plan.heading}. {plan.goal}".strip(), scope_ids, top_k=10)
    by_paper: dict[str, list[dict]] = {}
    for c in chunks:
        by_paper.setdefault(c["paper_id"], []).append(c)

    blocks = []
    for p in scope:
        lines = [f"[{number[p.paper_id]}] \"{_label(p)}\"", f"  overview: {overview[p.paper_id]}"]
        for c in by_paper.get(p.paper_id, []):
            lines.append(f"  excerpt ({c['section_type']}, p.{c['page_start']}): {c['text'][:700]}")
        blocks.append("\n".join(lines))

    words = WORDS[options.length]
    system = (
        f"You write one section of a {options.doc_type.replace('_', ' ')} in {TONE[options.tone]}. "
        f"Target about {words} words. {STRUCTURE[options.structure].capitalize()}.\n"
        "Rules:\n"
        "1. Make claims about existing work ONLY from the SOURCES given. Never use outside knowledge, and never invent "
        "numbers, datasets, or findings.\n"
        "2. Cite with the source's number in square brackets, e.g. [2] or [1, 3], right after the claim. Use only the "
        "numbers shown in SOURCES.\n"
        "3. Synthesise: compare, contrast, and point out agreement or conflict between sources rather than "
        "summarising one paper after another. If sources are thin for this section's goal, say so briefly instead of padding.\n"
        "4. The AUTHOR'S OWN RESEARCH (if given) is their original contribution: describe it as 'this work' / 'our "
        "approach'; never cite it and never attribute it to a source.\n"
        "5. Output only the section body as markdown prose: no heading, no title, no reference list."
    )
    parts = [f"Overall topic: {options.topic}", f"This section: {plan.heading}"]
    if plan.goal:
        parts.append(f"Section goal: {plan.goal}")
    if previous_headings:
        parts.append("Other sections of the document (do not repeat their content): " + "; ".join(previous_headings))
    if options.own_research:
        parts.append(f"AUTHOR'S OWN RESEARCH:\n{options.own_research}")
    if options.instructions:
        parts.append(f"Extra instructions from the author: {options.instructions}")
    if previous_text and feedback:
        parts.append(f"CURRENT VERSION OF THIS SECTION:\n{previous_text}\n\nREVISE it according to this feedback "
                     f"(keep what works, keep citations valid): {feedback}")
    elif feedback:
        parts.append(f"Author feedback to respect: {feedback}")
    parts.append("SOURCES:\n" + "\n\n".join(blocks))

    text = generation.generate(system, "\n\n".join(parts), max_tokens=int(words * 2.2) + 300, task=Task.REVIEW_SECTION)
    clean, warnings = validate_citations(text, {number[pid] for pid in scope_ids})
    return ReviewSection(heading=plan.heading, content=clean.strip(), warnings=warnings)


# ------------------------------------------------------------------ assembly
def _format_reference(n: int, title: str, authors: list[str]) -> str:
    who = ", ".join(a for a in authors if a)
    return f"[{n}] {who}. \"{title}.\"" if who else f"[{n}] \"{title}.\""


def assemble(workspace_id: str, options: ReviewOptions, title: str, sections: list[ReviewSection]) -> ReviewDraft:
    """Renumbers citations by first appearance and builds the reference list. No LLM call."""
    papers = resolve_papers(workspace_id, options)
    by_number = {i: p for i, p in enumerate(papers, 1)}

    order: list[int] = []
    for sec in sections:
        for m in _CITE.finditer(sec.content):
            for n in (int(x) for x in re.split(r"\s*,\s*", m.group(1))):
                if n in by_number and n not in order:
                    order.append(n)
    new_num = {old: i for i, old in enumerate(order, 1)}

    def remap(m: re.Match) -> str:
        nums = sorted({new_num[int(x)] for x in re.split(r"\s*,\s*", m.group(1)) if int(x) in new_num})
        return f"[{', '.join(map(str, nums))}]" if nums else ""

    final = [ReviewSection(heading=s.heading, content=_CITE.sub(remap, s.content), warnings=s.warnings) for s in sections]

    exts = storage.get_extractions(workspace_id, [by_number[o].paper_id for o in order])
    refs = []
    for old in order:
        p = by_number[old]
        authors = exts[p.paper_id].authors if p.paper_id in exts else []
        refs.append(ReviewReference(number=new_num[old], paper_id=p.paper_id, title=_label(p), authors=authors,
                                    formatted=_format_reference(new_num[old], _label(p), authors)))

    warnings = [w for s in final for w in s.warnings]
    uncited = [_label(p) for i, p in by_number.items() if i not in new_num]
    if uncited:
        warnings.append("Selected but not cited: " + "; ".join(uncited))

    md = [f"# {title}", ""]
    for s in final:
        md += [f"## {s.heading}", "", s.content, ""]
    if refs:
        md += ["## References", ""] + [r.formatted for r in refs]
    return ReviewDraft(title=title, sections=final, references=refs, markdown="\n".join(md).strip() + "\n", warnings=warnings)


def build_review(workspace_id: str, options: ReviewOptions, outline: ReviewOutline | None = None) -> ReviewDraft:
    outline = outline or build_outline(workspace_id, options)
    headings = [s.heading for s in outline.sections]

    def one(i: int) -> ReviewSection:
        others = headings[:i]          # sections before it; later ones are not written yet
        return write_section(workspace_id, options, outline.sections[i], previous_headings=others)

    with ThreadPoolExecutor(max_workers=3) as pool:
        sections = list(pool.map(one, range(len(outline.sections))))
    draft = assemble(workspace_id, options, outline.title, sections)
    draft.raw_sections = sections
    return draft
