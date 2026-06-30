<template>
  <div id="app">
    <header class="app-header">
      <div class="logo">
        <span class="logo-icon">✦</span>
        <span class="logo-text">Agent</span>
      </div>
      <nav class="nav-menu">
        <router-link to="/" class="nav-link" active-class="active">首页</router-link>
        <router-link to="/history" class="nav-link" active-class="active">历史</router-link>
        <router-link to="/metrics" class="nav-link" active-class="active">指标</router-link>
      </nav>
    </header>
    <main class="page-container">
      <router-view />
    </main>
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
  --primary: #4F6EF7;
  --bg: #0A0A1A;
  --card: rgba(255, 255, 255, 0.04);
  --text: #FFFFFF;
  --text-secondary: rgba(255, 255, 255, 0.5);
  --border: rgba(255, 255, 255, 0.06);
  --radius: 16px;

  /* ===== 强制覆盖 Element Plus 白色背景 ===== */
  --el-bg-color: rgba(20, 20, 50, 0.9) !important;
  --el-fill-color-blank: rgba(20, 20, 50, 0.9) !important;
  --el-bg-color-page: #0A0A1A !important;
  --el-fill-color: rgba(20, 20, 50, 0.8) !important;
  --el-fill-color-light: rgba(20, 20, 50, 0.6) !important;
  --el-text-color-primary: #FFFFFF !important;
  --el-text-color-regular: rgba(255, 255, 255, 0.85) !important;
  --el-text-color-secondary: rgba(255, 255, 255, 0.6) !important;
  --el-border-color: rgba(255, 255, 255, 0.06) !important;
  --el-border-color-light: rgba(255, 255, 255, 0.04) !important;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: var(--bg);
  color: var(--text);
  -webkit-font-smoothing: antialiased;
  margin: 0;
  padding: 0;
  min-height: 100vh;
}

#app {
  min-height: 100vh;
  background: 
    rgba(10, 10, 26, 0.5),
    url('/微信图片_20260630155027_91_3.jpg') center/cover no-repeat fixed;
  background-blend-mode: overlay;
  position: relative;
}

/* 导航 - 深色毛玻璃 */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 40px;
  height: 68px;
  background: rgba(0, 0, 0, 0.25);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  position: sticky;
  top: 0;
  z-index: 100;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
}
.logo-icon { font-size: 22px; color: var(--primary); }
.logo-text {
  background: linear-gradient(135deg, #4F6EF7, #7C5CFC);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.nav-menu { display: flex; gap: 4px; }
.nav-link {
  color: rgba(255, 255, 255, 0.4);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  padding: 8px 18px;
  border-radius: 8px;
  transition: all 0.2s;
}
.nav-link:hover { color: rgba(255, 255, 255, 0.7); background: rgba(255,255,255,0.05); }
.nav-link.active { color: #fff; background: rgba(255,255,255,0.08); }

.page-container {
  max-width: 1100px;
  margin: 0 auto;
  padding: 32px 24px 60px;
  position: relative;
  z-index: 1;
}

/* ===== Element Plus 暗色主题 ===== */
.el-card {
  border-radius: var(--radius) !important;
  border: 1px solid var(--border) !important;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3) !important;
  background: var(--card) !important;
  backdrop-filter: blur(16px) !important;
  -webkit-backdrop-filter: blur(16px) !important;
}

.el-button--primary {
  background: var(--primary) !important;
  border: none !important;
  border-radius: 8px !important;
  font-weight: 500 !important;
  box-shadow: 0 4px 16px rgba(79,110,247,0.2) !important;
}
.el-button--primary:hover {
  background: #3D5CE0 !important;
  box-shadow: 0 8px 28px rgba(79,110,247,0.3) !important;
  transform: translateY(-1px);
}

.el-input__wrapper,
.el-textarea__inner {
  border-radius: 8px !important;
  border: 1px solid var(--border) !important;
  box-shadow: none !important;
  background: rgba(255,255,255,0.04) !important;
  color: #fff !important;
}
.el-input__wrapper.is-focus,
.el-textarea__inner:focus {
  border-color: var(--primary) !important;
  box-shadow: 0 0 0 3px rgba(79,110,247,0.12) !important;
}
.el-input__inner,
.el-textarea__inner {
  color: #fff !important;
}
.el-input__inner::placeholder,
.el-textarea__inner::placeholder {
  color: rgba(255,255,255,0.25) !important;
}

.el-tag {
  border: none !important;
  border-radius: 6px !important;
  font-weight: 500 !important;
}
.el-tag--success { background: rgba(46,125,50,0.2) !important; color: #81C784 !important; }
.el-tag--danger { background: rgba(198,40,40,0.2) !important; color: #EF9A9A !important; }
.el-tag--warning { background: rgba(245,127,23,0.2) !important; color: #FFD54F !important; }
.el-tag--info { background: rgba(255,255,255,0.06) !important; color: rgba(255,255,255,0.5) !important; }

.el-tabs__header {
  border-bottom: 1px solid var(--border) !important;
}
.el-tabs__item {
  font-weight: 500 !important;
  color: rgba(255,255,255,0.4) !important;
}
.el-tabs__item.is-active {
  color: #fff !important;
}
.el-tabs__active-bar {
  background: var(--primary) !important;
  height: 2px !important;
  border-radius: 2px !important;
}

.el-empty .el-empty__description p {
  color: rgba(255,255,255,0.3) !important;
}
.el-empty .el-empty__image {
  opacity: 0.3;
}

.el-dialog {
  border-radius: var(--radius) !important;
  background: rgba(16,16,32,0.92) !important;
  backdrop-filter: blur(24px) !important;
  border: 1px solid var(--border) !important;
}
.el-dialog__title { color: #fff !important; }
.el-dialog__body { color: rgba(255,255,255,0.6) !important; }

.el-alert {
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
}
.el-alert__title { color: #fff !important; }
.el-alert__description { color: rgba(255,255,255,0.5) !important; }

.el-progress__text {
  color: rgba(255,255,255,0.5) !important;
}
.el-progress-bar__outer {
  background: rgba(255,255,255,0.06) !important;
}
.el-progress-bar__inner {
  background: linear-gradient(90deg, #4F6EF7, #7C5CFC) !important;
}

.el-table {
  background: transparent !important;
}
.el-table__header th {
  background: rgba(255,255,255,0.04) !important;
  color: rgba(255,255,255,0.4) !important;
  border-bottom: 1px solid var(--border) !important;
}
.el-table__body td {
  border-bottom: 1px solid var(--border) !important;
  color: rgba(255,255,255,0.7) !important;
}
.el-table__body tr:hover td {
  background: rgba(255,255,255,0.04) !important;
}
.el-table .cell .el-button {
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid var(--border) !important;
  color: rgba(255,255,255,0.5) !important;
}
.el-table .cell .el-button:hover {
  background: rgba(255,255,255,0.08) !important;
  color: #fff !important;
}
.el-loading-mask {
  background: rgba(0,0,0,0.3) !important;
}

/* 表格空状态深色 */
.el-table__empty-block {
  background: transparent !important;
  min-height: 100px !important;
}
.el-table__empty-text {
  color: rgba(255,255,255,0.3) !important;
}
</style>