"""
缓存层 - QueryCache + EmbeddingCache

【模块职责】
两层内存缓存，都是"以空间换时间"的性能优化：
  1. QueryCache（查询缓存）：相同问题在 TTL 内不重复检索向量库，
     直接复用上次的检索结果，大幅降低延迟（向量检索是耗时大头）；
  2. EmbeddingCache（向量缓存）：文本 → 向量的计算结果是确定性的
     （模型不变则结果不变），缓存后同一文本（如重复的分块）不再重复调用
     嵌入模型，TTL 设为永不过期。

【开发思路】
1. 为什么用 LRU（最近最少使用）淘汰？
   缓存容量有限（QUERY_CACHE_MAX_SIZE=500），需要淘汰策略。
   LRU 假设"最近用过的数据短期内还会再用"，对问答场景（用户反复问
   相似问题）命中率高。实现用 OrderedDict——字典保持插入顺序，
   get 时 move_to_end 标记"最近使用"，满了 popitem(last=False) 淘汰最久未用的。
2. 为什么加 asyncio.Lock？
   多协程并发访问同一缓存时，读改写（get→move_to_end、set→pop）不是原子的，
   加锁避免竞态；协程间锁不阻塞事件循环，只是串行化临界区。
3. key 设计：query 用 md5（内容短，碰撞风险可接受），embedding 用 sha256
   （文本更长更安全）。前缀 "q:" / "e:" 用于按类型批量清理（clear_prefix）。
"""
import time
import hashlib
import asyncio
from collections import OrderedDict
from typing import Optional, List, Tuple
from loguru import logger
from app.core.config import settings


class LRUCache:
    """线程安全 LRU 缓存（基于 OrderedDict）"""

    def __init__(self, max_size: int, ttl: int = 0):
        self._cache: OrderedDict = OrderedDict()   # key -> (value, 时间戳)
        self._max_size = max_size                   # 容量上限
        self._ttl = ttl          # 0 表示永不过期（秒）
        self._hits = 0           # 命中计数（统计用）
        self._misses = 0         # 未命中计数
        self._lock = asyncio.Lock()   # 协程安全锁

    async def get(self, key: str):
        """读取缓存：命中则移动到末尾（LRU 标记）+ 统计；过期/未命中返回 None。"""
        async with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            value, ts = self._cache[key]
            # TTL 过期检查：过期即删除并视为未命中
            if self._ttl > 0 and (time.time() - ts) > self._ttl:
                del self._cache[key]
                self._misses += 1
                return None
            # LRU：移到末尾
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    async def set(self, key: str, value):
        """写入缓存：已存在则更新并移到末尾；超出容量淘汰最久未用的（头部）。"""
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)   # 更新也算"最近使用"
            self._cache[key] = (value, time.time())
            if len(self._cache) > self._max_size:
                # popitem(last=False) 从头部弹出最久未使用的键值对（LRU 淘汰）
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug(f"Cache evicted key: {evicted_key[:32]}...")

    async def delete(self, key: str):
        """删除单个键（文档删除时同步清掉相关缓存）。"""
        async with self._lock:
            self._cache.pop(key, None)

    async def clear_prefix(self, prefix: str):
        """清除指定前缀的所有缓存（知识库更新时调用）"""
        async with self._lock:
            keys = [k for k in self._cache if k.startswith(prefix)]
            for k in keys:
                del self._cache[k]
            if keys:
                logger.info(f"Cache cleared {len(keys)} keys with prefix={prefix}")

    def stats(self) -> dict:
        """缓存统计：容量、命中数、命中率（供 /api/system/stats 展示）。"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }


class QueryCache:
    """
    查询结果缓存
    key = kb_id + query 文本的 hash
    value = (sources list, context str)
    缓存的是"检索结果"而不是"最终回答"：知识库内容不变时，
    同一问题的检索结果必然相同，直接复用省掉一次向量检索。
    """

    def __init__(self):
        # 复用 LRUCache 实现，带 TTL（默认 300 秒）
        self._cache = LRUCache(
            max_size=settings.QUERY_CACHE_MAX_SIZE,
            ttl=settings.QUERY_CACHE_TTL,
        )

    def _make_key(self, kb_id: int, query: str, k: int) -> str:
        """生成缓存键：知识库 + 召回数 + 规范化问题文本（去空白/小写）。"""
        raw = f"{kb_id}:{k}:{query.strip().lower()}"
        return "q:" + hashlib.md5(raw.encode()).hexdigest()

    async def get(self, kb_id: int, query: str, k: int):
        key = self._make_key(kb_id, query, k)
        result = await self._cache.get(key)
        if result is not None:
            logger.debug(f"QueryCache HIT | kb={kb_id} query={query[:30]!r}")
        return result

    async def set(self, kb_id: int, query: str, k: int, value):
        key = self._make_key(kb_id, query, k)
        await self._cache.set(key, value)

    async def invalidate_kb(self, kb_id: int):
        """知识库文档更新后清除对应缓存（防止旧内容被命中）。"""
        await self._cache.clear_prefix(f"q:")
        logger.info(f"QueryCache invalidated for kb_id={kb_id}")

    def stats(self) -> dict:
        return self._cache.stats()


class EmbeddingCache:
    """
    Embedding 向量缓存
    key = 文本 hash，value = embedding vector list
    embedding 是纯计算结果，TTL 设为永不过期（模型不变则结果不变）
    """

    def __init__(self):
        self._cache = LRUCache(
            max_size=settings.EMBEDDING_CACHE_MAX_SIZE,
            ttl=0,  # 永不过期
        )

    def _make_key(self, text: str) -> str:
        # sha256 对长文本更安全，前缀 e: 便于批量清理
        return "e:" + hashlib.sha256(text.encode()).hexdigest()

    async def get(self, text: str) -> Optional[List[float]]:
        return await self._cache.get(self._make_key(text))

    async def set(self, text: str, vector: List[float]):
        await self._cache.set(self._make_key(text), vector)

    async def get_batch(self, texts: List[str]) -> Tuple[List[Optional[List[float]]], List[int]]:
        """批量获取，返回 (vectors列表含None占位, 未命中的索引列表)"""
        results = []
        miss_indices = []
        for i, text in enumerate(texts):
            v = await self.get(text)
            results.append(v)
            if v is None:
                miss_indices.append(i)   # 只对未命中的文本重新计算
        return results, miss_indices

    async def set_batch(self, texts: List[str], vectors: List[List[float]]):
        """批量写入（配合 get_batch 的未命中结果）。"""
        for text, vec in zip(texts, vectors):
            await self.set(text, vec)

    def stats(self) -> dict:
        return self._cache.stats()


# 全局单例
query_cache = QueryCache()
embedding_cache = EmbeddingCache()