"""The Database tab's Corpus panel (issue #114, corpus_admin.py). Owners act; developers read the status.

- GET    /api/corpus                          active and previous version, the job, unfinished uploads, history
- POST   /api/corpus/uploads                  start (or resume) an upload: {file_name, size, manifest}
- GET    /api/corpus/uploads/{id}             its state: received bytes, part size
- PUT    /api/corpus/uploads/{id}?offset=N    one part (raw bytes) at that offset
- DELETE /api/corpus/uploads/{id}             discard it
- POST   /api/corpus/uploads/{id}/restore     start the replace job of a complete upload
- POST   /api/corpus/rollback                 the previous version goes live again
- GET    /api/corpus/manifest                 the active corpus's manifest
- POST   /api/corpus/download-link            a link valid 5 minutes for the browser's own download
- GET    /api/corpus/download?token=          pg_dump -Fc --compress=zstd:3 -n corpus, streamed
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import corpus_admin
import models
from corpus_admin import CorpusError
from db.database import get_db
from dependencies import require_owner, require_staff
from localrag.corpus_dump import InvalidManifest

router = APIRouter()


class UploadRequest(BaseModel):
    file_name: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    manifest: dict


def _refused(error: Exception) -> HTTPException:
    if isinstance(error, InvalidManifest):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(status_code=getattr(error, "status", 409), detail=str(error))


@router.get("/corpus")
def corpus_status(db: Session = Depends(get_db), _user: models.User = Depends(require_staff)) -> dict:
    try:
        return corpus_admin.status(db)
    except CorpusError as error:
        raise _refused(error) from None


@router.post("/corpus/uploads")
def create_upload(request: UploadRequest, user: models.User = Depends(require_owner)) -> dict:
    try:
        return corpus_admin.create_upload(request.file_name, request.size, request.manifest, user)
    except (CorpusError, InvalidManifest) as error:
        raise _refused(error) from None


@router.get("/corpus/uploads/{upload_id}")
def get_upload(upload_id: str, _user: models.User = Depends(require_owner)) -> dict:
    try:
        return corpus_admin.upload_state(upload_id)
    except CorpusError as error:
        raise _refused(error) from None


@router.put("/corpus/uploads/{upload_id}")
async def put_part(upload_id: str, request: Request, offset: int = Query(ge=0),
                   _user: models.User = Depends(require_owner)) -> dict:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > corpus_admin.part_bytes():
        raise HTTPException(status_code=413, detail=f"A part is at most {corpus_admin.part_bytes():,} bytes")
    data = await request.body()
    try:
        return await run_in_threadpool(corpus_admin.write_part, upload_id, offset, data)
    except CorpusError as error:
        raise _refused(error) from None


@router.delete("/corpus/uploads/{upload_id}")
def delete_upload(upload_id: str, _user: models.User = Depends(require_owner)) -> dict:
    try:
        corpus_admin.discard_upload(upload_id)
    except CorpusError as error:
        raise _refused(error) from None
    return {"deleted": upload_id}


@router.post("/corpus/uploads/{upload_id}/restore")
def restore_upload(upload_id: str, db: Session = Depends(get_db), user: models.User = Depends(require_owner)) -> dict:
    try:
        return corpus_admin.history_row(corpus_admin.start_replace(db, upload_id, user))
    except CorpusError as error:
        raise _refused(error) from None


@router.post("/corpus/rollback")
def rollback(db: Session = Depends(get_db), user: models.User = Depends(require_owner)) -> dict:
    try:
        return corpus_admin.history_row(corpus_admin.rollback(db, user))
    except CorpusError as error:
        raise _refused(error) from None


@router.get("/corpus/manifest")
def manifest(_user: models.User = Depends(require_owner)) -> dict:
    try:
        return corpus_admin.active_manifest()
    except CorpusError as error:
        raise _refused(error) from None


@router.post("/corpus/download-link")
def download_link(user: models.User = Depends(require_owner)) -> dict:
    return {"url": f"/api/corpus/download?token={corpus_admin.download_token(user)}",
            "expires_minutes": corpus_admin.DOWNLOAD_TOKEN_MINUTES}


@router.get("/corpus/download")
def download(token: str = Query(...), db: Session = Depends(get_db)) -> StreamingResponse:
    """A plain link (the browser saves the file itself): the token from /download-link stands in for the bearer."""
    try:
        user = corpus_admin.download_user(db, token)
        ops = corpus_admin.get_ops()
        meta = ops.meta(corpus_admin.CORPUS_SCHEMA)
        if not meta:
            raise CorpusError("There is no active corpus", 404)
    except CorpusError as error:
        raise _refused(error) from None
    name = corpus_admin.download_name(meta)
    db.add(models.CorpusVersion(action="download", status="done", user_id=user.id, user_email=user.email,
                                file_name=name, model=meta.get("model"), chunks=meta.get("chunks"),
                                kommuner=len(meta.get("kommuner") or []), built=str(meta.get("built")),
                                detail="Download started", finished_at=datetime.now(UTC)))
    db.commit()
    return StreamingResponse(corpus_admin.stream_dump(ops.dump_command()), media_type="application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})
