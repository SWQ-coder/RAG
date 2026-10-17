<template>
  <!--
    加载指示器（Spinner）：旋转圆圈 SVG
    【开发思路】
    1. animate-spin 是 Tailwind 内置旋转动画，循环转圈；
    2. $attrs.class 透传：调用方传入的 class（如 w-3.5 h-3.5 调整大小、
       text-primary-600 调整颜色）会透传到 svg 上；没传时用默认尺寸/颜色；
    3. 圆环（circle）不透明度 25% 做底色，弧形（path）75% 做旋转"指针"，
       SVG 原理解读：一整圈 = 底色 + 缺口弧，视觉上就是加载圈。
  -->
  <svg :class="['animate-spin', $attrs.class || 'w-5 h-5 text-primary-500']"
    fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
  </svg>
</template>
