"""
文档处理服务 - 协调文档解析、分块、向量化

【模块职责】
文档处理的"指挥中枢"：把一条文档从"磁盘上的文件"变成"可检索的向量"。
它不自己实现解析/向量化细节，而是协调三个组件：
  - parser（解析器）：文件 → 纯文本（LangChain Document 列表）；
  - vector_service（向量服务）：文本 → 分块 → 向量 → 写入 ChromaDB；
  - 自身：管理处理状态机（PENDING→PROCESSING→COMPLETED/FAILED）、
    维护 MySQL 记录与知识库计数、删除时清理三处数据。

【开发思路】
1. 为什么单独建一个 service 而不是写在 API 层？
   API 层 upload/import-path/reprocess 三个接口都要触发"处理文档"，
   且本地导入（import_from_path）也要复用同一套解析入库逻辑——
   抽成 service 方法避免三处重复代码。
2. 为什么 process_document 是 async 且接收 db 参数？
   它在 FastAPI BackgroundTasks 中执行，接收由调用方传入的 Session；
   async 是因为内部要 await vector_service.add_documents_async
   （embedding 是 IO 密集的异步操作）。
3. 状态机的作用：前端列表页轮询 status 字段刷新展示，
   失败时 error_msg 记录原因，支持 reprocess 一键重跑。
"""
import os
import shutil
from pathlib import Path
from typing import Optional
from sqlalchemy.orm import Session
from loguru import logger
from app.core.config import settings
from app.models import Document, KnowledgeBase, DocStatus
from app.services.parser import parser
from app.services.vector_store import vector_service


class DocumentService:
    """文档处理服务"""

    def get_upload_path(self, kb_id: int, filename: str) -> str:
        """
        生成文件存储路径。
        为什么按知识库建子目录（uploads/kb_{id}/）？
        ——方便按库管理磁盘文件、删除库时整目录清理、也避免不同库同名冲突。
        """
        kb_dir = os.path.join(settings.UPLOAD_DIR, f"kb_{kb_id}")
        os.makedirs(kb_dir, exist_ok=True)
        return os.path.join(kb_dir, filename)

    def is_supported_file(self, filename: str) -> bool:
        """按扩展名白名单判断文件是否可处理（与 settings.ALLOWED_EXTENSIONS 一致）。"""
        ext = Path(filename).suffix.lower().lstrip(".")
        return ext in settings.allowed_extensions_list

    async def process_document(
        self,
        db: Session,
        doc_id: int,
    ):
        """
        后台处理文档：解析 + 向量化。
        完整流水线：状态置 PROCESSING → parser.parse 抽文本 → 异步向量化
        → 状态置 COMPLETED + 记录分块/字符统计 → 刷新知识库文档计数。
        任一步失败都会把状态置 FAILED 并记录错误，供前端展示与 reprocess 重试。
        """
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            logger.error(f"Document not found: {doc_id}")
            return

        # 更新状态为处理中（前端轮询时能看到"处理中"）
        doc.status = DocStatus.PROCESSING
        db.commit()

        try:
            # 1. 解析文档：文件 → 一段段文本（LangChain Document 列表）+ 元信息
            documents, meta = parser.parse(doc.file_path, doc.filename)

            # 2. 向量化存储（异步）：
            #    传入 kb_id/doc_id/filename 是为了给每个向量块打上归属元数据
            #    （后续按文档删除向量、以及回答时溯源都要用到）。
            #    注：原实现有同步版 add_documents 调用被注释掉，统一走异步版。
            chunk_count = await vector_service.add_documents_async(
                kb_id=doc.kb_id,
                documents=documents,
                doc_id=doc.id,
                filename=doc.filename,
            )

            # 3. 更新文档状态：成功则记录分块数/总字符数/解析元数据
            doc.status = DocStatus.COMPLETED
            doc.chunk_count = chunk_count
            doc.char_count = meta.get("total_chars", 0)
            doc.meta_info = meta
            db.commit()

            # 4. 更新知识库文档计数（冗余字段，保持与真实 completed 数一致）
            self._update_kb_doc_count(db, doc.kb_id)
            logger.info(f"Document processed: {doc.filename}, chunks={chunk_count}")

        except Exception as e:
            # 失败也要落库：状态置 FAILED + 截断的错误信息（最长500字符防撑爆字段）
            logger.error(f"Error processing document {doc_id}: {e}")
            doc.status = DocStatus.FAILED
            doc.error_msg = str(e)[:500]
            db.commit()

    def _update_kb_doc_count(self, db: Session, kb_id: int):
        """重算知识库的已完成文档数并写回冗余字段 doc_count。"""
        from app.models import DocStatus
        count = db.query(Document).filter(
            Document.kb_id == kb_id,
            Document.status == DocStatus.COMPLETED
        ).count()
        db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).update(
            {"doc_count": count}
        )
        db.commit()

    async def import_from_path(
        self,
        db: Session,
        kb_id: int,
        path: str,
        recursive: bool = True,
    ) -> list:
        """
        从服务器本地路径导入文件（单文件或目录）。
        与上传的差别：源文件在服务器上，因此是"复制"到 uploads 目录
        而不是"接收上传字节"；之后走完全相同的处理流水线。
        注意：这里直接 await process_document（前台任务场景），
        与上传接口的 BackgroundTasks 触发方式不同，但最终都进同一条处理链路。
        """
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        # 展开路径：单文件 → [该文件]；目录 → 按 recursive 决定是否递归 glob
        files = []
        if path_obj.is_file():
            files = [path_obj]
        elif path_obj.is_dir():
            pattern = "**/*" if recursive else "*"
            files = [f for f in path_obj.glob(pattern) if f.is_file()]
        else:
            raise ValueError(f"Invalid path: {path}")

        doc_ids = []
        for f in files:
            # 白名单之外的文件跳过（比如目录里的图片若 OCR 不可用也会在这里被过滤）
            if not self.is_supported_file(f.name):
                logger.warning(f"Skipping unsupported file: {f.name}")
                continue

            # 复制文件到上传目录（如果目标路径恰好是同一文件则跳过复制）
            dest_path = self.get_upload_path(kb_id, f.name)
            if str(f) != dest_path:
                shutil.copy2(str(f), dest_path)

            # 创建文档记录：来源标记 local_path，状态 PENDING 待处理
            doc = Document(
                kb_id=kb_id,
                filename=f.name,
                file_path=dest_path,
                file_type=parser.get_file_type(f.name),
                file_size=f.stat().st_size,
                source_type="local_path",
                status=DocStatus.PENDING,
            )
            db.add(doc)
            db.flush()
            doc_ids.append(doc.id)

        db.commit()

        # 异步处理所有文档（逐个走解析+向量化）
        for doc_id in doc_ids:
            await self.process_document(db, doc_id)

        return doc_ids

    def delete_document(self, db: Session, doc_id: int):
        """
        删除文档：必须三处数据一起清理，缺一不可——
          1. ChromaDB 里的向量（否则检索还会召回已删除文档的内容）；
          2. uploads 磁盘上的原文件；
          3. MySQL 里的记录。
        清理顺序也讲究：先删向量（快、且失败不影响记录），再删文件（可能被
        占用而失败，用 try 兜底），最后删记录并重算计数。
        """
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return

        kb_id = doc.kb_id

        # 删除向量（按 doc_id 元数据过滤删除）
        vector_service.delete_documents(kb_id, doc_id)

        # 删除文件（文件可能被其他进程占用，删失败只记日志不阻塞主流程）
        if doc.file_path and os.path.exists(doc.file_path):
            try:
                os.remove(doc.file_path)
            except Exception as e:
                logger.error(f"Error deleting file: {e}")

        # 删除数据库记录
        db.delete(doc)
        db.commit()

        # 更新计数
        self._update_kb_doc_count(db, kb_id)


# 全局单例
doc_service = DocumentService()
