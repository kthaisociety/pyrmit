import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from db.database import get_db
from dependencies import get_current_user
from agents.law_agent import LawAgent
from agents.document_agent import DocumentAgent
from agents.orchestrator import Orchestrator
from agents.parsers import parse_query
import models
from observability import get_openai_client
import schemas

router = APIRouter()

client = get_openai_client()


@router.post("/analyze", response_model=schemas.AnalyzeResponse)
def analyze(
    request: schemas.AnalyzeRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Run multi-agent feasibility analysis on a development query."""

    location = request.location
    project_type = request.project_type
    units = request.units

    # If a free-text query is provided, parse it to fill in missing fields
    if request.query:
        parsed = parse_query(request.query)
        location = location or parsed.get("location")
        project_type = project_type or parsed.get("project_type")
        units = units or parsed.get("units")

    if not location or not units:
        raise HTTPException(
            status_code=400,
            detail="Could not determine location and units. Provide them explicitly or rephrase your query.",
        )

    project_type = project_type or "residential"

    law_agent = LawAgent(db, client)
    document_agent = DocumentAgent(db, client)
    orchestrator = Orchestrator(law_agent, document_agent)

    result = orchestrator.analyze(location, project_type, units)

    return schemas.AnalyzeResponse(
        feasibility=result["feasibility"],
        confidence=result["confidence"],
        summary=result["summary"],
        law_findings=result["law_findings"],
        case_findings=result["case_findings"],
        requirements=result["requirements"],
        timeline=result.get("timeline"),
        next_steps=result["next_steps"],
    )
