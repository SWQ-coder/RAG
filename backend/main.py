"""
企业内部知识库系统 - FastAPI 主程序

【模块职责】
本文件是整个 RAG 系统的"装配中心"（应用入口），它本身不实现任何业务逻辑，
只做四件事：
  1. 创建 FastAPI 应用实例，并配置全局中间件（CORS）与全局异常处理；
  2. 注册 4 个业务路由模块（知识库/文档/对话/系统），让 API 按前缀分流；
  3. 定义应用生命周期（lifespan）：启动时初始化数据库表、配置日志，关闭时清理；
  4. 提供 / 根路径的健康信息接口和本地直接运行入口（python main.py）。

【开发思路】
为什么要把"启动逻辑"放在 lifespan 而不是直接在模块顶层执行？
  - FastAPI 的 lifespan（ASGI 生命周期钩子）保证这些初始化只在服务真正启动时
    执行一次，并且与 uvicorn 的事件循环对齐；如果写在模块顶层，会在"导入时"
    就执行，导入即副作用，不利于测试和热重载（reload）。
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from loguru import logger
import sys
import os

from app.core.config import settings
from app.core.database import init_db
from app.api import kb, document, chat, system
from app.services.retrieval_log import setup_rag_loggers

# ── 全局日志配置 ──────────────────────────────────────────────
# loguru 默认自带一个 stderr handler，这里先 remove() 清掉，再按需重新添加：
#   1) sys.stdout：开发时在控制台看彩色日志，方便调试；
#   2) logs/app.log：落盘持久化，rotation 按 10MB 轮转、retention 保留 7 天，
#      避免日志文件无限膨胀占满磁盘。
logger.remove()
logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
logger.add("logs/app.log", rotation="10 MB", retention="7 days", level="INFO")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理器（FastAPI 推荐的启动/关闭钩子）。
    为什么做成异步上下文管理器：uvicorn 启动时进入（yield 之前），
    服务关闭时退出（yield 之后），天然对应"启动初始化 / 关闭清理"两个时机。
    """
    logger.info("🚀 Starting RAG System...")
    # 1. 初始化数据库：根据 ORM 模型自动建表（若表已存在则跳过）
    init_db()
    # 2. 配置 RAG 专项日志（检索日志 retrieval.log / Prompt 日志 prompt.log），
    #    与主日志分离，便于单独排查"检索质量"和"Prompt 构造"问题
    setup_rag_loggers()          # ← 新增
    logger.info(f"✅ Database initialized")
    logger.info(f"📦 LLM Model: {settings.OLLAMA_LLM_MODEL}")
    logger.info(f"🔍 Embedding Model: {settings.OLLAMA_EMBEDDING_MODEL}")
    yield
    logger.info("👋 Shutting down")




app = FastAPI(
    title="Enterprise RAG Knowledge Base",
    description="企业内部知识库系统",
    version=settings.APP_VERSION,
    lifespan=lifespan,   # 挂载生命周期钩子，启动/关闭时执行 init_db 等逻辑
)

# ── CORS 跨域中间件 ───────────────────────────────────────────
# 前端 Vue 开发服务器运行在 :3000，后端 API 在 :8000，两者端口不同，
# 浏览器会拦截跨域请求。这里允许任意来源（*），开发阶段图省事；
# 生产环境应收紧为具体域名列表，避免任意网页都能调用你的后端。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 全局异常兜底 ─────────────────────────────────────────────
# FastAPI 会自行处理 HTTPException，但业务代码中未捕获的普通异常
# （如解析失败、Ollama 超时）会直接冒泡到这里。统一拦截后：
#   1) 记录完整错误到日志，便于事后排查；
#   2) 返回统一 JSON 结构 {code, message, data}，前端解析逻辑才一致；
#    如果不拦截，FastAPI 默认返回的是一段 HTML 错误页，前端没法处理。
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": str(exc), "data": None}
    )

# ── 路由注册 ──────────────────────────────────────────────────
# 每个 router 自带 prefix（/api/kb、/api/doc、/api/chat、/api/system），
# 这里只需 include，实现"按业务域拆分文件"的模块化组织。
app.include_router(kb.router)
app.include_router(document.router)
app.include_router(chat.router)
app.include_router(system.router)


@app.get("/")
async def root():
    """根路径：返回服务基本信息，方便浏览器直接访问时快速确认服务已启动。"""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",        # Swagger 交互式 API 文档地址
    }



if __name__ == "__main__":
    # 直接 python main.py 启动的入口。
    # reload=settings.DEBUG：开发模式下开热重载（改代码自动重启），生产必须关掉；
    # host=0.0.0.0：监听所有网卡，局域网内其他机器也能访问，方便联调。
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level="info",
    )
