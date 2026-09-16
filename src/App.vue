<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import HomeView from './views/HomeView.vue'
import MediaView from './views/MediaView.vue'
import { downloadJobUrl, parseUrlApi } from './api'

const SESSION_KEY = 'videohub.session'

const screen = ref('home')
const homeStatus = ref('idle')
const errorMessage = ref('')
const sourceUrl = ref('')
const result = ref(null)
const toast = ref('')

let toastTimer = 0

function showToast(message) {
  toast.value = message
  clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    toast.value = ''
  }, 2200)
}

function persistSession(view) {
  try {
    sessionStorage.setItem(
      SESSION_KEY,
      JSON.stringify({
        view,
        sourceUrl: sourceUrl.value,
        result: result.value
      })
    )
  } catch {
    /* quota / private mode */
  }
}

function readSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function applyHome() {
  screen.value = 'home'
  homeStatus.value = 'idle'
  errorMessage.value = ''
}

function showMedia() {
  if (!result.value) {
    applyHome()
    return
  }
  screen.value = result.value.kind === 'audio' ? 'audio' : 'video'
}

function goHome() {
  // 返回首页：卸掉预览页（取消加载），不影响浏览器已接管的下载任务
  if (screen.value !== 'home') {
    history.pushState({ view: 'home' }, '', '#/')
  } else {
    history.replaceState({ view: 'home' }, '', '#/')
  }
  applyHome()
  persistSession('home')
}

function goMedia() {
  history.pushState({ view: 'media' }, '', '#/media')
  showMedia()
  persistSession('media')
}

function onPopState(event) {
  const view = event.state?.view || (location.hash.includes('media') ? 'media' : 'home')
  if (view === 'media' && result.value) {
    showMedia()
    persistSession('media')
    return
  }
  applyHome()
  persistSession('home')
}

onMounted(() => {
  const saved = readSession()
  const wantMedia = location.hash.includes('/media')

  if (wantMedia && saved?.result) {
    sourceUrl.value = saved.sourceUrl || ''
    result.value = saved.result
    history.replaceState({ view: 'media' }, '', '#/media')
    showMedia()
  } else {
    if (saved?.sourceUrl) sourceUrl.value = saved.sourceUrl
    if (saved?.result) result.value = saved.result
    history.replaceState({ view: 'home' }, '', '#/')
    applyHome()
  }

  window.addEventListener('popstate', onPopState)
})

onUnmounted(() => {
  window.removeEventListener('popstate', onPopState)
})

async function parse(url) {
  sourceUrl.value = url
  homeStatus.value = 'parsing'
  errorMessage.value = ''
  const parsed = await parseUrlApi(url)
  if (!parsed.ok) {
    homeStatus.value = 'error'
    errorMessage.value = parsed.message
    result.value = null
    history.replaceState({ view: 'home' }, '', '#/')
    screen.value = 'home'
    persistSession('home')
    return
  }
  result.value = parsed.result
  homeStatus.value = 'idle'
  goMedia()
}

function filenameForJob(pageUrl, index) {
  try {
    const u = new URL(pageUrl)
    const bv = (u.pathname.match(/BV[\w]+/) || [])[0]
    const p = u.searchParams.get('p') || String(index + 1)
    if (bv) return `${bv}-P${p}.mp4`
  } catch {
    /* ignore */
  }
  return `video-${index + 1}.mp4`
}

async function onDownload(payload) {
  const jobs = payload?.pageUrls?.filter(Boolean) || []
  if (!jobs.length) {
    showToast('没有可下载的条目')
    return
  }
  // 逐个 fetch 再触发浏览器下载：避免 setTimeout 连点被拦截成只下一个
  showToast(jobs.length > 1 ? `开始下载 ${jobs.length} 个文件…` : '开始下载…')
  let ok = 0
  for (let i = 0; i < jobs.length; i += 1) {
    try {
      const res = await fetch(downloadJobUrl(jobs[i], payload))
      if (!res.ok) {
        const detail = await res.json().catch(() => null)
        throw new Error(
          typeof detail?.detail === 'string' ? detail.detail : `下载失败（${res.status}）`
        )
      }
      const blob = await res.blob()
      const objectUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = objectUrl
      a.download = filenameForJob(jobs[i], i)
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
      ok += 1
      if (i < jobs.length - 1) {
        await new Promise((r) => window.setTimeout(r, 500))
      }
    } catch (err) {
      showToast(err?.message || `第 ${i + 1} 个下载失败`)
    }
  }
  if (ok > 0) {
    showToast(ok > 1 ? `已触发 ${ok} 个下载任务，请看浏览器下载栏` : '已开始下载')
  }
}

function onCopy(text) {
  const full = text.startsWith('http') ? text : `${window.location.origin}${text}`
  navigator.clipboard?.writeText(full).catch(() => {})
  showToast('下载链接已复制')
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="topbar-left">
        <button
          v-if="screen !== 'home'"
          class="back-btn"
          type="button"
          aria-label="返回首页"
          @click="goHome"
        >
          ←
        </button>
        <button class="brand" type="button" @click="goHome">
          <span class="brand-mark">V</span>
          VideoHub
        </button>
      </div>
      <span class="scope">B 站 · 抖音 · YouTube</span>
    </header>

    <HomeView
      v-if="screen === 'home'"
      :status="homeStatus"
      :error-message="errorMessage"
      :initial-url="sourceUrl"
      @parse="parse"
    />

    <MediaView
      v-else
      :result="result"
      @download="onDownload"
      @copy="onCopy"
      @back="goHome"
    />

    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>
