<!-- src/App.vue -->
<template>
  <div id="app">
    <el-menu mode="horizontal" @select="handleSelect">
      <el-menu-item index="/">🏠 首页</el-menu-item>
      <el-menu-item index="/history">📚 历史记录</el-menu-item>
      <el-menu-item index="/metrics">📊 指标看板</el-menu-item>
    </el-menu>
    <router-view />
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()
const handleSelect = (index) => router.push(index)
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
#app { 
  font-family: 'Helvetica Neue', Arial, sans-serif; 
  background: #f5f7fa;
  min-height: 100vh;
}
.el-menu { margin-bottom: 20px; }
</style>