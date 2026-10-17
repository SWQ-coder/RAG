"""
分块参数对比：CHUNK_SIZE=512/64（现） vs 1000/200（原版）。
不依赖后端服务，直接用项目里的 RecursiveCharacterTextSplitter。
运行：backend/.venv/Scripts/python.exe tests/chunk_eval.py
"""
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 用一段贴近真实实验指导书风格的长文本做样本（约 1800 字）
SAMPLE = (
    "本实验指导书介绍 Stable Diffusion 的基本原理与使用方法。" * 3 +
    "Stable Diffusion 是一种潜在扩散模型，通过在潜空间逐步去噪生成图像。" * 3 +
    "实验环境要求 Python 3.10、PyTorch 2.1、CUDA 11.8，并安装 diffusers 库。" * 3 +
    "第一步：加载预训练模型 runwayml/stable-diffusion-v1-5，注意显存占用约 4GB。" * 3 +
    "第二步：编写提示词，正向提示词描述想要的画面，负向提示词排除不需要的元素。" * 3 +
    "第三步：设置采样步数 num_inference_steps=20，引导系数 guidance_scale=7.5。" * 3 +
    "常见问题：生成图像出现畸形肢体时，应增加负向提示词；速度过慢时可改用 FP16 精度。" * 3 +
    "本实验考核点：能独立复现一张人物肖像生成，并解释 CFG 系数对结果的影响。" * 3
) + ("\n\n" if False else "") + (
    "另一部分：Transformer 的自注意力机制允许序列中每个位置直接关注所有其他位置。" * 3 +
    "多头注意力把 Q/K/V 投影到多个子空间并行计算，最后拼接。位置编码使用正弦函数。" * 3
)

SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ".", "!", "?", ";", " ", ""]


def run(chunk_size, chunk_overlap):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        separators=SEPARATORS, length_function=len,
    )
    chunks = splitter.split_text(SAMPLE)
    lens = [len(c) for c in chunks]
    return {
        "chunk_size": chunk_size, "chunk_overlap": chunk_overlap,
        "n_chunks": len(chunks),
        "avg_len": round(sum(lens) / len(lens), 1),
        "min_len": min(lens), "max_len": max(lens),
    }


if __name__ == "__main__":
    print(f"样本总长度：{len(SAMPLE)} 字\n")
    for cfg in [(1000, 200), (512, 64)]:
        r = run(*cfg)
        print(f"CHUNK_SIZE={r['chunk_size']} / OVERLAP={r['chunk_overlap']}:")
        print(f"  块数={r['n_chunks']}  平均长度={r['avg_len']} 字  最短={r['min_len']}  最长={r['max_len']}")
