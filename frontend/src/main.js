/**
 * 前端应用入口（main.js）
 *
 * 【开发思路】Vue3 标准启动流程：
 * 1. createApp(App) 创建应用实例——App.vue 是根组件，包含整体布局和路由出口；
 * 2. 挂载 Pinia（状态管理）：createPinia() 提供全局响应式 store（见 stores/app.js）；
 * 3. 挂载 Vue Router：所有页面切换都由 router/index.js 定义的路由表驱动；
 * 4. 引入全局样式 main.css（Tailwind + 自定义），最后 mount 到 #app。
 * 顺序很关键：pinia 和 router 必须在 mount 之前注册，组件内才能用 useStore/useRoute。
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './assets/main.css'

const app = createApp(App)
app.use(createPinia())   // 先注册状态管理
app.use(router)          // 再注册路由
app.mount('#app')        // 挂载到 index.html 的 #app 节点
