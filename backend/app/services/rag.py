"""
RAG 推理服务（生产级）
- QueryCache 查询缓存
- 多检索策略（similarity / mmr / hybrid）
- 检索日志 + Prompt 日志 + 命中率统计
- Context 截断保护
- 异步非阻塞

【模块职责】
RAG（检索增强生成）的核心编排逻辑，回答问题的完整流水线：
  用户问题 → 向量检索（带缓存）→ 拼装上下文（带截断保护）→
  构造 Prompt（含多轮历史）→ 调用本地 LLM → 返回答案 + 引用来源。

【开发思路】
1. RAG 相比"直接把问题丢给 LLM"强在哪？
   回答基于检索到的企业文档，而不是模型训练时的旧知识：
     - 答案可溯源（引用文件名/页码/相似度）；
     - 可回答私有/新增内容；
     - 大幅降低幻觉。
2. 为什么 prompt 要特别强调"文档是从向量库模糊检索的"？
   检索结果与问题只有"相关性"而非"必然包含答案"，模型需要先判断
   文档是否真能回答，不能答时明确说"未找到"——这条约束写在
   SYSTEM_PROMPT 规则里，是控制幻觉的关键设计。
3. 为什么 Context 要截断（MAX_CONTEXT_LENGTH）？
   LLM 有上下文窗口上限（qwen2.5:7b 约 32K token），且检索块越多
   噪声越大、响应越慢；截断保底、RERANK_TOP_K 控量，双重保护。
"""
import json
import time
from typing import List, Optional, AsyncGenerator, Tuple

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from loguru import logger

from app.core.config import settings
from app.services.vector_store import vector_service
from app.services.cache import query_cache
from app.services.retrieval_log import (
    log_retrieval, log_prompt, RetrievalStats
)


# 系统提示词：定义助手角色与回答纪律（防幻觉的三条铁律）
SYSTEM_PROMPT = """你是企业内部知识库助手，请根据以下参考文档回答用户问题。

重要规则：
1. 参考文档是从向量数据库模糊检索出来的，内容可能与问题有一定相关性，请仔细阅读后作答
2. 即使文档标题与问题措辞不完全一致，只要内容相关就应提取并回答
3. 若文档中确实完全没有任何相关内容，才回复"未找到相关信息"
4. 引用内容时标注来源：【来源：文件名】
5. 回答清晰、专业、用中文

参考文档：
{context}
"""


class RAGService:

    def _get_llm(self, streaming: bool = False) -> ChatOllama:
        """
        创建（或复用）ChatOllama 客户端。
        temperature=0.3：略降随机性，让回答更稳定/更贴合文档（RAG 场景
        需要确定性，不能每次答案都不一样）；
        num_predict=2048：限制最大生成长度，防止超时和滥输出。
        """
        return ChatOllama(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_LLM_MODEL,
            streaming=streaming,
            temperature=0.3,          # 生产环境降低随机性
            num_predict=2048,
        )

    # ── 检索（带缓存 + 日志）─────────────────────────────────────────────

    async def retrieve(
        self,
        kb_id: int,
        query: str,
        k: int = None,
        strategy: str = "similarity",
    ) -> Tuple[List[Tuple], bool]:
        """
        检索入口：QueryCache 优先 → 未命中走向量检索 → 回写缓存。
        返回 (results, cache_hit)
        results = [(Document, score), ...]
        """
        k = k or settings.TOP_K
        t0 = time.time()

        # 1. 查 QueryCache：相同问题（同库同 k）命中直接复用，
        #    跳过最耗时的向量检索，延迟可降低一个数量级
        cached = await query_cache.get(kb_id, query, k)
        if cached is not None:
            latency = (time.time() - t0) * 1000
            log_retrieval(kb_id, query, cached, latency,
                          cache_hit=True, strategy=strategy)
            return cached, True

        # 2. 向量检索：走 similarity_search_async（内部按 strategy 分派）
        results, filtered_out = await vector_service.similarity_search_async(
            kb_id=kb_id,
            query=query,
            k=k,
            strategy=strategy,
        )

        latency = (time.time() - t0) * 1000
        # 检索日志：记录耗时/召回数/被过滤数，用于后续分析检索质量
        log_retrieval(kb_id, query, results, latency,
                      cache_hit=False, strategy=strategy,
                      filtered_count=filtered_out)

        # 3. 写 QueryCache：只在有结果时缓存（空结果缓存没有意义，
        #    而且知识库更新后内容变化，缓存反而可能过期误导）
        if results:
            await query_cache.set(kb_id, query, k, results)

        return results, False

    # ── Context 构建

    def _build_context(self, results: List[Tuple]) -> Tuple[str, List[dict]]:
        """
        把检索结果拼成两样东西：
          1. context：纯文本，按 [1][2][3] 编号 + 文件名/页码/相似度 排布，
            作为 SYSTEM_PROMPT 的 {context} 注入；
          2. sources：结构化引用列表（index/filename/page/score/content 前300字），
            返回前端展示"来源溯源"。
        为什么截断？——控制注入 Prompt 的总长度，防止超窗口、防噪声干扰。
        """
        # 只取前 RERANK_TOP_K 条（已按 sim 降序）
        top_results = results[:settings.RERANK_TOP_K]

        parts = []
        sources = []
        total_len = 0   # 已累计的 context 字符数（截断用的水位线）

        for i, (doc, score) in enumerate(top_results):
            filename = doc.metadata.get("filename", "未知文件")
            page = doc.metadata.get("page", "")
            page_info = f"·第{page}页" if page else ""
            content = doc.page_content

            # 截断保护：总长度逼近 MAX_CONTEXT_LENGTH 时，
            # 剩余空间不足 100 字符就不再追加（避免塞半句话）
            if total_len + len(content) > settings.MAX_CONTEXT_LENGTH:
                remain = settings.MAX_CONTEXT_LENGTH - total_len
                if remain < 100:
                    break
                content = content[:remain] + "…"

            # 每条上下文都带编号/来源/相似度——Prompt 里强调"引用要标注来源"
            # 与此呼应：模型看到结构化来源，回答时会引用对应编号
            part = f"[{i + 1}] 【{filename}{page_info}】（相关度：{score:.2%}）\n{content}"
            parts.append(part)
            total_len += len(content)

            # 引用来源（给前端展示用）：content 只截前 300 字，避免响应体过大
            sources.append({
                "index": i + 1,
                "filename": filename,
                "page": page,
                "score": round(float(score), 4),
                "doc_id": doc.metadata.get("doc_id"),
                "content": doc.page_content[:300] + "…"
                if len(doc.page_content) > 300
                else doc.page_content,
            })

        return "\n\n---\n\n".join(parts), sources

    def _build_prompt_messages(self, history: List[dict]) -> list:
        """
        构造发给 LLM 的消息列表：
        [system 系统提示] + [最近 6 条历史对话] + [当前问题占位符]。
        为什么只取最近 6 条（3 轮）？——历史太多会挤占上下文窗口，
        且早远轮次对当前回答帮助递减；同时占位符 {question}/{context}
        由 invoke 时用实际值填充。
        """
        msgs = [("system", SYSTEM_PROMPT)]
        for msg in history[-6:]:          # 最近 3 轮
            if msg["role"] == "user":
                msgs.append(("human", msg["content"]))
            elif msg["role"] == "assistant":
                msgs.append(("ai", msg["content"]))
        msgs.append(("human", "{question}"))
        return msgs

    # ── 非流式问答 ────────────────────────────────────────────────────────

    async def chat(
        self,
        kb_id: int,
        question: str,
        history: Optional[List[dict]] = None,
        strategy: str = "similarity",
    ) -> Tuple[str, List[dict]]:
        """
        非流式问答：一次调用返回完整答案 + 引用来源。
        流程：retrieve（缓存优先检索）→ build_context（拼装/截断）→
        LCEL 链（prompt | llm | parser）→ 返回。
        """
        history = history or []

        results, _ = await self.retrieve(kb_id, question, strategy=strategy)
        context, sources = self._build_context(results)

        # Prompt 日志：记录上下文长度/历史轮数/预估 token，
        # 用于评估"Prompt 是否过大/检索内容是否够用"
        log_prompt(
            kb_id=kb_id,
            question=question,
            context_length=len(context),
            history_turns=len(history) // 2,
            prompt_tokens_est=len(context) // 2 + len(question) // 2,
        )

        # LCEL（LangChain 表达式语言）链：prompt → LLM → 字符串解析
        # prompt | llm | StrOutputParser() 就是"模板填充→模型调用→取文本"
        llm = self._get_llm(streaming=False)
        prompt = ChatPromptTemplate.from_messages(
            self._build_prompt_messages(history)
        )
        chain = prompt | llm | StrOutputParser()
        answer = await chain.ainvoke({"context": context, "question": question})
        return answer, sources

    # ── 流式问答 ─────────────────────────────────────────────────────────

    async def chat_stream(
        self,
        kb_id: int,
        question: str,
        history: Optional[List[dict]] = None,
        strategy: str = "similarity",
    ) -> AsyncGenerator[str, None]:
        """
        流式问答：按 SSE 协议逐条 yield 事件字符串（前端逐字渲染）。
        事件类型：
          - sources：引用来源（先发，前端先展示"正在引用哪些文档"）
          - token：  生成中的文本片段
          - done：   完整答案（结束标记）
        注意这里检索固定用 hybrid 策略——流式场景追求更全的召回，
        双路合并比单一 similarity 更能覆盖模糊提问。
        """
        history = history or []

        #results, cache_hit = await self.retrieve(kb_id, question, strategy=strategy)

        results, cache_hit = await self.retrieve(
            kb_id, question,
            k=settings.TOP_K,
            strategy="hybrid",  # 改为 hybrid，similarity+mmr 双路召回
        )

        context, sources = self._build_context(results)

        log_prompt(
            kb_id=kb_id,
            question=question,
            context_length=len(context),
            history_turns=len(history) // 2,
            prompt_tokens_est=len(context) // 2 + len(question) // 2,
        )

        # 先推送来源：前端立即显示引用文档，不用等生成结束
        yield f"data: {json.dumps({'type': 'sources', 'data': sources}, ensure_ascii=False)}\n\n"

        # 空结果时快速返回：明确告知"没找到"，而不是让模型硬编答案
        if not results:
            msg = "根据当前知识库内容，未找到与该问题相关的信息。"
            yield f"data: {json.dumps({'type': 'token', 'data': msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done',  'data': msg})}\n\n"
            return

        llm = self._get_llm(streaming=True)
        prompt = ChatPromptTemplate.from_messages(
            self._build_prompt_messages(history)
        )
        chain = prompt | llm | StrOutputParser()

        # astream：LLM 逐 token 生成，每来一块就 yield 一个 token 事件
        full_answer = ""
        async for chunk in chain.astream({"context": context, "question": question}):
            full_answer += chunk
            yield f"data: {json.dumps({'type': 'token', 'data': chunk}, ensure_ascii=False)}\n\n"

        # done 事件带完整答案：后端用它落库，前端用它判定结束
        yield f"data: {json.dumps({'type': 'done', 'data': full_answer}, ensure_ascii=False)}\n\n"

    # ── 工具方法 ──────────────────────────────────────────────────────────

    def test_connection(self) -> bool:
        """探测 Ollama 是否可用：调用 /api/tags（列出模型），成功即视为在线。"""
        try:
            import httpx
            r = httpx.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False


# 全局单例
rag_service = RAGService()