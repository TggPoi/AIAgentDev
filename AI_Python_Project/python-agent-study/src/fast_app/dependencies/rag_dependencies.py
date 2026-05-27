from fastapi import Depends

from fast_app.core.config import Settings, get_settings
from fast_app.services.rag_pipeline_service import RagPipeline


def get_rag_pipeline(
    settings: Settings = Depends(get_settings),
) -> RagPipeline:
    return RagPipeline(settings=settings)