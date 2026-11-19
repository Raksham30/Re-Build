from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict


SectionType = Literal[
    "title", "abstract", "introduction", "related_work", "method",
    "experiments", "results", "discussion", "limitations",
    "conclusion", "references", "other"
]


class Chunk(BaseModel):
    chunk_id: str
    paper_id: str
    text: str
    section_type: SectionType
    page_start: int
    page_end: int
    order: int


class ParsedSection(BaseModel):
    section_type: SectionType
    text: str
    page_start: int
    page_end: int


class StructuredExtraction(BaseModel):
    """The fixed schema every paper gets reduced to. This is what powers
    comparisons, tables, and the literature review generator -- NOT raw
    chunk retrieval."""
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    datasets: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    key_results: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    summary: str = ""


class Workspace(BaseModel):
    workspace_id: str
    owner_uid: str
    name: str
    created_at: str
    updated_at: str


class RenameRequest(BaseModel):
    name: str


class Paper(BaseModel):
    paper_id: str
    workspace_id: str
    filename: str
    title: str = ""
    num_pages: int = 0
    status: Literal["uploaded", "parsing", "indexed", "failed"] = "uploaded"


class AskRequest(BaseModel):
    question: str
    paper_ids: list[str] | None = None  # None = search across whole library


class Citation(BaseModel):
    paper_id: str
    paper_title: str
    section_type: SectionType
    page_start: int
    page_end: int
    snippet: str


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]


class CompareRequest(BaseModel):
    paper_ids: list[str]
    dimension: Literal["methods", "datasets", "key_results", "limitations"] = "methods"


class RelationshipEdge(BaseModel):
    source: str
    target: str
    relationship: Literal["extends", "contradicts", "uses_same_dataset", "similar_topic", "cites"]
    explanation: str


class LitReviewRequest(BaseModel):
    topic: str
    paper_ids: list[str]


# ---- Feature 2: Research gap finder ----

class GapAnalysisRequest(BaseModel):
    topic: str | None = None  # optional focus; None = analyze the whole workspace


class GapAnalysisResponse(BaseModel):
    found_gap: bool
    analysis: str
    citations: list[Citation]
    caveat: str = "Based only on the papers currently in this workspace."


# ---- Feature 3: Contradiction detector ----

class ContradictionPair(BaseModel):
    paper_a_id: str
    paper_a_title: str
    claim_a: str          # exact line from paper A
    paper_a_citation: Citation
    paper_b_id: str
    paper_b_title: str
    claim_b: str          # exact line from paper B
    paper_b_citation: Citation
    explanation: str


class ContradictionRequest(BaseModel):
    paper_ids: list[str] | None = None  # None = all papers in workspace


class ContradictionResponse(BaseModel):
    contradictions: list[ContradictionPair]
    checked_pairs: int


# ---- Feature 4: Research writer ----

class ResearchWriteRequest(BaseModel):
    idea: str
    own_research: str
    instructions: str | None = None
    paper_ids: list[str] | None = None  # None = ground against whole workspace


class ResearchWriteResponse(BaseModel):
    draft: str
    citations: list[Citation]


# ---------------------------------------------------------------- Review builder
class ReviewOptions(BaseModel):
    topic: str                                   # what the review is about (or the user's research idea)
    own_research: str | None = None              # the user's own work: described as theirs, never cited
    paper_ids: list[str] | None = None           # None = all indexed papers in the workspace
    doc_type: Literal["literature_review", "related_work", "survey", "gap_section"] = "literature_review"
    structure: Literal["thematic", "chronological", "methodological"] = "thematic"
    length: Literal["short", "medium", "long"] = "medium"      # per section: ~150 / ~300 / ~500 words
    tone: Literal["academic", "concise", "accessible"] = "academic"
    sections: list[str] | None = None            # your own headings; skips automatic outlining
    instructions: str | None = None              # free-text extras ("emphasise limitations", "use British spelling")


class ReviewSectionPlan(BaseModel):
    heading: str
    goal: str = ""                               # what this section should accomplish
    paper_ids: list[str] = Field(default_factory=list)   # papers to focus on; empty = whole selection


class ReviewOutline(BaseModel):
    title: str
    sections: list[ReviewSectionPlan]


class ReviewOutlineRequest(BaseModel):
    options: ReviewOptions


class ReviewSectionRequest(BaseModel):
    options: ReviewOptions
    section: ReviewSectionPlan
    previous_headings: list[str] = Field(default_factory=list)   # so sections don't repeat each other
    feedback: str | None = None                  # "make it shorter", "focus on datasets" ...
    previous_text: str | None = None             # the version being revised (with feedback)


class ReviewSection(BaseModel):
    heading: str
    content: str                                 # markdown body; citations are [n] = reference numbers
    warnings: list[str] = Field(default_factory=list)


class ReviewReference(BaseModel):
    number: int
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    formatted: str


class ReviewAssembleRequest(BaseModel):
    options: ReviewOptions
    title: str
    sections: list[ReviewSection]


class ReviewRequest(BaseModel):
    options: ReviewOptions
    outline: ReviewOutline | None = None         # supply an edited outline to skip outlining


class ReviewDraft(BaseModel):
    title: str
    sections: list[ReviewSection]
    references: list[ReviewReference]
    markdown: str
    warnings: list[str] = Field(default_factory=list)
    # Sections with STABLE citation numbers (before renumbering). Keep these client-side: regenerate one
    # of them, then call /review/assemble again. Only filled by the one-shot /review endpoint.
    raw_sections: list[ReviewSection] = Field(default_factory=list)
