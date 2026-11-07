"""
The shared glossary of Swedish domain terms (glossary.py), for the page:

- GET /api/glossary -> {term: English explanation}, the terms in lower case as glossary.GLOSSARY holds them
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/glossary")
def glossary() -> dict[str, str]:
    """Every entry of glossary.GLOSSARY, unchanged. Needs no sign-in (it is fixed content, no user data); like every
    /api path it stays behind the access gate."""
    raise NotImplementedError
