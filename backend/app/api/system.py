"""
系统状态 API（含检索统计、缓存状态）

【模块职责】
系统运维与诊断接口，路由前缀 /api/system：
  - /health：健康检查（含 Ollama 连接状态），前端侧边栏轮询用它显示状态灯；
  - /stats：检索命中率、缓存命中率等运行指标；
  - /cache/clear：手动清缓存（文档更新后调用）；
  - /models：列出 Ollama 本地已安装的模型。

【开发思路】
这些接口是给"人"和"前端"看的运维信息，全部只读、不涉及业务数据，
放独立 router 避免污染业务 API 的语义。
"""
import httpx
from fastapi import APIRouter
from app.core.config import settings
from app.services.rag import rag_service
from app.services.cache import query_cache, embedding_cache
from app.services.retrieval_log import RetrievalStats

router = APIRouter(prefix="/api/system", tags=["系统"])


@router.get("/health")
async def health_check():
    """
    健康检查：探测 Ollama 是否可达。
    前端 App.vue 每 30 秒轮询一次，据此渲染"Ollama 已连接/未连接"。
    """
    ollama_ok = rag_service.test_connection()
    return {
        "status":          "healthy",
        "ollama":          ollama_ok,
        "llm_model":       settings.OLLAMA_LLM_MODEL,
        "embedding_model": settings.OLLAMA_EMBEDDING_MODEL,
        "version":         settings.APP_VERSION,
    }


@router.get("/stats")
async def get_stats():
    """检索命中率 + 缓存状态：用于观察 RAG 检索质量与缓存收益。"""
    return {
        "retrieval": RetrievalStats.summary(),       # 检索统计（命中率/耗时/空结果率）
        "query_cache":     query_cache.stats(),      # 查询缓存命中情况
        "embedding_cache": embedding_cache.stats(),  # 向量缓存命中情况
    }


@router.post("/cache/clear")
async def clear_cache(kb_id: int = None):
    """手动清除缓存（文档更新后调用）：清某个库或全局。"""
    if kb_id:
        await query_cache.invalidate_kb(kb_id)
    else:
        await query_cache._cache.clear_prefix("q:")
    return {"message": "缓存已清除"}


@router.get("/models")
async def list_models():
    """列出 Ollama 已安装的模型名（调用 Ollama 的 /api/tags）。"""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5
            )
            return {"models": [m["name"] for m in r.json().get("models", [])]}
    except Exception as e:
        # Ollama 不可达时降级返回空列表+错误信息，不让系统接口报 500
        return {"models": [], "error": str(e)}