import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 全局应用状态 store（Pinia setup 写法）
 *
 * 【为什么需要全局状态而不是每个页面自己管？】
 * 1. toast 提示：多个页面（上传成功、删除失败、保存报错…）都可能弹提示，
 *    用全局 store 保证"同一时刻只显示一个"且样式统一；
 * 2. systemOk：后端健康状态（启动时探测一次），供多处（如导航栏）共享显示。
 *
 * 【开发思路】
 * - defineStore('app', () => {...}) 是 Pinia 的 setup 语法：
 *   内部 ref 即响应式状态，函数即 action，return 出去才对外可见；
 * - toastTimer 放在 store 内部闭包：新 toast 到来时先清掉上一个定时器，
 *   防止"快速连续弹多个提示时旧定时器把新提示提前清掉"。
 */
export const useAppStore = defineStore('app', () => {
  const systemOk = ref(null)          // null=未知 | true=后端在线 | false=离线
  const toast = ref(null)             // 当前要显示的提示 {msg, type}
  let toastTimer = null               // 自动消失的定时器句柄

  // 弹出提示：默认 3 秒后自动消失；再次调用会重置计时
  function showToast(msg, type = 'info', duration = 3000) {
    if (toastTimer) clearTimeout(toastTimer)   // 清掉上一个定时器，避免误清新提示
    toast.value = { msg, type }
    toastTimer = setTimeout(() => toast.value = null, duration)  // 到时自动消失
  }

  return { systemOk, toast, showToast }
})
