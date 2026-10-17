# Changelog

本仓库在原项目（@qyhua0, MIT License）基础上的主要改动。

## [Unreleased] - 二次开发改动

### 🐛 Bug 修复
- **修复前端请求 baseURL 前导空格**：`frontend/src/api/index.js` 中 `baseURL` 原为 `' http://localhost:8000/api'`（引号后多一个空格），导致请求绕开 Vite 代理直连后端。改为相对路径 `/api`，与 SSE 流式接口路径保持一致，走同源代理。
- **修复对话页输入框模板截断**：`frontend/src/views/ChatView.vue` 的 `<textarea>` 标签内误写 HTML 注释，Vue 模板编译时把注释后的 `@input` / `placeholder` / `class` / `:disabled` 全部截断为文本框内文字。移除标签内注释后恢复正常。

### 🎨 样式调整
- 主色由靛蓝（indigo `#4f46e5`）改为青绿（teal `#0d9488`），统一更新 `tailwind.config.js` 色板。
- 前端品牌名与浏览器标题改为「智能知识库 / 智能知识库问答」。

### 📦 工程化
- 补充端到端流程测试 `tests/e2e_flow_test.py`，覆盖：健康检查 → 建知识库 → 上传文档 → 解析向量化 → SSE 流式问答 → 会话落库 → 删除清理。
- 测试报告示例见 `tests/test-report.md`。
- 清理代码注释中原作者与包名标识（保留 LICENSE 中的原始版权）。

### 📚 教学友好
- 全项目保留并补充了**逐模块的详细中文注释**：每个文件开头说明模块职责与设计思路，关键函数处标注"为什么这么写"（比如为什么用 BackgroundTasks、为什么 SSE 用 fetch 而不是 axios、为什么上传要加 uuid 前缀等），初学者可以顺着注释读懂整条 RAG 数据流。

### 🔧 检索参数调优
- 文档分块参数从原版 `CHUNK_SIZE=1000 / CHUNK_OVERLAP=200` 调整为 `CHUNK_SIZE=512 / CHUNK_OVERLAP=64`（见 `backend/app/core/config.py`）。
- 更小的块让检索定位更精准、引用片段更短；重叠相应缩小避免冗余。量化对比脚本见 `tests/chunk_eval.py`。

### 🔧 本地部署适配
- 本地环境实测：Ollama + qwen2.5:7b（对话）+ qwen3-embedding:0.6b（向量），Python 3.10，MySQL。
