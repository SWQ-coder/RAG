"""
文档 Pydantic Schema

【模块职责】
文档相关的 API 数据模型：
  - DocOut：文档出参（列表页/详情页展示字段）；
  - LocalPathImport：本地路径导入的请求体。
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class DocStatus(str, Enum):
    """与 ORM 的 DocStatus 对应的 API 层枚举。"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocOut(BaseModel):
    """文档出参模型：供前端列表展示。"""
    id: int
    kb_id: int
    filename: str
    file_type: Optional[str]
    file_size: int
    status: str
    error_msg: Optional[str]          # 失败原因（前端红色提示）
    chunk_count: int
    char_count: int
    source_type: str                  # upload(上传)/local_path(本地导入)
    created_at: datetime

    class Config:
        from_attributes = True


class LocalPathImport(BaseModel):
    """本地路径导入请求体：告诉后端去扫描服务器上的哪个目录/文件。"""
    kb_id: int
    path: str = Field(..., description="本地文件或目录路径")
    recursive: bool = Field(default=True, description="是否递归扫描子目录")
