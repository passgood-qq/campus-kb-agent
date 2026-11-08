"""FastAPI 入口。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings
from app.services import db

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    db.init_pool()
    log.info("服务启动完成")
    yield
    db.close_pool()
    log.info("服务已关闭")


app = FastAPI(title="campus-kb-agent", version="0.1.0", lifespan=lifespan)
app.include_router(router)
