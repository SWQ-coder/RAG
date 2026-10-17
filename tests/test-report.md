# 端到端流程测试报告

- 时间：2026-10-17 13:26:43
- 后端：http://localhost:8000/api
- 结果：**7/7 通过**

| 用例 | 结果 | 说明 |
| --- | --- | --- |
| 健康检查 | ✅ PASS | status=healthy, ollama=True, llm=qwen2.5:7b |
| 创建知识库 | ✅ PASS | kb_id=2, name=e2e测试库 |
| 上传文档 | ✅ PASS | doc_ids=[5], msg=成功上传 1 个文件，正在后台处理中 |
| 文档解析+向量化 | ✅ PASS | 最终状态=completed, 分块数=1 |
| SSE 流式问答 | ✅ PASS | 收到事件=100, 引用来源=2 条, 答案长度=177 字 |
| 会话落库 | ✅ PASS | 会话总数=1, 本次conv_id=2 |
| 删除测试知识库 | ✅ PASS | http=200 |

## 本次提问

> 系统用什么模型做对话？RAG 的完整流程是什么？

## 模型流式回答（节选）

系统使用 qwen2.5:7b 作为对话大模型。

RAG（Retrieval-Augmented Generation）的完整流程如下：
1. 文档解析
2. 文本分块
3. 向量化写入 ChromaDB
4. 用户提问时先做相似度检索取出最相关的文本块
5. 拼进 Prompt
6. 调用大模型流式生成答案

【来源：e2e_sample.txt】

## 引用来源

- e2e_sample.txt（相关度 57%）：智能知识库系统使用 qwen2.5:7b 作为对话大模型，使用 qwen3-embedding:0.6b 把文本转成向量。RAG 完整流程是：文档解析 → 文本…
- e2e_sample.txt（相关度 45%）：智能知识库系统使用 qwen2.5:7b 作为对话大模型，使用 qwen3-embedding:0.6b 把文本转成向量。RAG 完整流程是：文档解析 → 文本…