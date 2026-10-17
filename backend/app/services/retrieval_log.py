"""
检索日志、Prompt 日志、命中率统计

【模块职责】
RAG 系统的"可观测性"组件，回答三个运维问题：
  1. 检索质量如何？——记录每次检索的召回数、被阈值过滤数、耗时、
     缓存命中情况，并统计命中率/空结果率（RetrievalStats 汇总）；
  2. Prompt 构造是否合理？——记录每次问答的上下文长度、历史轮数、
     预估 token，用于诊断"上下文是否超长/检索是否足够"；
  3. 日志去哪看？——独立落盘到 retrieval.log 与 prompt.log（JSON 行，
     便于 grep/脚本分析），同时输出精简版到主日志。

【开发思路】
1. 为什么用标准 logging 模块而不是 loguru？
   loguru 是主日志；这两个专项日志希望"只写 JSON、不写其他格式"，
   用标准 logging + FileHandler 可以完全控制格式（Formatter 只放 message）。
2. RetrievalStats 用类变量（classmethod）做全局计数：
   简单场景足够（重启清零），注释里也说明了生产可换 Redis 持久化。
"""
import time
import json
from datetime import datetime
from typing import List, Optional
from loguru import logger
from app.core.config import settings

# ── 独立日志文件配置（在 main.py 之后调用 setup() 初始化）──────────────────
# 模块级变量保存 logger 实例：setup_rag_loggers 只初始化一次，
# 后续 log_retrieval/log_prompt 直接使用，避免重复创建 FileHandler
_retrieval_logger = None
_prompt_logger = None


def setup_rag_loggers():
    """初始化两个专项日志文件（在 main.py lifespan 中调用一次）。"""
    global _retrieval_logger, _prompt_logger
    import logging

    # 检索日志：独立文件、UTF-8 编码、formatter 只输出 message（即 JSON 行）
    _retrieval_logger = logging.getLogger("rag.retrieval")
    _retrieval_logger.setLevel(logging.INFO)
    # 防重复：热重载（uvicorn reload）时模块可能被重复导入，
    # 若已有 handler 就不再加，避免日志重复写入
    if not _retrieval_logger.handlers:
        fh = logging.FileHandler(f"{settings.LOG_DIR}/retrieval.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(message)s"))
        _retrieval_logger.addHandler(fh)

    # Prompt 日志：同样的模式
    _prompt_logger = logging.getLogger("rag.prompt")
    _prompt_logger.setLevel(logging.INFO)
    if not _prompt_logger.handlers:
        fh = logging.FileHandler(f"{settings.LOG_DIR}/prompt.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(message)s"))
        _prompt_logger.addHandler(fh)


class RetrievalStats:
    """内存中的检索命中率统计（重启清零，可替换为 Redis）"""
    _total: int = 0           # 总检索次数
    _cache_hits: int = 0      # 缓存命中次数
    _empty_results: int = 0   # 空结果次数
    _score_filtered: int = 0  # 被阈值过滤掉的块总数
    _total_latency_ms: float = 0.0  # 累计耗时（算平均）

    @classmethod
    def record(cls, cache_hit: bool, result_count: int,
               filtered_count: int, latency_ms: float):
        """每次检索结束后调用，累加各项计数。"""
        cls._total += 1
        if cache_hit:
            cls._cache_hits += 1
        if result_count == 0:
            cls._empty_results += 1
        cls._score_filtered += filtered_count
        cls._total_latency_ms += latency_ms

    @classmethod
    def summary(cls) -> dict:
        """汇总成可读指标（/api/system/stats 直接返回）。"""
        total = cls._total or 1   # 防止除零（还没有检索记录时）
        return {
            "total_queries":       cls._total,
            "cache_hit_rate":      round(cls._cache_hits / total, 4),
            "empty_result_rate":   round(cls._empty_results / total, 4),
            "avg_filtered_chunks": round(cls._score_filtered / total, 2),
            "avg_latency_ms":      round(cls._total_latency_ms / total, 2),
        }


def log_retrieval(
    kb_id: int,
    query: str,
    results: list,
    latency_ms: float,
    cache_hit: bool,
    strategy: str,
    filtered_count: int = 0,
):
    """
    记录一次检索：JSON 行写入 retrieval.log + 精简版进主日志 + 更新统计。
    results 是 [(Document, score), ...]，取前 3 条的分数和文件名
    用于快速判断"召回的是不是正确内容"。
    """
    if not settings.LOG_RETRIEVAL:
        return   # 开关关闭时直接跳过（性能敏感路径不做多余 IO）
    record = {
        "ts":            datetime.utcnow().isoformat(),
        "kb_id":         kb_id,
        "query":         query[:200],        # 截断，防止超长 query 撑爆日志
        "strategy":      strategy,
        "cache_hit":     cache_hit,
        "result_count":  len(results),
        "filtered_out":  filtered_count,
        "latency_ms":    round(latency_ms, 2),
        "top_scores":    [round(float(s), 4) for _, s in results[:3]] if results else [],
        "top_files":     list({r.metadata.get("filename","?") for r, _ in results[:3]}) if results else [],
    }
    if _retrieval_logger:
        _retrieval_logger.info(json.dumps(record, ensure_ascii=False))

    # 同时输出到主日志（简洁版）
    hit_tag = "CACHE_HIT" if cache_hit else "VECTOR_SEARCH"
    logger.info(
        f"[RETRIEVAL] {hit_tag} | kb={kb_id} | strategy={strategy} | "
        f"results={len(results)} | filtered={filtered_count} | "
        f"latency={latency_ms:.1f}ms | query={query[:50]!r}"
    )

    RetrievalStats.record(cache_hit, len(results), filtered_count, latency_ms)


def log_prompt(
    kb_id: int,
    question: str,
    context_length: int,
    history_turns: int,
    prompt_tokens_est: int,
):
    """记录一次 Prompt 构造信息：上下文长度/历史轮数/预估 token。"""
    if not settings.LOG_PROMPT:
        return
    record = {
        "ts":               datetime.utcnow().isoformat(),
        "kb_id":            kb_id,
        "question":         question[:200],
        "context_length":   context_length,      # 注入的检索上下文长度
        "history_turns":    history_turns,       # 历史对话轮数
        "prompt_tokens_est": prompt_tokens_est,  # 粗略估算 token 数
    }
    if _prompt_logger:
        _prompt_logger.info(json.dumps(record, ensure_ascii=False))

    logger.info(
        f"[PROMPT] kb={kb_id} | ctx_len={context_length} | "
        f"history={history_turns}turns | est_tokens={prompt_tokens_est} | "
        f"question={question[:50]!r}"
    )