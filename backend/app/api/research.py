from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_uid
from app.api.workspaces import require_owned_workspace
from app.schemas import (
    GapAnalysisRequest, GapAnalysisResponse,
    ContradictionRequest, ContradictionResponse,
    ResearchWriteRequest, ResearchWriteResponse,
    ReviewOutline, ReviewOutlineRequest, ReviewSection, ReviewSectionRequest,
    ReviewAssembleRequest, ReviewRequest, ReviewDraft,
)
from app.services import agent, review, storage

router = APIRouter(prefix="/workspaces/{workspace_id}/research", tags=["research"])


def _resolve_paper_ids(workspace_id: str, requested: list[str] | None) -> list[str]:
    workspace_paper_ids = {p.paper_id for p in storage.list_papers(workspace_id)}
    if requested is None:
        return list(workspace_paper_ids)
    return list(set(requested) & workspace_paper_ids)


@router.post("/gap-analysis", response_model=GapAnalysisResponse)
def gap_analysis(workspace_id: str, req: GapAnalysisRequest, uid: str = Depends(get_current_uid)):
    require_owned_workspace(workspace_id, uid)
    paper_ids = _resolve_paper_ids(workspace_id, None)
    result = agent.find_research_gaps(workspace_id, paper_ids, req.topic)
    return GapAnalysisResponse(**result)


@router.post("/contradictions", response_model=ContradictionResponse)
def contradictions(workspace_id: str, req: ContradictionRequest, uid: str = Depends(get_current_uid)):
    require_owned_workspace(workspace_id, uid)
    paper_ids = _resolve_paper_ids(workspace_id, req.paper_ids)
    if len(paper_ids) < 2:
        raise HTTPException(400, "Need at least 2 papers in this workspace to check for contradictions")
    pairs, checked = agent.find_contradictions(workspace_id, paper_ids)
    return ContradictionResponse(contradictions=pairs, checked_pairs=checked)


@router.post("/write", response_model=ResearchWriteResponse)
def write(workspace_id: str, req: ResearchWriteRequest, uid: str = Depends(get_current_uid)):
    require_owned_workspace(workspace_id, uid)
    paper_ids = _resolve_paper_ids(workspace_id, req.paper_ids)
    draft, citations = agent.write_research_draft(workspace_id, req.idea, req.own_research, req.instructions, paper_ids)
    return ResearchWriteResponse(draft=draft, citations=citations)


# ---------------------------------------------------------------- Review builder
def _review_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except review.ReviewError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/review/outline", response_model=ReviewOutline)
def review_outline(workspace_id: str, req: ReviewOutlineRequest, uid: str = Depends(get_current_uid)):
    """Step 1: propose (or echo your own) section structure. Cheap; edit it before writing."""
    require_owned_workspace(workspace_id, uid)
    return _review_call(review.build_outline, workspace_id, req.options)


@router.post("/review/section", response_model=ReviewSection)
def review_section(workspace_id: str, req: ReviewSectionRequest, uid: str = Depends(get_current_uid)):
    """Step 2: write (or revise, with feedback + previous_text) ONE section."""
    require_owned_workspace(workspace_id, uid)
    return _review_call(review.write_section, workspace_id, req.options, req.section,
                        req.previous_headings, req.feedback, req.previous_text)


@router.post("/review/assemble", response_model=ReviewDraft)
def review_assemble(workspace_id: str, req: ReviewAssembleRequest, uid: str = Depends(get_current_uid)):
    """Step 3: renumber citations, build references + markdown from your (edited) sections. No AI call."""
    require_owned_workspace(workspace_id, uid)
    return _review_call(review.assemble, workspace_id, req.options, req.title, req.sections)


@router.post("/review", response_model=ReviewDraft)
def review_full(workspace_id: str, req: ReviewRequest, uid: str = Depends(get_current_uid)):
    """One-shot: outline (unless you pass one) + every section + references."""
    require_owned_workspace(workspace_id, uid)
    return _review_call(review.build_review, workspace_id, req.options, req.outline)
