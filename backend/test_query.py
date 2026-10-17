# backend/test_query.py  检索排查脚本
# 【用途】开发期绕过 LangChain 层，直接用 ChromaDB 原生 query 接口
# 验证"某个 query 到底能召回什么"，同时打印相似度/距离，定位：
#   - 检索不到内容（embedding 问题 / 向量库为空）
#   - 召回内容不对（相似度阈值、chunk 质量、query 写法）
# 【开发思路】
#   1. 不走 vector_service 的异步封装，直接同步调用，脚本最简单直接；
#   2. 复用 vector_service._emb_wrapper 的 embed 函数（同一模型、同一
#      向量空间），保证这里的向量与正式入库时完全一致；
#   3. 相似度换算与 vector_store.py 相同（exp(-L2距离)），结果可直接对照。
# 注意：脚本使用固定 kb_id=6、固定 query，按需修改后运行。
import sys
sys.path.insert(0, ".")   # 以 backend 为根，能 import app.*
import chromadb
from chromadb.config import Settings
from app.services.vector_store import vector_service

client = chromadb.PersistentClient(
    path="./chroma_db",
    settings=Settings(anonymized_telemetry=False)
)

kb_id = 6
collection = client.get_collection(f"kb_{kb_id}")

# 直接用 collection.query 测试，绕过 LangChain 层
# 关键点：embed 用的必须是入库时同一套 wrapper（同一模型），
# 否则查询向量与库内向量不在同一空间，召回必然失真
emb_wrapper = vector_service._emb_wrapper
query = "斯华AIWindows客户端手册"
vec = emb_wrapper._sync_embed_query(query)

results = collection.query(
    query_embeddings=[vec],        # 传入查询向量（而不是文本，跳过内部再 embed）
    n_results=10,                  # 取前 10 条
    include=["metadatas", "documents", "distances"]
)

print(f"Query: {query!r}\n")
# 并行遍历 文档内容/元数据/距离，逐条打印相似度与文件名，
# 便于肉眼判断召回顺序是否合理
for i, (doc, meta, dist) in enumerate(zip(
    results["documents"][0],
    results["metadatas"][0],
    results["distances"][0]
)):
    import math
    sim = math.exp(-dist)   # L2 距离 → 0~1 相似度（与正式检索口径一致）
    print(f"[{i+1}] sim={sim:.4f} dist={dist:.4f}")
    print(f"     file={meta.get('filename')!r}")
    print(f"     content={doc[:80]!r}\n")