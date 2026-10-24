from fastapi import APIRouter, Depends, HTTPException
from fastapi import Query as Q
from fastapi.responses import Response

from .. import details
from ..ags import AGSExportError, build_ags
from ..auth import get_current_user
from ..storage import load_reports


router = APIRouter(prefix="/api/export", tags=["export"], dependencies=[Depends(get_current_user)])


@router.get("/ags")
def export_ags(project: str = Q(..., min_length=1, max_length=200, description="Project name, as in ProjectName")):
    """Download all logs of one project as an AGS4 (4.1.1) file."""
    try:
        filename, content = build_ags(project, load_reports(), depth_data=details.all_details())
    except AGSExportError as exc:
        status = 404 if str(exc).startswith("No borehole logs") else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return Response(
        content=content.encode("ascii"),
        media_type="text/plain; charset=us-ascii",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
