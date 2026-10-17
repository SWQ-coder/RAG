<template>
  <!-- 文档管理页：上传文件 / 本地路径导入 / 列表(搜索+状态过滤+分页) / 删除 / 失败重试 -->
  <div class="flex flex-col h-full">
    <!-- Header：返回详情页 + 两个导入入口 + 隐藏的文件选择 input -->
    <div class="flex-shrink-0 flex items-center gap-3 px-6 py-4 border-b border-gray-100 bg-white">
      <button class="btn-ghost p-1.5" @click="$router.push(`/kb/${id}`)">
        <!-- 返回箭头：回到知识库详情页 -->
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/>
        </svg>
      </button>
      <div class="flex-1">
        <h1 class="text-base font-semibold text-gray-900">文档管理</h1>
        <p class="text-xs text-gray-500">上传和管理知识库文档</p>
      </div>
      <div class="flex gap-2">
        <button class="btn-ghost text-xs" @click="showPathModal = true">
          <!-- 本地目录导入：适用于服务器上已有的文件（不走浏览器文件选择） -->
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
          </svg>
          本地目录导入
        </button>
        <button class="btn-primary text-xs" @click="triggerUpload">
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/>
          </svg>
          上传文件
        </button>
        <!-- 隐藏的 input：由 triggerUpload() 用 ref 触发 click，支持多选（multiple）+ 限扩展名 -->
        <input ref="fileInput" type="file" multiple class="hidden"
          accept=".pdf,.doc,.docx,.txt,.md,.xls,.xlsx,.jpg,.jpeg,.png,.gif,.bmp"
          @change="onFilesSelected" />
      </div>
    </div>

    <!-- Upload progress area：上传中显示进度条（onUploadProgress 回调驱动） -->
    <div v-if="uploading" class="flex-shrink-0 mx-6 mt-4 p-3 rounded-xl bg-primary-50 border border-primary-100 flex items-center gap-3">
      <Spinner class="w-4 h-4 text-primary-600" />
      <span class="text-sm text-primary-700">正在上传文件... {{ uploadProgress }}%</span>
      <div class="flex-1 h-1.5 bg-primary-100 rounded-full overflow-hidden">
        <!-- 进度条宽度由 JS 计算的 uploadProgress 决定 -->
        <div class="h-full bg-primary-500 rounded-full transition-all" :style="`width:${uploadProgress}%`"></div>
      </div>
    </div>

    <!-- Filters：搜索关键字 + 状态过滤 + 手动刷新 -->
    <div class="flex-shrink-0 flex items-center gap-3 px-6 py-3">
      <div class="relative">
        <svg class="absolute left-2.5 top-2.5 w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z"/>
        </svg>
        <input v-model="keyword" @input="onSearch" placeholder="搜索文档..."
          class="input pl-7 text-xs h-8 w-52" />
      </div>
      <!-- 状态下拉：change 即重新加载（按处理状态筛选） -->
      <select v-model="statusFilter" @change="load" class="input text-xs h-8 w-28">
        <option value="">全部状态</option>
        <option value="completed">已完成</option>
        <option value="processing">处理中</option>
        <option value="pending">待处理</option>
        <option value="failed">失败</option>
      </select>
      <button class="btn-ghost text-xs h-8" @click="load">
        <!-- 手动刷新按钮 -->
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
        </svg>
        刷新
      </button>
    </div>

    <!-- Table：文档列表（loading / 空态 / 数据 三态） -->
    <div class="flex-1 overflow-auto px-6 pb-6">
      <div class="card overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-gray-100">
              <th class="text-left px-4 py-3 text-xs font-medium text-gray-500">文件名</th>
              <th class="text-left px-4 py-3 text-xs font-medium text-gray-500">类型</th>
              <th class="text-left px-4 py-3 text-xs font-medium text-gray-500">大小</th>
              <th class="text-left px-4 py-3 text-xs font-medium text-gray-500">分块</th>
              <th class="text-left px-4 py-3 text-xs font-medium text-gray-500">来源</th>
              <th class="text-left px-4 py-3 text-xs font-medium text-gray-500">状态</th>
              <th class="text-left px-4 py-3 text-xs font-medium text-gray-500">时间</th>
              <th class="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-50">
            <tr v-if="loading">
              <td colspan="8" class="py-12 text-center"><Spinner /></td>
            </tr>
            <tr v-else-if="!docs.length">
              <td colspan="8" class="py-12 text-center text-sm text-gray-400">暂无文档</td>
            </tr>
            <tr v-for="doc in docs" :key="doc.id" class="hover:bg-gray-50 transition-colors">
              <td class="px-4 py-3">
                <div class="flex items-center gap-2">
                  <span class="text-base">{{ fileIcon(doc.file_type) }}</span>
                  <div class="min-w-0">
                    <p class="text-sm text-gray-800 truncate max-w-[200px]" :title="doc.filename">{{ doc.filename }}</p>
                    <!-- 处理失败时显示后端返回的错误信息（红字），方便定位问题 -->
                    <p v-if="doc.error_msg" class="text-xs text-red-500 truncate max-w-[200px]" :title="doc.error_msg">{{ doc.error_msg }}</p>
                  </div>
                </div>
              </td>
              <td class="px-4 py-3 text-xs text-gray-500 uppercase">{{ doc.file_type || '-' }}</td>
              <td class="px-4 py-3 text-xs text-gray-500">{{ formatSize(doc.file_size) }}</td>
              <td class="px-4 py-3 text-xs text-gray-500">{{ doc.chunk_count || '-' }}</td>
              <td class="px-4 py-3">
                <!-- 来源徽章：浏览器上传 或 服务器本地路径导入 -->
                <span :class="doc.source_type === 'upload' ? 'badge-blue' : 'badge-gray'">
                  {{ doc.source_type === 'upload' ? '上传' : '本地' }}
                </span>
              </td>
              <td class="px-4 py-3">
                <div class="flex items-center gap-1.5">
                  <!-- 状态小圆点：processing 用 animate-pulse 呼吸动画提示"正在处理" -->
                  <span class="w-1.5 h-1.5 rounded-full flex-shrink-0"
                    :class="{ 'bg-green-400': doc.status==='completed', 'bg-blue-400 animate-pulse': doc.status==='processing',
                              'bg-yellow-400': doc.status==='pending', 'bg-red-400': doc.status==='failed' }"></span>
                  <span :class="statusBadge(doc.status)">{{ statusLabel(doc.status) }}</span>
                </div>
              </td>
              <td class="px-4 py-3 text-xs text-gray-400">{{ formatDate(doc.created_at) }}</td>
              <td class="px-4 py-3">
                <div class="flex gap-1 justify-end">
                  <!-- 仅失败状态显示"重新处理"按钮（重跑解析/入库流程） -->
                  <button v-if="doc.status === 'failed'" class="btn-ghost p-1" title="重新处理"
                    @click="reprocess(doc)">
                    <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                    </svg>
                  </button>
                  <button class="btn-danger p-1" title="删除" @click="onDelete(doc)">
                    <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination：总数超一页才显示 -->
      <div v-if="total > pageSize" class="flex justify-center mt-4">
        <div class="flex gap-1">
          <button class="btn-ghost text-xs" :disabled="page===1" @click="page--;load()">上一页</button>
          <span class="flex items-center px-3 text-xs text-gray-500">{{ page }}/{{ Math.ceil(total/pageSize) }}</span>
          <button class="btn-ghost text-xs" :disabled="page>=Math.ceil(total/pageSize)" @click="page++;load()">下一页</button>
        </div>
      </div>
    </div>

    <!-- Local path modal：填写服务器上的路径批量导入（可递归扫子目录） -->
    <Modal v-if="showPathModal" @close="showPathModal = false">
      <template #title>导入本地目录</template>
      <div class="space-y-4">
        <div>
          <label class="text-xs font-medium text-gray-700 mb-1.5 block">目录或文件路径</label>
          <input v-model="localPath" class="input" placeholder="例如: /data/documents 或 /data/report.pdf" />
        </div>
        <label class="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" v-model="recursive" class="rounded" />
          <span class="text-sm text-gray-700">递归扫描子目录</span>
        </label>
        <div class="text-xs text-gray-400">
          支持格式：PDF、Word、Excel、TXT、图片等
        </div>
        <div class="flex justify-end gap-2">
          <button class="btn-ghost" @click="showPathModal=false">取消</button>
          <!-- 路径为空或导入中时禁用按钮 -->
          <button class="btn-primary" @click="importLocalPath" :disabled="!localPath || importing">
            <Spinner v-if="importing" class="w-3.5 h-3.5" />
            开始导入
          </button>
        </div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { docApi } from '@/api'
import { useAppStore } from '@/stores/app'
import Modal from '@/components/Modal.vue'
import Spinner from '@/components/Spinner.vue'

const route = useRoute()
const appStore = useAppStore()
const id = parseInt(route.params.id)   // 当前知识库 ID（从 URL 取）

const docs = ref([])           // 当前页文档列表
const loading = ref(false)     // 表格加载中
const total = ref(0)           // 总条数（分页）
const page = ref(1)            // 当前页码
const pageSize = 20
const keyword = ref('')        // 搜索关键字
const statusFilter = ref('')   // 状态过滤（'' = 全部）
const fileInput = ref(null)    // 隐藏的文件选择 input 引用
const uploading = ref(false)   // 上传进行中
const uploadProgress = ref(0)  // 上传进度 0~100
const showPathModal = ref(false)  // 本地路径导入弹窗
const localPath = ref('')     // 输入的服务器路径
const recursive = ref(true)   // 是否递归扫子目录
const importing = ref(false)  // 导入请求进行中

// 展示层工具函数（与 KbDetail 一致，页内独立定义避免跨文件耦合）
const fileIcon = t => ({ pdf:'📄', word:'📝', excel:'📊', text:'📃', image:'🖼️' }[t] || '📁')
const formatSize = b => b >= 1048576 ? (b/1048576).toFixed(1)+'MB' : (b/1024).toFixed(1)+'KB'
const statusBadge = s => ({ completed:'badge-green', processing:'badge-blue', pending:'badge-yellow', failed:'badge-red' }[s] || 'badge-gray')
const statusLabel = s => ({ completed:'已完成', processing:'处理中', pending:'待处理', failed:'失败' }[s] || s)
const formatDate = d => new Date(d).toLocaleDateString('zh-CN', { month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' })

let searchTimer = null
// 搜索防抖：停止输入 400ms 后才触发（回第 1 页）
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page.value=1; load() }, 400) }

// 加载文档列表：按 知识库/页码/状态/关键字 组合查询
async function load() {
  loading.value = true
  try {
    const res = await docApi.list({
      kb_id: id, page: page.value, page_size: pageSize,
      status: statusFilter.value || undefined, keyword: keyword.value || undefined
    })
    docs.value = res.data.items
    total.value = res.data.total
  } finally { loading.value = false }   // 失败不弹错（列表页静默），靠"刷新"按钮重试
}

// 触发隐藏 input 的点击（美化上传入口：按钮外观统一，不用原生 input）
function triggerUpload() { fileInput.value?.click() }

// 文件选择后：构造 FormData 一次提交所有文件，带进度回调
async function onFilesSelected(e) {
  const files = Array.from(e.target.files)
  if (!files.length) return
  const fd = new FormData()
  fd.append('kb_id', id)                       // 知识库归属
  files.forEach(f => fd.append('files', f))    // 支持多文件（同名字段多次 append）
  uploading.value = true; uploadProgress.value = 0
  try {
    await docApi.upload(fd, p => uploadProgress.value = p)
    appStore.showToast(`成功上传 ${files.length} 个文件，后台处理中`, 'success')
    setTimeout(load, 1000)   // 稍等后台开始处理后再刷新，避免刚上传就刷新看不到变化
  } catch (e) { appStore.showToast(e.message, 'error') }
  finally { uploading.value = false; e.target.value = '' }   // 清空 input，保证同文件可再次选择
}

// 服务器本地路径导入：后端扫描目录/单文件入库
async function importLocalPath() {
  importing.value = true
  try {
    await docApi.importPath({ kb_id: id, path: localPath.value, recursive: recursive.value })
    appStore.showToast('正在导入，请稍候刷新查看结果', 'success')
    showPathModal.value = false; localPath.value = ''
    setTimeout(load, 2000)   // 目录扫描 + 解析较慢，多等一会
  } catch (e) { appStore.showToast(e.message, 'error') }
  finally { importing.value = false }
}

// 删除文档（连带删向量块）：confirm 二次确认
async function onDelete(doc) {
  if (!confirm(`确认删除文档「${doc.filename}」？`)) return
  try { await docApi.delete(doc.id); appStore.showToast('删除成功', 'success'); await load() }
  catch (e) { appStore.showToast(e.message, 'error') }
}

// 失败重试：把文档状态重置回 pending 重新走解析入库
async function reprocess(doc) {
  try { await docApi.reprocess(doc.id); appStore.showToast('已重新提交处理', 'success'); await load() }
  catch (e) { appStore.showToast(e.message, 'error') }
}

// Auto-refresh for processing docs：进入页面后每 8 秒自动刷新列表，
// 让"处理中"的文档状态自己变成"已完成"，无需用户反复点刷新
let refreshTimer = null
onMounted(() => { load(); refreshTimer = setInterval(load, 8000) })
onUnmounted(() => clearInterval(refreshTimer))   // 离开页面必须清定时器，防止泄漏
</script>
