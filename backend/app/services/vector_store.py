"""
向量存储服务 - ChromaDB + Qwen3-Embedding-8B

【模块职责】
RAG 的"记忆仓库"：
  - 写入侧：文本 → 分块（RecursiveCharacterTextSplitter）→ 向量化（Ollama
    Embedding）→ 存入 ChromaDB（按知识库分集合 kb_{id}）；
  - 读取侧：问题向量化 → 相似度检索（similarity / MMR / hybrid 三种策略）
    → 阈值过滤 → 按相似度排序返回。

【开发思路】
1. 为什么自己包装 AsyncEmbeddingWrapper 而不直接用 OllamaEmbeddings？
   OllamaEmbeddings 是同步库（内部用 requests/httpx 阻塞调用）：
     a) FastAPI 是 asyncio 事件循环，直接在协程里调用同步阻塞方法会卡住
        整个服务——所以用 run_in_executor 丢到线程池执行；
     b) 同时把 EmbeddingCache 缓存、信号量并发控制揉进这个包装层，
        让所有 embedding 调用都自动享受缓存和限流。
2. 为什么每个知识库一个 Chroma 集合（kb_{id}）？
   检索天然按库隔离：集合隔离 = 数据隔离 + 可单独删除重建（delete_kb）。
3. 三种检索策略的意义：
   - similarity：纯向量相似度，最直接；
   - mmr（最大边际相关性）：在"相关"与"多样性"间平衡，避免召回的全是
     同一段内容的切片（max_marginal_relevance_search）；
   - hybrid：similarity 结果优先，MMR 结果补充去重，兼顾精准与召回。
4. 为什么相似度用 math.exp(-L2距离) 换算？
   ChromaDB 默认返回 L2 距离（越小越相似），0 表示完全相同。exp(-d) 把
   [0, +∞) 映射到 (0, 1]，距离为 0 → 相似度 1，便于统一阈值过滤与前端展示。
"""
import uuid
import asyncio
import time
from typing import List, Tuple, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from loguru import logger

from app.core.config import settings
from app.services.cache import embedding_cache


class AsyncEmbeddingWrapper:
    """
    将同步 OllamaEmbeddings 包装为支持：
      1. EmbeddingCache 缓存
      2. 信号量控制并发
      3. 兼容 FastAPI 已有事件循环（不再用 run_until_complete）
    """

    def __init__(self):
        self._emb: Optional[OllamaEmbeddings] = None
        # 信号量在第一次异步调用时懒初始化，避免在事件循环外创建
        self._semaphore: Optional[asyncio.Semaphore] = None

    def _get_emb(self) -> OllamaEmbeddings:
        """懒加载 OllamaEmbeddings 实例（模型首次调用时才连接）。"""
        if self._emb is None:
            self._emb = OllamaEmbeddings(
                base_url=settings.OLLAMA_BASE_URL,
                model=settings.OLLAMA_EMBEDDING_MODEL,
            )
            logger.info(f"Embedding model loaded: {settings.OLLAMA_EMBEDDING_MODEL}")
        return self._emb

    def _get_semaphore(self) -> asyncio.Semaphore:
        """懒初始化信号量，确保在事件循环内创建"""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.EMBEDDING_CONCURRENCY)
        return self._semaphore

    def _sync_embed_documents(self, texts: List[str]) -> List[List[float]]:
        """纯同步 embed，供 run_in_executor 调用"""
        return self._get_emb().embed_documents(texts)

    def _sync_embed_query(self, text: str) -> List[float]:
        """纯同步 embed query，供 run_in_executor 调用"""
        return self._get_emb().embed_query(text)

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        """带缓存的异步批量 embed（文档入库时使用）"""
        if not texts:
            return []

        # 批量查缓存：命中直接复用，只对未命中的文本调模型（省时省钱）
        cached_vectors, miss_indices = await embedding_cache.get_batch(texts)
        if not miss_indices:
            logger.debug(f"EmbeddingCache full hit: {len(texts)} texts")
            return cached_vectors  # type: ignore

        # 只请求未命中的
        miss_texts = [texts[i] for i in miss_indices]
        new_vectors = await self._async_batch_embed(miss_texts)

        # 写缓存
        await embedding_cache.set_batch(miss_texts, new_vectors)

        # 合并：未命中的位置用新向量填回，保持与入参顺序一致
        for idx, vec in zip(miss_indices, new_vectors):
            cached_vectors[idx] = vec

        logger.debug(
            f"EmbeddingCache: {len(texts)-len(miss_indices)} hits, "
            f"{len(miss_indices)} misses"
        )
        return cached_vectors  # type: ignore

    async def aembed_query(self, text: str) -> List[float]:
        """带缓存的异步单文本 embed（检索时使用）"""
        cached = await embedding_cache.get(text)
        if cached is not None:
            logger.debug("EmbeddingCache query HIT")
            return cached

        # 同步 embed 丢线程池执行，信号量限制并发；完后再写缓存
        loop = asyncio.get_event_loop()
        async with self._get_semaphore():
            vec = await loop.run_in_executor(None, self._sync_embed_query, text)

        await embedding_cache.set(text, vec)
        return vec

    async def _async_batch_embed(self, texts: List[str]) -> List[List[float]]:
        """受信号量保护的实际 embed 调用，按批分组（大文档拆小批，防止单次请求过载）"""
        result: List[List[float]] = []
        loop = asyncio.get_event_loop()
        batch_size = settings.EMBED_BATCH_SIZE

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            # 信号量：同一时刻最多 EMBEDDING_CONCURRENCY 个请求在跑，
            # 避免大量并发压垮本地 Ollama 服务
            async with self._get_semaphore():
                t0 = time.time()
                vecs = await loop.run_in_executor(
                    None, self._sync_embed_documents, batch
                )
                elapsed = (time.time() - t0) * 1000
                logger.debug(
                    f"Embed batch {i//batch_size + 1}: "
                    f"{len(batch)} texts in {elapsed:.1f}ms"
                )
            result.extend(vecs)
        return result

    # ── LangChain Embeddings 接口（同步，供 Chroma 内部调用）─────────────

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Chroma 入库时同步调用。
        此时已在 run_in_executor 的线程中，直接同步调用即可，无事件循环冲突。
        为什么还需要这个同步版？——Chroma 的 add_documents 内部会调用
        embedding_function.embed_documents，它不认识 async；所以包装类
        必须同时提供同步接口给 Chroma 用。
        """
        batch_size = settings.EMBED_BATCH_SIZE
        result = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            t0 = time.time()
            vecs = self._sync_embed_documents(batch)
            elapsed = (time.time() - t0) * 1000
            logger.debug(f"sync embed_documents batch: {len(batch)} in {elapsed:.1f}ms")
            result.extend(vecs)
        return result

    def embed_query(self, text: str) -> List[float]:
        """
        Chroma similarity_search 内部同步调用此方法。
        直接走同步接口，完全避开事件循环嵌套问题。
        缓存通过 aembed_query 在外层异步检索流程中提前处理。
        """
        return self._sync_embed_query(text)

class VectorStoreService:
    """
    向量存储服务（生产级）
    - 异步 embedding（AsyncEmbeddingWrapper）
    - 多策略检索：similarity / mmr / hybrid
    - 相似度阈值过滤
    - 唯一 chunk ID 防止重复覆盖
    """

    def __init__(self):
        self._emb_wrapper = AsyncEmbeddingWrapper()
        self._client: Optional[chromadb.PersistentClient] = None
        self._stores: dict = {}   # 缓存已打开的知识库 Chroma 句柄（避免重复连接）

    def _get_client(self) -> chromadb.PersistentClient:
        """懒加载 ChromaDB 客户端：PersistentClient 会把数据持久化到磁盘目录。"""
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=settings.CHROMA_PERSIST_DIR,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        return self._client

    def _collection_name(self, kb_id: int) -> str:
        """集合命名规则：每个知识库一个集合 kb_{id}，天然隔离。"""
        return f"kb_{kb_id}"

    def get_store(self, kb_id: int) -> Chroma:
        """获取某知识库的 Chroma 句柄（带缓存，避免重复打开）。"""
        if kb_id not in self._stores:
            self._stores[kb_id] = Chroma(
                client=self._get_client(),
                collection_name=self._collection_name(kb_id),
                embedding_function=self._emb_wrapper,   # 自定义嵌入封装（含缓存）
            )
        return self._stores[kb_id]

    def _text_splitter(self) -> RecursiveCharacterTextSplitter:
        """
        创建文档分块器。
        separators 按优先级递归切分：段落→换行→中文句末标点→英文标点→空格→字符，
        保证分块尽量落在语义完整的边界，而不是生硬截断。
        chunk_overlap 让相邻块有重叠，跨块语义不断裂。
        """
        return RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
            separators=["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " ", ""],
            length_function=len,
        )

    # ── 写入

    async def add_documents_async(
        self,
        kb_id: int,
        documents: List[Document],
        doc_id: int,
        filename: str,
    ) -> int:
        """
        异步文档入库：
        1. 文本分块
        2. 异步批量 embed（含缓存）
        3. 写入 ChromaDB（每块唯一 UUID，防止重复覆盖）
        """
        splitter = self._text_splitter()
        chunks = splitter.split_documents(documents)   # 长文本切成 chunk

        if not chunks:
            logger.warning(f"No chunks for doc_id={doc_id} filename={filename}")
            return 0

        # 设置元数据（全部 str，避免 ChromaDB filter 类型问题）：
        # doc_id/kb_id/filename 用于"按文档删除向量"和"回答溯源"；
        # chunk_index 便于排查具体块的顺序
        for i, chunk in enumerate(chunks):
            chunk.metadata.update({
                "doc_id":      str(doc_id),
                "kb_id":       str(kb_id),
                "filename":    filename,
                "chunk_index": str(i),
            })

        # 异步批量 embed：走缓存，重复文本不重复计算
        texts = [c.page_content for c in chunks]
        t0 = time.time()
        vectors = await self._emb_wrapper.aembed_documents(texts)
        embed_ms = (time.time() - t0) * 1000
        logger.info(
            f"[EMBED] doc_id={doc_id} | chunks={len(chunks)} | "
            f"embed_time={embed_ms:.1f}ms"
        )

        # 写入 ChromaDB（用唯一 UUID 作为 id）：
        # 分批（50/批）写入，避免一次性提交过多文档；UUID 保证
        # 重复处理同一文档不会因 id 冲突而报错
        store = self.get_store(kb_id)
        batch_size = 50
        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_vectors = vectors[i:i + batch_size]
            ids = [str(uuid.uuid4()) for _ in batch_chunks]
            store.add_documents(batch_chunks, ids=ids)

        logger.info(
            f"[VECTOR_STORE] Added kb={kb_id} doc_id={doc_id} "
            f"filename={filename} chunks={len(chunks)}"
        )
        return len(chunks)

    # ── 检索

    async def similarity_search_async(
        self,
        kb_id: int,
        query: str,
        k: int = None,
        strategy: str = "similarity",        # similarity | mmr | hybrid
        score_threshold: float = None,
        filter_doc_ids: Optional[List[int]] = None,
    ) -> Tuple[List[Tuple[Document, float]], int]:
        """
        异步相似度检索
        返回 (过滤后结果列表, 被阈值过滤掉的数量)
        """
        k = k or settings.TOP_K
        threshold = score_threshold if score_threshold is not None \
            else settings.RETRIEVAL_SCORE_THRESHOLD
        store = self.get_store(kb_id)

        # 可选：按 doc_id 过滤（如"只看某篇文档"的检索场景），
        # ChromaDB 的 where 条件，单值与多值写法不同
        where_filter = None
        if filter_doc_ids:
            if len(filter_doc_ids) == 1:
                where_filter = {"doc_id": str(filter_doc_ids[0])}
            else:
                where_filter = {"doc_id": {"$in": [str(d) for d in filter_doc_ids]}}

        try:
            loop = asyncio.get_event_loop()

            if strategy == "mmr":
                # MMR：最大边际相关性，减少结果冗余
                # fetch_k 多取 3 倍候选，MMR 算法内部再从候选中挑"既相关又不重复"的
                raw_docs = await loop.run_in_executor(
                    None,
                    lambda: store.max_marginal_relevance_search(
                        query, k=k, fetch_k=k * 3,
                        filter=where_filter,
                    )
                )
                # MMR 不返回 score，统一赋 1.0 占位
                raw = [(doc, 1.0) for doc in raw_docs]

            elif strategy == "hybrid":
                # Hybrid：similarity + mmr 结果合并去重，综合召回
                # 思路：相似度结果最"准"（带真实分数），MMR 结果更"广"（去冗余），
                # 两者合并 = 精准优先 + 多样性补充
                sim_results = await loop.run_in_executor(
                    None,
                    lambda: store.similarity_search_with_score(
                        query, k=k, filter=where_filter,
                    )
                )
                mmr_docs = await loop.run_in_executor(
                    None,
                    lambda: store.max_marginal_relevance_search(
                        query, k=k // 2 + 1, fetch_k=k * 2,
                        filter=where_filter,
                    )
                )
                # 合并：sim 结果优先，mmr 补充去重
                # 用 id() 判重（同文档对象只保留 sim 那份）；mmr 补充项赋 0.8 占位分
                seen = {id(d) for d, _ in sim_results}
                raw = list(sim_results)
                for doc in mmr_docs:
                    if id(doc) not in seen and len(raw) < k:
                        raw.append((doc, 0.8))  # mmr 补充结果赋 0.8 分
                        seen.add(id(doc))

            else:
                # 默认 similarity：纯向量相似度检索（带分数）
                raw = await loop.run_in_executor(
                    None,
                    lambda: store.similarity_search_with_score(
                        query, k=k, filter=where_filter,
                    )
                )

            # 相似度阈值过滤：把低相关噪声块挡在 Prompt 之外，
            # 避免 LLM 被无关内容干扰（幻觉来源之一）
            filtered = []
            filtered_out = 0
            for doc, score in raw:
                # ChromaDB 返回 L2 距离，用指数衰减转为 0~1 相似度
                import math
                sim = math.exp(-float(score))
                if sim >= threshold:
                    filtered.append((doc, sim))
                else:
                    filtered_out += 1
                    logger.debug(
                        f"[FILTER] score={score:.4f} sim={sim:.4f} < threshold={threshold} "
                        f"file={doc.metadata.get('filename', '?')} "
                        f"chunk={doc.metadata.get('chunk_index', '?')}"
                    )

            # 按相似度降序（最相关的排最前，上下文拼接顺序即答案引用顺序）
            filtered.sort(key=lambda x: x[1], reverse=True)
            return filtered, filtered_out

        except Exception as e:
            # 检索异常降级返回空结果（比抛 500 友好），同时记日志便于排查
            logger.error(f"[VECTOR_STORE] Search error kb={kb_id}: {e}")
            return [], 0

    # ── 删除 ──────────────────────────────────────────────────────────────

    def delete_documents(self, kb_id: int, doc_id: int):
        """删除某篇文档的所有向量块：按 doc_id 元数据查出 ids 再删。"""
        try:
            col = self._get_client().get_collection(self._collection_name(kb_id))
            res = col.get(where={"doc_id": str(doc_id)})
            if res and res["ids"]:
                col.delete(ids=res["ids"])
                logger.info(
                    f"[VECTOR_STORE] Deleted {len(res['ids'])} vectors "
                    f"kb={kb_id} doc_id={doc_id}"
                )
            # 删完清掉缓存的 store 句柄，强制下次重建（保证读到最新状态）
            if kb_id in self._stores:
                del self._stores[kb_id]
        except Exception as e:
            logger.error(f"[VECTOR_STORE] Delete doc error: {e}")

    def delete_kb(self, kb_id: int):
        """删除整个知识库的向量集合（连带本地缓存的句柄）。"""
        try:
            self._get_client().delete_collection(self._collection_name(kb_id))
            self._stores.pop(kb_id, None)
            logger.info(f"[VECTOR_STORE] Deleted collection kb={kb_id}")
        except Exception as e:
            logger.error(f"[VECTOR_STORE] Delete KB error: {e}")

    def get_kb_stats(self, kb_id: int) -> dict:
        """返回知识库的向量总数（详情页展示用；集合不存在时容错返回 0）。"""
        try:
            col = self._get_client().get_collection(self._collection_name(kb_id))
            return {"vector_count": col.count()}
        except Exception:
            return {"vector_count": 0}


# 全局单例
vector_service = VectorStoreService()