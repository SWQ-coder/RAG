<template>
  <!-- 知识库问答页：左侧会话列表 + 右侧聊天区（SSE 流式输出） -->
  <div class="flex h-full overflow-hidden">
    <!-- Conversation sidebar：历史会话列表（当前知识库下） -->
    <div class="w-56 flex-shrink-0 flex flex-col border-r border-gray-100 bg-white">
      <div class="flex items-center justify-between px-3 py-3 border-b border-gray-100">
        <div class="flex items-center gap-2">
          <button class="btn-ghost p-1" @click="$router.push(`/kb/${id}`)">
            <!-- 返回知识库详情 -->
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/>
            </svg>
          </button>
          <span class="text-xs font-medium text-gray-700">对话列表</span>
        </div>
        <button class="btn-ghost p-1" title="新对话" @click="newConversation">
          <!-- 新对话：只清前端状态，后端等发第一条消息时才建会话 -->
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/>
          </svg>
        </button>
      </div>

      <div class="flex-1 overflow-y-auto p-2 space-y-0.5">
        <!-- 会话项：当前会话高亮；删除按钮悬浮显示（@click.stop 防误触切换） -->
        <div v-for="conv in convs" :key="conv.id"
          class="group flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer text-xs transition-colors"
          :class="activeConvId === conv.id ? 'bg-primary-50 text-primary-700' : 'text-gray-600 hover:bg-gray-50'"
          @click="loadConversation(conv.id)">
          <svg class="w-3 h-3 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
          </svg>
          <span class="flex-1 truncate">{{ conv.title }}</span>
          <button class="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:text-red-500 transition-all"
            @click.stop="deleteConv(conv.id)">
            <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <div v-if="!convs.length" class="py-8 text-center text-xs text-gray-400">暂无对话记录</div>
      </div>
    </div>

    <!-- Chat area：主聊天区 -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Chat header：标题 + 当前知识库名 -->
      <div class="flex-shrink-0 flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-white">
        <div class="flex items-center gap-2">
          <div class="w-6 h-6 rounded-lg bg-primary-600 flex items-center justify-center">
            <svg class="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
          </div>
          <span class="text-sm font-medium text-gray-700">知识库问答</span>
        </div>
        <span class="text-xs text-gray-400">基于 {{ kbName }} 知识库</span>
      </div>

      <!-- Messages：滚动消息容器（ref 供自动滚动定位） -->
      <div ref="msgContainer" class="flex-1 overflow-y-auto px-6 py-4 space-y-5">
        <!-- Welcome：空会话时的引导页 -->
        <div v-if="!messages.length" class="flex flex-col items-center justify-center h-full text-center">
          <div class="w-14 h-14 rounded-2xl bg-primary-50 flex items-center justify-center mb-4">
            <svg class="w-7 h-7 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
          </div>
          <h3 class="text-base font-semibold text-gray-800 mb-1">开始与知识库对话</h3>
          <p class="text-sm text-gray-500 max-w-xs">我会基于知识库中的文档内容来回答您的问题，并注明引用来源</p>
        </div>

        <!-- Message list：每条消息都用 key（后端 id 或本地临时 id）标识 -->
        <template v-for="msg in messages" :key="msg.id || msg._tmpId">
          <!-- User message：右对齐蓝色气泡 -->
          <div v-if="msg.role === 'user'" class="flex justify-end">
            <div class="max-w-[75%] px-4 py-3 rounded-2xl rounded-tr-sm bg-primary-600 text-white text-sm leading-relaxed">
              {{ msg.content }}
            </div>
          </div>

          <!-- Assistant message：左对齐，带头像 + 正文 + 可折叠引用来源 -->
          <div v-else class="flex gap-3">
            <div class="w-7 h-7 rounded-full bg-primary-100 flex items-center justify-center flex-shrink-0 mt-0.5">
              <svg class="w-4 h-4 text-primary-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <div class="card px-4 py-3 rounded-tl-sm">
                <!-- 流式中：纯文本 + 光标闪烁动画（不渲染 markdown，避免闪烁） -->
                <div v-if="msg._streaming" class="prose-rag">
                  <span>{{ msg.content }}</span><span class="cursor-blink text-primary-500 ml-0.5">▋</span>
                </div>
                <!-- 流式结束：marked 把 markdown 渲染成 HTML（v-html） -->
                <div v-else class="prose-rag" v-html="renderMd(msg.content)"></div>
              </div>
              <!-- Sources：后端 SSE 推送的引用来源（折叠展开） -->
              <div v-if="msg.sources && msg.sources.length" class="mt-2">
                <button class="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
                  @click="msg._showSrc = !msg._showSrc">
                  <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                  </svg>
                  {{ msg.sources.length }} 个引用来源 {{ msg._showSrc ? '▲' : '▼' }}
                </button>
                <div v-if="msg._showSrc" class="mt-2 space-y-1.5">
                  <!-- 每条来源：编号/文件名/页码/内容摘要/相关度 -->
                  <div v-for="src in msg.sources" :key="src.index"
                    class="flex gap-2 p-2.5 rounded-lg bg-gray-50 border border-gray-100 text-xs">
                    <span class="w-5 h-5 rounded bg-primary-100 text-primary-600 flex items-center justify-center flex-shrink-0 font-medium">
                      {{ src.index }}
                    </span>
                    <div class="min-w-0">
                      <p class="font-medium text-gray-700 truncate">{{ src.filename }}{{ src.page ? ` · 第${src.page}页` : '' }}</p>
                      <p class="text-gray-500 mt-0.5 line-clamp-2">{{ src.content }}</p>
                    </div>
                    <!-- 相似度百分比（后端算好的 score） -->
                    <span class="text-gray-400 flex-shrink-0 self-start">{{ (src.score * 100).toFixed(0) }}%</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </template>

        <!-- Loading indicator：检索阶段（SSE sources 事件前的等待提示） -->
        <div v-if="thinking && !streamingMsg" class="flex gap-3">
          <div class="w-7 h-7 rounded-full bg-primary-100 flex items-center justify-center flex-shrink-0">
            <svg class="w-4 h-4 text-primary-600 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          </div>
          <div class="card px-4 py-3 text-sm text-gray-400 rounded-tl-sm">正在检索知识库...</div>
        </div>
      </div>

      <!-- Input area：输入框 + 发送按钮（Enter 发送 / Shift+Enter 换行） -->
      <div class="flex-shrink-0 border-t border-gray-100 bg-white px-4 py-3">
        <div class="flex gap-2 items-end">
          <div class="flex-1 relative">
            <textarea
              ref="inputRef"
              v-model="input"
              @keydown.enter.exact.prevent="sendMessage"
              @input="autoResize"
              rows="1"
              placeholder="输入问题，Enter 发送，Shift+Enter 换行..."
              class="input resize-none overflow-hidden py-2.5 pr-4 text-sm leading-relaxed"
              style="min-height: 42px; max-height: 120px;"
              :disabled="thinking"
            ></textarea>
          </div>
          <!-- 发送按钮：空输入/生成中禁用；生成中显示旋转图标 -->
          <button class="btn-primary h-10 px-4 flex-shrink-0" @click="sendMessage" :disabled="!input.trim() || thinking">
            <svg v-if="!thinking" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
            </svg>
            <svg v-else class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
          </button>
        </div>
        <p class="text-xs text-gray-400 mt-1.5 px-1">基于知识库内容回答，答案仅供参考</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted, reactive } from 'vue'
import { useRoute } from 'vue-router'
import { chatApi, kbApi } from '@/api'
import { useAppStore } from '@/stores/app'
import { marked } from 'marked'

const route = useRoute()
const appStore = useAppStore()
const id = parseInt(route.params.id)   // 知识库 ID

const messages = ref([])        // 当前会话的消息列表
const convs = ref([])           // 会话列表（左侧栏）
const activeConvId = ref(null)  // 当前激活的会话 id（null=新对话）
const input = ref('')           // 输入框内容
const thinking = ref(false)     // 是否在请求中（控制输入/按钮禁用）
const streamingMsg = ref(null)  // 正在流式输出的助手消息对象（渲染用）
const msgContainer = ref(null)  // 消息容器 DOM（自动滚动定位）
const inputRef = ref(null)      // 输入框 DOM（重置高度）
const kbName = ref('')          // 当前知识库名称（头部展示）

// marked 配置：breaks=换行即换行，gfm=GitHub 风格 markdown
marked.setOptions({ breaks: true, gfm: true })
// 把 markdown 文本渲染成 HTML 字符串（用于 v-html）
const renderMd = (text) => marked.parse(text || '')

// 输入框自适应高度：先归零再按 scrollHeight 撑高，封顶 120px
function autoResize(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

// 滚动到底部：nextTick 等 DOM 更新完成后再滚（smooth 平滑 / auto 直接跳）
async function scrollToBottom(smooth = true) {
  await nextTick()
  if (msgContainer.value) {
    msgContainer.value.scrollTo({ top: msgContainer.value.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }
}

// 新对话：只清空前端状态（activeConvId=null），后端在发首条消息时才建新会话
function newConversation() {
  activeConvId.value = null
  messages.value = []
}

// 加载会话列表（当前知识库下，最多 50 条）
async function loadConvList() {
  try {
    const res = await chatApi.listConvs({ kb_id: id, page_size: 50 })
    convs.value = res.data.items
  } catch {}
}

// 点击会话：加载其历史消息；给每条消息补 _showSrc=false（引用来源默认折叠）
async function loadConversation(convId) {
  activeConvId.value = convId
  try {
    const res = await chatApi.getMessages(convId)
    messages.value = res.data.map(m => ({ ...m, _showSrc: false }))
    await scrollToBottom(false)
  } catch {}
}

// 删除会话：如果删的是当前会话，一并清空聊天区
async function deleteConv(convId) {
  try {
    await chatApi.deleteConv(convId)
    if (activeConvId.value === convId) { activeConvId.value = null; messages.value = [] }
    await loadConvList()
  } catch (e) { appStore.showToast(e.message, 'error') }
}

// 发送消息（核心：SSE 流式接收答案）
async function sendMessage() {
  const q = input.value.trim()
  if (!q || thinking.value) return   // 空输入或正在生成时忽略

  input.value = ''
  if (inputRef.value) { inputRef.value.style.height = '42px' }   // 重置输入框高度
  thinking.value = true

  // 先把用户消息推进列表（用时间戳做临时 id，刷新后才会有后端 id）
  const tmpId = Date.now()
  messages.value.push({ _tmpId: tmpId, role: 'user', content: q })
  await scrollToBottom()

  // 再放一个"流式占位"的助手消息：reactive 对象，SSE 事件直接改它
  // _streaming=true 期间渲染纯文本+光标，结束后才渲染 markdown
  const aiMsg = reactive({ _tmpId: tmpId + 1, role: 'assistant', content: '', sources: [], _streaming: true, _showSrc: false })
  messages.value.push(aiMsg)
  streamingMsg.value = aiMsg

  try {
    // SSE streaming：POST 后保持连接，逐块读取增量文本
    // 为什么不用 axios？——axios 会等整个响应结束才回调，
    // 无法拿到"流式中间状态"；fetch + ReadableStream 才能边收边渲染
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kb_id: id, conv_id: activeConvId.value, question: q }),
    })

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''   // 跨块缓存：TCP 分片可能把一条 data 行切成两半

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // 按行切分；最后一段可能不完整（还没收完），先留回 buffer 等下一块
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue   // 只处理 SSE 的 data 行
        try {
          const data = JSON.parse(line.slice(6))   // 去掉 "data: " 前缀后解析 JSON
          if (data.type === 'token') {       // 生成片段：追加到助手消息并滚动
            aiMsg.content += data.data
            await scrollToBottom()
          } else if (data.type === 'sources') {  // 引用来源：直接存起来（前面已显示）
            aiMsg.sources = data.data
          } else if (data.type === 'conv_id') {  // 首条消息建会话：记录新会话 id 并刷新列表
            activeConvId.value = data.data
            await loadConvList()
          } else if (data.type === 'done') {     // 结束：切换渲染模式（markdown）
            aiMsg._streaming = false
            streamingMsg.value = null
          } else if (data.type === 'error') {    // 后端业务错误：显示在消息里
            aiMsg.content = `❌ ${data.data}`
            aiMsg._streaming = false
          }
        } catch {}   // 个别行解析失败直接跳过，不影响整体流
      }
    }
  } catch (e) {   // 网络层失败（连接断开等）
    aiMsg.content = `❌ 请求失败: ${e.message}`
    aiMsg._streaming = false
    streamingMsg.value = null
  } finally {
    thinking.value = false
    streamingMsg.value = null
    await scrollToBottom()
  }
}

// 挂载：先取知识库名（头部展示），再加载会话列表
onMounted(async () => {
  try {
    const res = await kbApi.get(id)
    kbName.value = res.data.name
  } catch {}
  await loadConvList()
})
</script>
