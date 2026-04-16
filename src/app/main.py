from contextlib import AsyncExitStack
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.app.api.routes import router
from src.app.config import settings
from src.app.graph.workflow import build_graph
from src.app.services.storage import Storage


@asynccontextmanager
async def lifespan(app: FastAPI):
    exit_stack = AsyncExitStack()
    storage = Storage(settings.db_path)
    await storage.init()

    checkpointer = None
    if settings.enable_langgraph_checkpoint:
        # LangGraph built-in SQLite checkpointer for process resume/replay.
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        checkpointer = await exit_stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(settings.checkpoint_db_path)
        )
        await checkpointer.setup()

    graph_app = build_graph(checkpointer=checkpointer)

    app.state.settings = settings
    app.state.storage = storage
    app.state.checkpointer = checkpointer
    app.state.graph_app = graph_app

    try:
        yield
    finally:
        await exit_stack.aclose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
cors_allow_origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
if not cors_allow_origins:
    cors_allow_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)
