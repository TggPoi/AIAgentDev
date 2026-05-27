from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fast_app.api.chat_routes import router as chat_router
from fast_app.api.health_routes import router as health_router
from fast_app.api.rag_chat_routes import router as rag_chat_router
from fast_app.api.rag_routes import router as rag_router
from fast_app.api.stream_routes import router as stream_router
from fast_app.api.error_demo_routes import router as error_demo_router
from fast_app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(health_router)
app.include_router(chat_router)
app.include_router(rag_router)
app.include_router(error_demo_router)
app.include_router(stream_router)
app.include_router(rag_chat_router)
