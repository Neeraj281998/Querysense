"""
api/routes/history.py
GET /api/v1/history        — list recent analyses
GET /api/v1/history/{id}   — full response for one analysis
"""

from fastapi import APIRouter, HTTPException, Query

from api.db.history import get_recent_analyses, get_analysis_by_id

router = APIRouter(prefix="/api/v1", tags=["History"])


@router.get("/history")
async def list_history(
    limit: int = Query(default=20, ge=1, le=100, description="Number of records to return"),
):
    """
    Return the most recent query analyses, newest first.
    Each record is a lightweight summary dict.
    """
    records = await get_recent_analyses(limit=limit)
    return records


@router.get("/history/{analysis_id}")
async def get_history_item(analysis_id: int):
    """
    Return the full AnalyzeResponse JSON for a single past analysis.
    """
    data = await get_analysis_by_id(analysis_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Analysis {analysis_id} not found.")
    return data