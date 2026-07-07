"""/capture — file a one-liner to the DB without it becoming more work than the thought."""
from fastapi import APIRouter, Depends

from app.capture import create_capture
from app.deps import require_token
from app.schemas import CaptureRequest, CaptureResponse

router = APIRouter()


@router.post("/capture", response_model=CaptureResponse)
async def capture(req: CaptureRequest, _: None = Depends(require_token)) -> CaptureResponse:
    capture_id = await create_capture(req.text, source="api")
    return CaptureResponse(id=capture_id)
