"""
会话 & 消息 ORM 模型

【模块职责】
定义"会话"和"消息"两张表，实现 RAG 问答的多轮对话能力：
  - Conversation（会话）：一次连续对话的容器，属于某个知识库；
  - Message（消息）：会话里的每一条 user/assistant 消息，含回答引用的来源。

【开发思路】
1. 为什么会话要关联知识库？
   RAG 问答必须限定在某个知识库内检索，因此会话挂在知识库下面，
   切换知识库 = 切换检索范围 = 换一批会话记录。
2. 为什么要持久化消息（而不是只存在前端内存）？
   刷新页面后历史对话不丢失；同时后端把最近 N 轮历史拼进 Prompt，
   让模型能"记住"上下文，实现连贯的多轮问答。
3. sources 字段存 JSON：回答时的引用来源列表（文件名、页码、相似度），
   前端据此展示"来源溯源"，这是 RAG 相比纯大模型问答的重要卖点。
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Conversation(Base):
    """一次多轮对话会话。"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # 外键：会话属于哪个知识库；知识库删除时连带删除会话
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), default="新对话")   # 用首条问题的前20字自动生成
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # ORM 关联：会话 → 知识库（反向）、会话 → 消息（级联删除）
    knowledge_base = relationship("KnowledgeBase", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """会话中的单条消息（用户提问或 AI 回答）。"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # 外键：属于哪个会话；会话删除时连带删除消息
    conv_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False, comment="user/assistant")  # 消息角色
    content = Column(Text, nullable=False)                                # 消息正文
    sources = Column(JSON, comment="引用来源")   # AI 回答时携带的引用文档列表
    tokens = Column(Integer, default=0)          # 预估 token 数（留作统计/计费用）
    created_at = Column(DateTime, server_default=func.now())

    # 反向关联：消息 → 所属会话
    conversation = relationship("Conversation", back_populates="messages")
