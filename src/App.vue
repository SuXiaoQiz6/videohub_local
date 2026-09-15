<script setup>
import { computed, ref } from 'vue'
import HomeView from './views/HomeView.vue'
import MediaView from './views/MediaView.vue'
import { parseUrlApi } from './api'

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

function goHome() {
  screen.value = 'home'
  homeStatus.value = 'idle'
  errorMessage.value = ''
}

async function parse(url) {
  sourceUrl.value = url
  homeStatus.value = 'parsing'
  errorMessage.value = ''
  const parsed = await parseUrlApi(url)
  if (!parsed.ok) {
    homeStatus.value = 'error'
    errorMessage.value = parsed.message
    screen.value = 'home'
    result.value = null
    return
  }
  result.value = parsed.result
  homeStatus.value = 'idle'
  screen.value = parsed.result.kind === 'audio' ? 'audio' : 'video'
}

function onDownload(payload) {
  const urls = Array.isArray(payload) ? payload : [payload]
  const valid = urls.filter(Boolean)
  if (!valid.length) {
    showToast('暂无可用下载链接')
    return
  }
  // MVP: browser download — open first link; multi = open sequentially (popup may block)
  valid.slice(0, 5).forEach((u, i) => {
    window.setTimeout(() => {
      const a = document.createElement('a')
      a.href = u
      a.target = '_blank'
      a.rel = 'noopener'
      a.download = ''
      document.body.appendChild(a)
      a.click()
      a.remove()
    }, i * 200)
  })
  showToast(
    valid.length > 1
      ? `已尝试打开 ${Math.min(valid.length, 5)} 个下载（浏览器直链）`
      : '已开始在浏览器中下载'
  )
}

function onCopy(text) {
  navigator.clipboard?.writeText(text).catch(() => {})
  showToast('下载链接已复制')
}
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <button class="brand" type="button" @click="goHome">
        <span class="brand-mark">V</span>
        VideoHub
      </button>
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
    />

    <div v-if="toast" class="toast">{{ toast }}</div>
  </div>
</template>
