import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import HistoryView from '../views/HistoryView.vue'
import MetricsView from '../views/MetricsView.vue'

const routes = [
  { path: '/', component: HomeView },
  { path: '/history', component: HistoryView },
  { path: '/metrics', component: MetricsView },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router