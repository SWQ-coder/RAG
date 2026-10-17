"""
重建指定知识库的所有向量索引
用法: python reindex.py <kb_id>

【用途】当向量库数据损坏 / 元数据 schema 变更 / 想按新分块参数重跑时，
一键清空并重新处理某知识库的全部文档。

【开发思路】"重建"= 三件事的顺序很关键：
  1. 先删旧向量（delete_kb 删整个集合，比逐条删快且彻底）；
  2. 再把数据库里文档状态重置为 PENDING、清空 chunk_count/错误信息，
     让下游逻辑认为"这些文档还没处理过"；
  3. 最后逐个调用 doc_service.process_document 重新走完整入库流程
     （解析→分块→embed→写向量库→回写状态）。
  之所以复用 process_document 而不是自己重写解析逻辑：
  保证重建与正常上传走同一套代码，不会出现"两套实现、行为不一致"。
"""
import sys
import asyncio
sys.path.insert(0, ".")   # 以 backend 为根，能 import app.*

from app.core.database import SessionLocal
from app.models import Document, DocStatus
from app.services.vector_store import vector_service
from app.services.document import doc_service

async def reindex(kb_id: int):
    db = SessionLocal()
    try:
        # 清除旧向量
        vector_service.delete_kb(kb_id)
        print(f"Deleted old vectors for kb_id={kb_id}")

        # 重置所有文档状态：PENDING + 清空计数/错误，
        # 让 process_document 重新执行时像"首次处理"一样
        docs = db.query(Document).filter(Document.kb_id == kb_id).all()
        for doc in docs:
            doc.status = DocStatus.PENDING
            doc.chunk_count = 0
            doc.error_msg = None
        db.commit()

        # 重新处理：逐篇走标准入库流程（阻塞等待每篇完成，按序执行）
        for doc in docs:
            print(f"Processing: {doc.filename}")
            await doc_service.process_document(db, doc.id)
            print(f"Done: {doc.filename}, chunks={doc.chunk_count}")

    finally:
        db.close()   # 无论成功失败都释放数据库连接

if __name__ == "__main__":
    # 支持命令行传参：python reindex.py 6；不传则用下面的默认值
    # kb_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    kb_id = 6
    asyncio.run(reindex(kb_id))   # 脚本无事件循环，用 asyncio.run 起一个