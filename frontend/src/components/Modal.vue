<template>
  <!--
    通用弹窗组件（Modal）
    【用法】调用方用 v-if="show" 控制显示，@close 监听关闭；
            具名插槽 #title 传标题，默认插槽传正文内容。
    【开发思路】
    1. teleport to="body"：把弹窗 DOM 挂到 body 下，而不是组件所在位置。
       好处：不受父容器 overflow/层级（z-index 上下文）影响，保证全屏遮罩生效；
    2. 遮罩层点击（@click="$emit('close')"）即关闭——常见的"点外面关闭"交互；
    3. 内容用两个插槽：具名插槽 #title 放标题，默认插槽放正文，
       调用方通过插槽自由定制，组件本身不关心业务内容；
    4. 入场动画 fadeInUp：从下方轻微上浮淡入，提升弹窗的"质感"。
  -->
  <teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <!-- 半透明遮罩层：点击它触发 close 事件（点外部关闭） -->
      <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="$emit('close')"></div>
      <!-- 弹窗主体卡片：宽度最大 md，带入场动画 -->
      <div class="relative card w-full max-w-md p-6 shadow-xl animate-[fadeInUp_0.2s_ease]">
        <div class="flex items-center justify-between mb-4">
          <!-- 标题插槽：调用方通过具名插槽 #title 填充 -->
          <h3 class="text-base font-semibold text-gray-900">
            <slot name="title" />
          </h3>
          <!-- 右上角关闭按钮（X） -->
          <button class="btn-ghost p-1.5" @click="$emit('close')">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
        <!-- 默认插槽：正文内容由调用方填充 -->
        <slot />
      </div>
    </div>
  </teleport>
</template>

<script setup>
// 声明组件对外发射的事件 close：父组件用 @close 监听（关闭弹窗）
defineEmits(['close'])
</script>

<style>
/* 入场动画：透明 + 从下方 8px 上浮，0.2s 完成 */
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
