"""
端到端流程测试：健康检查 → 建知识库 → 上传文档 → 轮询处理状态 → SSE 问答 → 会话列表 → 清理。
运行：backend/.venv/Scripts/python.exe tests/e2e_flow_test.py
结果：打印到控制台，并写入 tests/test-report.md
"""
import time
import json
import httpx
from pathlib import Path

BASE = "http://localhost:8000/api"
REPORT = Path(__file__).parent / "test-report.md"
DOC_CONTENT = (
    "智能知识库系统使用 qwen2.5:7b 作为对话大模型，"
    "使用 qwen3-embedding:0.6b 把文本转成向量。"
    "RAG 完整流程是：文档解析 → 文本分块 → 向量化写入 ChromaDB → "
    "用户提问时先做相似度检索取出最相关的文本块 → 拼进 Prompt → 调用大模型流式生成答案。"
    "系统后端基于 FastAPI，前端基于 Vue3 + Vite。"
)

results = []  # (用例, 通过?, 说明)


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")


def main():
    c = httpx.Client(base_url=BASE, timeout=120)

    # 1. 健康检查
    r = c.get("/system/health")
    h = r.json()
    record("健康检查", r.status_code == 200 and h["ollama"] is True,
           f"status={h['status']}, ollama={h['ollama']}, llm={h['llm_model']}")

    # 2. 建测试知识库
    r = c.post("/kb", json={"name": "e2e测试库", "description": "自动化流程测试用", "icon": "🧪"})
    body = r.json()
    kb_id = body.get("data", {}).get("id")
    record("创建知识库", r.status_code == 200 and kb_id is not None,
           f"kb_id={kb_id}, name={body.get('data',{}).get('name')}")

    # 3. 上传测试文档
    files = {"files": ("e2e_sample.txt", DOC_CONTENT.encode("utf-8"), "text/plain")}
    r = c.post("/doc/upload", data={"kb_id": kb_id}, files=files)
    body = r.json()
    doc_ids = body.get("data", {}).get("doc_ids", [])
    record("上传文档", r.status_code == 200 and len(doc_ids) == 1,
           f"doc_ids={doc_ids}, msg={body.get('message')}")

    # 4. 轮询文档状态直到 completed / failed
    final_status, chunks = "pending", 0
    for i in range(30):
        time.sleep(2)
        r = c.get("/doc", params={"kb_id": kb_id, "page": 1, "page_size": 10})
        items = r.json()["data"]["items"]
        if items:
            final_status = items[0]["status"]
            chunks = items[0].get("chunk_count", 0)
            if final_status in ("completed", "failed"):
                break
    record("文档解析+向量化", final_status == "completed",
           f"最终状态={final_status}, 分块数={chunks}")

    # 5. SSE 流式问答
    question = "系统用什么模型做对话？RAG 的完整流程是什么？"
    answer_tokens, sources, conv_id, events = [], [], None, 0
    with c.stream("POST", "/chat/stream",
                  json={"kb_id": kb_id, "conv_id": None, "question": question}) as resp:
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                evt = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            events += 1
            t = evt.get("type")
            if t == "token":
                answer_tokens.append(evt["data"])
            elif t == "sources":
                sources = evt["data"]
            elif t == "conv_id":
                conv_id = evt["data"]
    answer = "".join(answer_tokens)
    record("SSE 流式问答", events > 0 and len(answer) > 10,
           f"收到事件={events}, 引用来源={len(sources)} 条, 答案长度={len(answer)} 字")

    # 6. 会话列表
    r = c.get("/chat/conversations", params={"kb_id": kb_id, "page_size": 50})
    conv_total = r.json()["data"]["total"]
    record("会话落库", conv_total >= 1, f"会话总数={conv_total}, 本次conv_id={conv_id}")

    # 7. 清理：删除测试知识库
    r = c.delete(f"/kb/{kb_id}")
    record("删除测试知识库", r.status_code == 200, f"http={r.status_code}")

    # 生成报告
    passed = sum(1 for _, ok, _ in results if ok)
    lines = [
        "# 端到端流程测试报告",
        "",
        f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 后端：{BASE}",
        f"- 结果：**{passed}/{len(results)} 通过**",
        "",
        "| 用例 | 结果 | 说明 |",
        "| --- | --- | --- |",
    ]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'✅ PASS' if ok else '❌ FAIL'} | {detail} |")
    lines += [
        "",
        "## 本次提问",
        "",
        f"> {question}",
        "",
        "## 模型流式回答（节选）",
        "",
        answer[:800] + ("..." if len(answer) > 800 else ""),
        "",
        "## 引用来源",
        "",
    ]
    for s in sources[:3]:
        lines.append(f"- {s.get('filename','?')}（相关度 {round(s.get('score',0)*100)}%）：{s.get('content','')[:80]}…")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {REPORT}")


if __name__ == "__main__":
    main()
