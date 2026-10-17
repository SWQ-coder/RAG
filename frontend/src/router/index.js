import { createRouter, createWebHistory } from 'vue-router'

/**
 * 路由表：单页应用的所有页面路径定义
 *
 * 【开发思路】
 * 1. createWebHistory()：HTML5 history 模式（URL 无 # 号，如 /kb/6/chat），
 *    需要后端在 dev 模式下配合（Vite dev server 已配置 history 回退）；
 * 2. 所有业务路由都在 /kb 之下，参数 :id 是知识库 ID：
 *    - /kb         知识库列表（首页默认重定向到这里）
 *    - /kb/:id     知识库详情（改名/统计/入口）
 *    - /kb/:id/chat 对话页（核心问答界面）
 *    - /kb/:id/docs 文档管理页（上传/列表/删除/重新处理）
 * 3. 组件用 () => import() 懒加载：路由命中时才下载对应组件，
 *    首屏只加载 KbList，体感更快（代码分包）。
 * 4. meta.title 供页面标题展示（见各视图里读取 useRoute().meta.title）。
 */
export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/kb' },   // 根路径直接跳到知识库列表
    { path: '/kb', component: () => import('@/views/KbList.vue'), meta: { title: '知识库' } },
    { path: '/kb/:id', component: () => import('@/views/KbDetail.vue'), meta: { title: '知识库详情' } },
    { path: '/kb/:id/chat', component: () => import('@/views/ChatView.vue'), meta: { title: '对话' } },
    { path: '/kb/:id/docs', component: () => import('@/views/DocList.vue'), meta: { title: '文档管理' } },
  ]
})
