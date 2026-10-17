"""
知识库 Pydantic Schema

【模块职责】
定义知识库相关的 API 数据模型（请求体/响应体），分三类：
  - KBCreate / KBUpdate：创建、更新时的请求体（入参校验规则）；
  - KBOut：返回给前端的知识库信息（出参，过滤掉敏感/无关字段）。

【开发思路】
为什么有了 ORM 模型（models/），还要再来一套 Schema（schemas/）？
  1. 关注点分离：ORM 模型对数据库结构负责，Schema 对 API 契约负责；
  2. 安全：ORM 模型可能包含内部字段（如外键、时间戳），用 Schema 显式
     声明哪些字段可以暴露给前端，避免越权泄露；
  3. 校验：Field(min_length=...) 在请求进入业务逻辑之前就拦截非法输入；
  4. from_attributes=True 让 Pydantic 能直接从 ORM 对象读取属性（model_validate）。
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class KBStatus(str, Enum):
    """与 ORM 的 KBStatus 对应的 API 层枚举（入参校验用）。"""
    ACTIVE = "active"
    INACTIVE = "inactive"


class KBCreate(BaseModel):
    """创建知识库的请求体：name 必填且 1~200 字符，其余可选。"""
    name: str = Field(..., min_length=1, max_length=200)  # ... 表示必填
    description: Optional[str] = None
    icon: Optional[str] = "📚"
    embedding_model: Optional[str] = "qwen3-embedding-0.6b"  # 默认向量模型


class KBUpdate(BaseModel):
    """更新知识库的请求体：全部可选（部分更新，只传要改的字段）。"""
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    status: Optional[KBStatus] = None


class KBOut(BaseModel):
    """知识库出参模型：明确列出返回给前端的字段。"""
    id: int
    name: str
    description: Optional[str]
    icon: str
    status: str
    embedding_model: str
    doc_count: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # 允许 model_validate(ORM对象) 直接从属性构建
