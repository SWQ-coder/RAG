"""
分块参数 A/B 检索质量对比（Recall@3 / MRR）。
自包含：不依赖后端，直接调 Ollama embedding + 内存版 Chroma。
运行前确保 ollama serve 已起、qwen3-embedding:0.6b 已拉取。
运行：backend/.venv/Scripts/python.exe tests/retrieval_ab_test.py
"""
import httpx
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter

OLLAMA = "http://localhost:11434"
EMB_MODEL = "qwen3-embedding:0.6b"

# ── 测试文档：一段约 4000 字、含多个独立事实点的多主题文本 ──
DOC = """
实验一 肺炎感染图像识别
本任务使用 ChestX-ray14 数据集，输入为 224x224 的胸部 X 光图，输出 14 类病理标签的概率。
网络采用 ResNet-50 作为骨干，预训练权重在 ImageNet 上获得。训练 batch size 设为 16，初始学习率 0.001，
采用 AdamW 优化器，weight decay 为 1e-4。评价指标使用 AUC（ROC 曲线下面积），肺炎类别目标 AUC 不低于 0.85。
数据增强仅使用随机水平翻转，禁止垂直翻转（会颠倒解剖结构）。训练轮次 20，验证集每轮计算一次 AUC。
损失函数为带类别的二元交叉熵，因为每张图可能同时有多种病理标签。学习率在第 10 轮后衰减为原来的十分之一。
推理阶段阈值默认 0.5，可根据精确率召回率权衡调整。混淆矩阵显示假阳性主要来自心脏增大类别，需在损失中加大权重。

实验二 Transformer 基本结构
Transformer 完全基于注意力机制，不含卷积与循环。编码器由 6 层堆叠组成，每层包含多头自注意力和前馈网络两个子层。
多头数为 8，模型维度 d_model=512，前馈隐层维度 2048。位置编码采用正弦余弦函数，不学习位置嵌入。
注意力公式为 Attention(Q,K,V)=softmax(QK^T/sqrt(d_k))V，缩放因子 sqrt(d_k) 防止点积过大。
训练时 dropout 率 0.1，标签平滑系数 0.1，warmup 步数 4000。编码器输出再经过层归一化后送入解码器。
解码器额外包含 encoder-decoder 交叉注意力，让每个生成位置关注全部输入位置。
推理时采用自回归生成，每步把已生成序列重新输入模型，速度慢但质量稳定。
注意力图可视化显示，模型在处理指代消解时会高亮相关名词位置。

实验三 Stable Diffusion 文生图
Stable Diffusion 在潜空间而非像素空间做扩散，VAE 把 512x512 图像压缩到 64x64 的潜表示。
U-Net 负责在潜空间逐步去噪，采样器默认 DDIM，步数 20。文本编码器为 CLIP ViT-L/14。
CFG 引导系数 guidance_scale 默认 7.5，数值越高越贴合提示词但多样性下降。
一张 512x512 图像在单张 RTX 4060 上约需 4 秒，FP16 精度下显存占用约 4.2GB。
负向提示词 recommended 为低分辨率、模糊、畸形手指、多余肢体。种子固定为 42 时可复现同一张图。
采样步数增加到 50 时画质提升有限但耗时翻倍，因此默认保持 20。VAE 解码器在生成后把潜表示还原到像素空间。
""" * 1  # 保持结构清晰，下面靠拼接扩充到足够长度
DOC = DOC + DOC.replace("实验一", "附录A") + DOC.replace("实验二", "附录B").replace("实验三", "附录C")

# ── 黄金问题集：(问题, 答案中必然出现的关键短语) ──
GOLDEN = [
    ("肺炎图像用什么骨干网络？", "ResNet-50"),
    ("肺炎实验的初始学习率是多少？", "0.001"),
    ("Transformer 编码器堆叠了多少层？", "6 层"),
    ("多头注意力的多头数是多少？", "8"),
    ("缩放注意力点积的因子是什么？", "sqrt(d_k)"),
    ("Stable Diffusion 把图像压缩到多大的潜空间？", "64x64"),
    ("CFG 引导系数默认值是多少？", "7.5"),
    ("生成一张图在 4060 上大约要几秒？", "4 秒"),
]

SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " ", ""]


def embed(texts):
    r = httpx.post(f"{OLLAMA}/api/embed", json={"model": EMB_MODEL, "input": texts}, timeout=60)
    return r.json()["embeddings"]


def build_collection(chunk_size, chunk_overlap):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=SEPARATORS, length_function=len,
    )
    chunks = splitter.split_text(DOC)
    client = chromadb.EphemeralClient()
    col = client.create_collection(f"eval_{chunk_size}")
    col.add(
        ids=[f"c{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=embed(chunks),
    )
    return chunks, col


def evaluate(col, chunks):
    hits, rr_sum = 0, 0.0
    detail = []
    for q, key in GOLDEN:
        qv = embed([q])[0]
        res = col.query(query_embeddings=[qv], n_results=3)
        docs = res["documents"][0]
        rank = next((i + 1 for i, d in enumerate(docs) if key in d), None)
        if rank:
            hits += 1
            rr_sum += 1.0 / rank
        detail.append((q, key, rank or "未命中"))
    n = len(GOLDEN)
    return {
        "recall@3": hits / n,
        "MRR": rr_sum / n,
        "detail": detail,
        "n_chunks": len(chunks),
    }


if __name__ == "__main__":
    for label, (cs, co) in [("原版 1000/200", (1000, 200)), ("现用 512/64", (512, 64))]:
        chunks, col = build_collection(cs, co)
        r = evaluate(col, chunks)
        print(f"\n=== {label} ===")
        print(f"块数={r['n_chunks']}  Recall@3={r['recall@3']:.0%}  MRR={r['MRR']:.2f}")
        for q, key, rank in r["detail"]:
            mark = f"第{rank}位" if isinstance(rank, int) else "未命中"
            print(f"  [{mark}] {q}  (关键词: {key})")
