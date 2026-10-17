<template>
  <!-- 根布局：左侧固定导航栏 + 右侧路由内容区（单页应用外壳） -->
  <div class="flex h-screen overflow-hidden bg-gray-50">
    <!-- Sidebar：品牌 Logo + 导航 + 系统状态，整个应用常驻 -->
    <aside class="w-56 flex-shrink-0 flex flex-col bg-white border-r border-gray-100">
      <!-- Logo 区：品牌标识与产品名 -->
      <div class="h-14 flex items-center gap-2.5 px-4 border-b border-gray-100">
        <div class="w-7 h-7 rounded-lg bg-primary-600 flex items-center justify-center">
          <!-- 书籍图标（SVG）：暗示"知识库"产品定位 -->
          <svg class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.746 0 3.332.477 4.5 1.253v13C19.832 18.477 18.246 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
        </div>
        <span class="font-semibold text-gray-900 text-sm">智能知识库</span>
      </div>

      <!-- Nav：主导航（router-link 渲染为 <a>，点击切换路由） -->
      <nav class="flex-1 p-3 space-y-0.5">
        <!-- $route.path.startsWith('/kb') 高亮当前项：知识库页及其子页都算激活 -->
        <router-link to="/kb" class="nav-item" :class="{'nav-active': $route.path.startsWith('/kb')}">
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.8">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
          </svg>
          知识库
        </router-link>
      </nav>

      <!-- System status：底部常驻显示 Ollama 连接状态与当前 LLM 模型 -->
      <div class="p-3 border-t border-gray-100">
        <div class="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs text-gray-500">
          <!-- 绿点=已连接，灰点=未连接（health 为空时也显示灰点） -->
          <span class="w-2 h-2 rounded-full flex-shrink-0"
            :class="health?.ollama ? 'bg-green-400' : 'bg-gray-300'"></span>
          <span>{{ health?.ollama ? 'Ollama 已连接' : 'Ollama 未连接' }}</span>
        </div>
        <div class="px-2 py-1 text-xs text-gray-400 truncate" v-if="health?.llm_model">
          {{ health.llm_model }}
        </div>
      </div>
    </aside>

    <!-- Main content：路由出口——当前路由对应的页面组件在这里渲染 -->
    <main class="flex-1 overflow-hidden flex flex-col min-w-0">
      <router-view />
    </main>

    <!-- Toast：全局提示气泡（由 appStore.toast 驱动，按 type 换配色） -->
    <transition name="fade">
      <div v-if="appStore.toast" class="fixed bottom-6 right-6 z-50 flex items-center gap-2 px-4 py-3 rounded-xl shadow-lg text-sm font-medium"
        :class="{
          'bg-gray-900 text-white': appStore.toast.type === 'info',
          'bg-green-600 text-white': appStore.toast.type === 'success',
          'bg-red-600 text-white':   appStore.toast.type === 'error',
        }">
        <span>{{ appStore.toast.msg }}</span>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useAppStore } from '@/stores/app'
import { sysApi } from '@/api'

const appStore = useAppStore()
const health = ref(null)   // 后端健康状态：{ollama, llm_model, ...}

// 挂载后立即探测一次健康状态，之后每 30 秒轮询刷新
// 为什么轮询？——Ollama 可能中途启动/停止，让侧边栏状态"自己恢复"而不必刷新页面
onMounted(async () => {
  try { health.value = await sysApi.health() } catch {}   // 失败保持 null（灰点）
  setInterval(async () => {
    try { health.value = await sysApi.health() } catch {}
  }, 30000)
})
</script>

<style>
/* Tailwind @apply：把通用导航样式抽成可复用的工具类组合 */
.nav-item {
  @apply flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm text-gray-600
         hover:bg-gray-50 hover:text-gray-900 transition-colors cursor-pointer;
}
.nav-active {
  @apply bg-primary-50 text-primary-700 font-medium;
}
</style>
