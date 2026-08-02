import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from './api.js'

const routes = [
  {
    path: "/login",
    name: "login",
    component: () => import("./views/LoginView.vue"),
  },
  {
    path: "/",
    name: "dashboard",
    component: () => import("./views/DashboardView.vue"),
  },
  {
    path: "/sites",
    name: "sites",
    component: () => import("./views/SitesView.vue"),
  },
  {
    path: "/projects",
    name: "projects",
    component: () => import("./views/ProjectsView.vue"),
  },
  {
    path: "/appstore",
    name: "appstore",
    component: () => import("./views/AppStoreView.vue"),
  },
  {
    path: "/files/:siteId?",
    name: "files",
    component: () => import("./views/FileManagerView.vue"),
  },
  {
    path: "/files-generic/:rootKey?",
    name: "files-generic",
    component: () => import("./views/FileManagerGenericView.vue"),
  },
  {
    path: "/databases",
    name: "databases",
    component: () => import("./views/DatabasesView.vue"),
  },
  {
    path: "/trash",
    name: "trash",
    component: () => import("./views/TrashView.vue"),
  },
  {
    path: "/logs",
    name: "logs",
    component: () => import("./views/LogsView.vue"),
  },
  {
    path: "/terminal",
    name: "terminal",
    component: () => import("./views/TerminalView.vue"),
  },
  {
    path: "/backup",
    name: "backup",
    component: () => import("./views/BackupView.vue"),
  },
  { path: "/ftp", name: "ftp", component: () => import("./views/FtpView.vue") },
  {
    path: "/settings",
    name: "settings",
    component: () => import("./views/SettingsView.vue"),
  },
  {
    path: "/users",
    name: "users",
    component: () => import("./views/UsersView.vue"),
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Guard: tanpa token → login; sudah login di /login → dashboard.
router.beforeEach((to) => {
  if (!getToken() && to.name !== 'login') return { name: 'login' }
  if (getToken() && to.name === 'login') return { name: 'dashboard' }
})

export default router
