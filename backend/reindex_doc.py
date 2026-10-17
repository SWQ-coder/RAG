"""
 重建指定文件向量
【用途】reindex.py 是"重建整个知识库"；本脚本是它的单篇版本——
只重跑某一篇文档，适合"只有一篇坏了/想单独更新一篇"的排查场景。
【开发思路】与 reindex.py 相同的三步套路，只是范围缩到单篇：
  删该文档的向量 → 重置该文档状态 → 重新 process_document。
  注意 doc.refresh(doc) 的作用：process_document 内部是提交到数据库
  的，refresh 才能把最新 status/chunk_count 重新读回内存打印。
"""
import sys, asyncio
sys.path.insert(0, ".")

from app.core.database import SessionLocal
from app.models import Document, DocStatus
from app.services.vector_store import vector_service
from app.services.document import doc_service

async def reindex_doc(kb_id: int, doc_id: int):
    db = SessionLocal()
    try:
        # 删除旧向量
        vector_service.delete_documents(kb_id, doc_id)
        print(f"Deleted old vectors for doc_id={doc_id}")

        # 重置状态
        doc = db.query(Document).filter(Document.id == doc_id).first()
        doc.status = DocStatus.PENDING
        doc.chunk_count = 0
        doc.error_msg = None
        db.commit()

        # 重新处理
        await doc_service.process_document(db, doc_id)

        # 重新从数据库读取该行（process 里 commit 过，内存对象可能已过期）
        db.refresh(doc)
        print(f"Done: {doc.filename} | status={doc.status} | chunks={doc.chunk_count}")
    finally:
        db.close()

if __name__ == "__main__":
    # 支持命令行传参：python reindex_doc.py <kb_id> <doc_id>
    # kb_id  = int(sys.argv[1])
    # doc_id = int(sys.argv[2])
    kb_id  = 6
    doc_id = 6
    asyncio.run(reindex_doc(kb_id, doc_id))