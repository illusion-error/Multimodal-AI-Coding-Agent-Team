<template>
  <div style="padding: 40px; color: #fff;">
    <h1>✅ TaskDetailView 加载成功</h1>
    <p>任务ID: {{ $route.params.id }}</p>
    <el-button @click="$router.push('/history')">返回历史</el-button>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
console.log('TaskDetailView 加载了，任务ID:', route.params.id)
</script>