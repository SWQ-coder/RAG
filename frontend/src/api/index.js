import axios from 'axios'

/**
 * 全局 axios 实例（所有 HTTP 请求的统一出口）
 *
 * 【为什么要有这一层封装？】
 * 1. baseURL 统一：所有接口都挂在 /api 下，封装后各模块调用时只需写相对路径；
 * 2. timeout 统一：60s 超时（LLM 生成答案可能较慢，流式接口尤其需要耐心）；
 * 3. 响应拦截器统一"拆壳"：后端响应结构是 {code, data, message}，
 *    拦截器直接返回 res.data，业务代码拿到的就是数据本体，无需重复解包；
 * 4. 错误拦截器统一转成中文 Error：把 axios 原始报错里的 detail/message
 *    提取出来，前端各页面 catch(e) 后直接展示 e.message。
 */
const http = axios.create({
  // 走相对路径，经 Vite dev server 代理转发到后端（vite.config.js 里配了 /api → :8000），
  // 浏览器看到的是同源请求，不依赖 CORS；与 ChatView 里 SSE 的 fetch('/api/chat/stream') 保持一致。
  baseURL: '/api',
  timeout: 60000,
})

// 响应拦截器：成功 → 直接返回数据本体；失败 → 提取后端 detail 转成 Error
http.interceptors.response.use(
  res => res.data,
  err => {
    const msg = err.response?.data?.detail || err.response?.data?.message || err.message
    return Promise.reject(new Error(msg))
  }
)

// Knowledge Base（知识库 CRUD：列表/详情/创建/改名/删除）
export const kbApi = {
  list: (p) => http.get('/kb', { params: p }),
  get:  (id) => http.get(`/kb/${id}`),
  create: (d) => http.post('/kb', d),
  update: (id, d) => http.put(`/kb/${id}`, d),
  delete: (id) => http.delete(`/kb/${id}`),
}

// Document（文档管理：列表/详情/删除/重新处理/上传/本地路径导入）
export const docApi = {
  list:   (p) => http.get('/doc', { params: p }),
  get:    (id) => http.get(`/doc/${id}`),
  delete: (id) => http.delete(`/doc/${id}`),
  reprocess: (id) => http.post(`/doc/${id}/reprocess`),
  // 文件上传：multipart/form-data；onUploadProgress 回调计算百分比驱动进度条
  upload: (formData, onProgress) => http.post('/doc/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: e => onProgress && onProgress(Math.round(e.loaded / e.total * 100)),
  }),
  // 服务器本地路径导入（适合批量导入服务器上的已有文件）
  importPath: (d) => http.post('/doc/import-path', d),
}

// Chat（对话：会话列表/历史消息/删除会话/发消息）
export const chatApi = {
  listConvs:  (p) => http.get('/chat/conversations', { params: p }),
  getMessages: (id) => http.get(`/chat/conversations/${id}/messages`),
  deleteConv: (id) => http.delete(`/chat/conversations/${id}`),
  send: (d) => http.post('/chat/send', d),
}

// System（系统状态：健康检查/可用模型列表）
export const sysApi = {
  health: () => http.get('/system/health'),
  models: () => http.get('/system/models'),
}

export default http
