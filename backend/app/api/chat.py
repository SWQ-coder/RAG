"""
对话 API - RAG 问答与会话管理

【模块职责】
RAG 问答的核心接口层，路由前缀 /api/chat：
  - 会话管理：列表、消息历史、删除会话
  - 问答：非流式（/send）与 SSE 流式（/stream）

【开发思路】
1. 为什么提供流式 + 非流式两套？
   流式（SSE）逐字返回，用户体验好（打字机效果），但实现复杂；
   非流式简单稳定，适合测试/脚本调用。本项目两个都保留。
2. 为什么流式接口在生成器结束后才存 AI 消息？
   StreamingResponse 的生成器在响应开始后异步执行，此时 FastAPI 注入的
   数据库会话可能已被关闭。所以在生成器内部用 SessionLocal() 新建会话
   保存最终答案——这是流式接口保存数据的经典坑位。
3. history 只取最近 20 条：控制 Prompt 长度，避免上下文无限膨胀导致
   超长和费用飙升。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional, List
from app.core.database import get_db
from app.models import Conversation, Message, KnowledgeBase
from app.schemas import ChatRequest, ConversationOut, MessageOut, ResponseModel, PageData
from app.services.rag import rag_service
from loguru import logger

router = APIRouter(prefix="/api/chat", tags=["对话"])


@router.get("/conversations", response_model=ResponseModel)
def list_conversations(
    kb_id: int = Query(...),       # 只看某个知识库下的会话
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """分页查询某知识库的会话列表，最近更新的排前面。"""
    query = db.query(Conversation).filter(Conversation.kb_id == kb_id)
    total = query.count()
    items = query.order_by(Conversation.updated_at.desc()) \
        .offset((page - 1) * page_size).limit(page_size).all()
    return ResponseModel(data=PageData(
        total=total, items=[ConversationOut.model_validate(i) for i in items],
        page=page, page_size=page_size
    ))


@router.get("/conversations/{conv_id}/messages", response_model=ResponseModel)
def get_messages(
    conv_id: int,
    db: Session = Depends(get_db),
):
    """查询会话的全部消息历史，按时间正序（前端直接按序渲染）。"""
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = db.query(Message).filter(Message.conv_id == conv_id) \
        .order_by(Message.created_at.asc()).all()   # asc：旧消息在前
    return ResponseModel(data=[MessageOut.model_validate(m) for m in messages])


@router.delete("/conversations/{conv_id}", response_model=ResponseModel)
def delete_conversation(conv_id: int, db: Session = Depends(get_db)):
    """删除会话：ORM 级联会一并删除该会话下的所有消息。"""
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.delete(conv)
    db.commit()
    return ResponseModel(message="删除成功")


@router.post("/send", response_model=ResponseModel)
async def send_message(body: ChatRequest, db: Session = Depends(get_db)):
    """发送消息（非流式）：RAG 检索 → LLM 生成 → 返回完整答案 + 引用来源。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == body.kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    # 获取或创建会话（传 conv_id 则复用，不传则按问题自动新建）
    conv = _get_or_create_conversation(db, body.kb_id, body.conv_id, body.question)

    # 拉取历史消息，让 LLM 具备多轮上下文
    history = _get_history(db, conv.id)

    # RAG 推理：rag_service.chat 内部完成"向量检索→拼上下文→调 LLM"
    try:
        answer, sources = await rag_service.chat(body.kb_id, body.question, history)
    except Exception as e:
        logger.error(f"RAG error: {e}")
        raise HTTPException(status_code=500, detail=f"推理失败: {str(e)}")

    # 用户提问与 AI 回答都持久化，刷新页面不丢历史
    user_msg = Message(conv_id=conv.id, role="user", content=body.question)
    ai_msg = Message(conv_id=conv.id, role="assistant", content=answer, sources=sources)
    db.add_all([user_msg, ai_msg])
    db.commit()
    db.refresh(ai_msg)

    return ResponseModel(data={
        "conv_id": conv.id,
        "message": MessageOut.model_validate(ai_msg),
    })


@router.post("/stream")
async def stream_message(body: ChatRequest, db: Session = Depends(get_db)):
    """发送消息（流式 SSE）：逐 token 返回，前端打字机效果。"""
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == body.kb_id).first()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    conv = _get_or_create_conversation(db, body.kb_id, body.conv_id, body.question)
    history = _get_history(db, conv.id)

    # 用户消息立即落库（AI 消息等生成结束后再存）
    user_msg = Message(conv_id=conv.id, role="user", content=body.question)
    db.add(user_msg)
    db.commit()

    # 重新拉取（把刚存的用户消息包含进历史）并提前取出 kb_id：
    # 生成器是延迟执行的，届时依赖的 ORM 对象/会话状态可能已失效
    history = _get_history(db, conv.id)
    kb_id = body.kb_id  # 提前取出，避免生成器里访问 ORM 对象

    async def event_generator():
        """
        SSE 事件生成器：把 rag_service.chat_stream 产出的每个 chunk
        原样转发给前端，同时从 chunk 流里"旁路"提取最终答案和引用来源
        （用于生成结束后持久化 AI 消息）。
        """
        import json
        full_answer = ""
        final_sources = []
        try:
            async for chunk in rag_service.chat_stream(body.kb_id, body.question, history):
                yield chunk   # 原样转发给浏览器
                # 旁路解析：done 事件带最终答案，sources 事件带引用来源。
                # 字符串匹配而不是反序列化整个流，是为了只挑特定类型事件解析
                if '"type": "done"' in chunk or '"type":"done"' in chunk:
                    try:
                        data = json.loads(chunk.replace("data: ", "").strip())
                        full_answer = data.get("data", "")
                    except Exception:
                        pass
                elif '"type": "sources"' in chunk or '"type":"sources"' in chunk:
                    try:
                        data = json.loads(chunk.replace("data: ", "").strip())
                        final_sources = data.get("data", [])
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"
        finally:
            # 生成器结束后用新 Session 保存 AI 回复，避免原 Session 已关闭的问题。
            # 这是流式接口的经典陷阱：FastAPI 注入的 db 在响应开始后可能不可用，
            # 所以这里手动开一个独立 Session 完成写入。
            if full_answer:
                from app.core.database import SessionLocal
                new_db = SessionLocal()
                try:
                    ai_msg = Message(
                        conv_id=conv.id,
                        role="assistant",
                        content=full_answer,
                        sources=final_sources,
                    )
                    new_db.add(ai_msg)
                    new_db.commit()
                except Exception as e:
                    logger.error(f"Save AI message error: {e}")
                    new_db.rollback()
                finally:
                    new_db.close()

        # 最后通知前端会话 ID（新会话首次提问时前端需要它）
        yield f"data: {json.dumps({'type': 'conv_id', 'data': conv.id})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",   # SSE 的标准 MIME
        headers={
            "Cache-Control": "no-cache",        # 禁止缓存，保证实时
            "X-Accel-Buffering": "no",          # 关闭 Nginx 缓冲，防止流被攒批
        }
    )


def _get_or_create_conversation(db: Session, kb_id: int, conv_id: Optional[int], question: str) -> Conversation:
    """会话复用逻辑：传了有效 conv_id 就复用；否则新建（标题取问题前20字）。"""
    if conv_id:
        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        if conv:
            return conv

    # 用问题前20字作为标题，方便前端会话列表展示
    title = question[:20] + "..." if len(question) > 20 else question
    conv = Conversation(kb_id=kb_id, title=title)
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _get_history(db: Session, conv_id: int) -> List[dict]:
    """取会话最近 20 条消息，转成 [{role, content}] 供 RAG 服务拼 Prompt。"""
    messages = db.query(Message).filter(Message.conv_id == conv_id) \
        .order_by(Message.created_at.asc()).limit(20).all()
    return [{"role": m.role, "content": m.content} for m in messages]
