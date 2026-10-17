"""
文档 ORM 模型

【模块职责】
定义"文档"表结构。文档是知识库的内容载体：用户上传/导入的每个文件
对应一条记录，记录文件的存储位置、类型、大小、处理状态、分块统计等。

【开发思路】
1. 为什么状态（status）单独定义成枚举类？
   文档处理是异步的（上传后由后台任务解析+向量化），前端列表页需要根据
   状态展示"待处理/处理中/已完成/失败"并配合轮询刷新，枚举让状态值
   可读且不可能写错字符串。
2. 为什么要记录 chunk_count / char_count？
   向量化后文档会被切分成多个 chunk 写入 ChromaDB，这两个字段用于
   列表展示和健康检查（如排查"某文档为什么检索不到"——大概率是
   分块数为 0 或处理失败）。
3. meta_info 用 JSON 类型：解析器返回的结构化元数据（页数、总字符、
   每页内容等）直接整存，无需设计额外字段，灵活应对不同文件格式。
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, BigInteger, ForeignKey, Enum, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import enum


class DocStatus(str, enum.Enum):
    """文档处理状态机：pending(待处理) → processing(处理中) → completed(完成) / failed(失败)"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    # 外键：属于哪个知识库；ondelete="CASCADE" 保证知识库删除时连带删除文档
    kb_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(500), nullable=False, comment="原始文件名")
    file_path = Column(String(1000), comment="存储路径")     # 在 uploads/kb_{id}/ 下
    file_type = Column(String(50), comment="文件类型")       # pdf/word/excel/text/image
    file_size = Column(BigInteger, default=0, comment="文件大小(bytes)")  # BigInteger 防大文件溢出
    status = Column(Enum(DocStatus), default=DocStatus.PENDING)
    error_msg = Column(Text, comment="错误信息")              # 处理失败时记录原因
    chunk_count = Column(Integer, default=0, comment="分块数量")  # 向量化后的 chunk 数
    char_count = Column(Integer, default=0, comment="字符数量")   # 解析出的总字符数
    meta_info = Column(JSON, comment="元数据")               # 解析器返回的扩展信息
    source_type = Column(String(20), default="upload", comment="来源: upload/local_path")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 反向关联：文档 → 所属知识库（与 KnowledgeBase.documents 配对）
    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
