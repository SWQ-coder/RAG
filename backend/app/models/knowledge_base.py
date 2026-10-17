"""
知识库 ORM 模型

【模块职责】
定义"知识库"表结构。知识库是系统的顶层业务实体：
用户可创建多个独立知识库（例如"技术文档库"、"人事制度库"），
每个知识库拥有自己的文档、会话，并在 ChromaDB 中对应独立的向量集合（kb_{id}）。

【开发思路】
1. 为什么不直接用 MySQL 存向量，还要单独用 ChromaDB？
   MySQL 擅长结构化数据的事务与关联查询，但"向量相似度检索"（余弦/欧氏距离
   近邻搜索）不是它的强项，性能很差。所以设计上是双存储：
   MySQL 存业务元数据（文档名、状态、会话、消息），ChromaDB 存向量本体。
2. relationship + cascade="all, delete-orphan" 的含义：
   删除知识库时，级联删除其下所有文档与会话记录（数据库层面也加了
   ondelete="CASCADE"），保证不会残留孤儿数据。
3. doc_count 是冗余计数字段：与其每次 COUNT(*)，不如维护一个整数字段，
   牺牲一点一致性换取列表页的性能；由文档服务在增删文档后更新它。
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class KBStatus(str, enum.Enum):
    """知识库状态：active=正常可用，inactive=停用（预留的开关能力）。"""
    ACTIVE = "active"
    INACTIVE = "inactive"


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"   # 对应 MySQL 表名

    # 主键：自增整数，index=True 让 WHERE id= 的查询走索引
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(200), nullable=False, comment="知识库名称")   # 必填，最长200字符
    description = Column(Text, comment="知识库描述")                    # Text 支持长文本
    icon = Column(String(10), default="📚", comment="图标emoji")       # 前端展示用
    status = Column(Enum(KBStatus), default=KBStatus.ACTIVE)
    embedding_model = Column(String(100), default="qwen3-embedding-0.6b") # 该库用的向量模型
    doc_count = Column(Integer, default=0, comment="文档数量")           # 冗余计数
    # created_at/updated_at：server_default=func.now() 让数据库写入当前时间，
    # onupdate=func.now() 保证每次 UPDATE 时自动刷新 updated_at
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # ORM 关联：一个知识库 → 多篇文档/多个会话；
    # cascade="all, delete-orphan" 表示删除知识库时连带删除关联子表数据
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="knowledge_base", cascade="all, delete-orphan")
