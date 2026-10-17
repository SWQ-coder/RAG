"""
对话 Pydantic Schema

【模块职责】
对话/问答相关的 API 数据模型：
  - ChatRequest：发送问题的请求体（非流式 send 与流式 stream 共用）；
  - MessageOut：单条消息出参（含引用来源）；
  - ConversationOut：会话出参（会话列表展示）。
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ChatRequest(BaseModel):
    """发送问答请求体。"""
    kb_id: int                       # 在哪个知识库检索
    conv_id: Optional[int] = None    # 会话ID：不传则自动新建会话
    question: str = Field(..., min_length=1)   # 问题内容，不能为空
    stream: bool = False             # 是否流式（当前由调用 /send 或 /stream 决定）


class MessageOut(BaseModel):
    """消息出参：包含引用来源列表 sources。"""
    id: int
    conv_id: int
    role: str                        # user / assistant
    content: str
    sources: Optional[List[Dict]] = None   # 引用文档 [{filename, page, score, content}, ...]
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    """会话出参：会话列表页展示用。"""
    id: int
    kb_id: int
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
