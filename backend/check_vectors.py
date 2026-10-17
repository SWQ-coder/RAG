# backend/check_vectors.py  临时排查脚本
# 【用途】开发期快速查看某个知识库在 ChromaDB 里的向量情况：
#   1. 总数是多少；2. 每个文件各占多少块（chunk）。
# 【开发思路】这是个一次性诊断脚本，不参与服务运行：
#   - 直接用 chromadb 原生 API（绕过应用层封装）读库，适合临时排查；
#   - kb_id 写死在代码里（这里是 6），用完按需改。
# 注意：路径/参数要与实际配置一致（persist dir 是 ./chroma_db，
# 集合名规则 kb_{id} 与 vector_store 中的 _collection_name 保持一致）。
import sys
sys.path.insert(0, ".")   # 让 Python 能找到同目录下的包（以 backend 为根）
import chromadb
from chromadb.config import Settings

# 打开持久化客户端（与 vector_store.py 同一目录，读同一份数据）
client = chromadb.PersistentClient(
    path="./chroma_db",
    settings=Settings(anonymized_telemetry=False)
)

kb_id = 6   # 要检查的知识库 ID（按需修改）
collection = client.get_collection(f"kb_{kb_id}")
print(f"Total vectors in kb_{kb_id}: {collection.count()}")

# 查所有文件名：get 只取 metadatas（不取 embedding，省内存），
# 遍历每条元数据统计每个文件贡献了多少 chunk
results = collection.get(include=["metadatas"], limit=10000)
filenames = {}
for meta in results["metadatas"]:
    fname = meta.get("filename", "?")
    filenames[fname] = filenames.get(fname, 0) + 1

print("\n各文件向量数量：")
for fname, count in sorted(filenames.items()):
    print(f"  {count:4d} chunks | {fname}")