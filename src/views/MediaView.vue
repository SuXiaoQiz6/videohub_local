<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import CollectionPanel from '../components/CollectionPanel.vue'
import { downloadJobUrl, resolveItemApi, streamJobUrl } from '../api'
import { PAGE_SIZE, pageForIndex } from '../mock'

const props = defineProps({
  result: { type: Object, required: true }
})

const emit = defineEmits(['download', 'copy', 'back'])

const isAudio = computed(() => props.result.kind === 'audio')
const isCollection = computed(() => props.result.kind === 'collection')

const ui = reactive({
  quality: props.result.defaultQuality || props.result.qualities?.[0] || '1080p',
  format: props.result.defaultFormat || props.result.formats?.[0] || 'mp3',
  currentId: '',
  selectedIds: [],
  page: 1,
  qualities: props.result.qualities || ['best'],
  resolving: false
})

const playError = ref('')
const previewLoading = ref(false)
const mediaSrc = ref('')
let objectUrl = ''
let loadToken = 0
let previewAbort = null

function resetFromResult() {
  const r = props.result
  ui.qualities = r.qualities || ['best']
  if (r.kind === 'collection') {
    ui.currentId = r.parsedId
    ui.selectedIds = [r.parsedId]
    const item = r.items.find((i) => i.id === r.parsedId)
    ui.page = item ? pageForIndex(item.index, PAGE_SIZE) : 1
    ui.quality = r.defaultQuality || ui.qualities[0]
  } else if (r.kind === 'video') {
    ui.currentId = r.item.id
    ui.selectedIds = [r.item.id]
    ui.quality = r.defaultQuality || ui.qualities[0]
  } else {
    ui.currentId = r.item.id
    ui.selectedIds = [r.item.id]
    ui.format = r.defaultFormat
  }
}

watch(
  () => props.result,
  () => resetFromResult(),
  { immediate: true }
)

const currentItem = computed(() => {
  const r = props.result
  if (r.kind === 'collection') return r.items.find((i) => i.id === ui.currentId)
  return r.item
})

const selectedCount = computed(() => ui.selectedIds.length)
const showCopy = computed(() => selectedCount.value === 1)

/** Preview uses lowest available quality so the player loads quickly. */
const previewQuality = computed(() => {
  const list = ui.qualities || []
  if (!list.length) return ui.quality
  return list[list.length - 1]
})

function revokePreview() {
  if (objectUrl) {
    URL.revokeObjectURL(objectUrl)
    objectUrl = ''
  }
  mediaSrc.value = ''
}

function cancelPreviewLoad() {
  loadToken += 1
  if (previewAbort) {
    previewAbort.abort()
    previewAbort = null
  }
  previewLoading.value = false
  revokePreview()
}

async function loadPreview() {
  const pageUrl = currentItem.value?.webpageUrl || props.result.sourceUrl
  if (!pageUrl) {
    cancelPreviewLoad()
    return
  }
  if (previewAbort) previewAbort.abort()
  const ac = new AbortController()
  previewAbort = ac
  const token = ++loadToken
  previewLoading.value = true
  playError.value = ''
  revokePreview()

  const url = streamJobUrl(pageUrl, {
    quality: isAudio.value ? ui.quality : previewQuality.value,
    format: ui.format,
    isAudio: isAudio.value
  })

  // YouTube files are large; stream via same-origin URL + Range.
  // Bilibili/抖音 keep blob preview (already stable).
  const platform = String(props.result.platform || '').toLowerCase()
  const useDirectStream = platform.includes('youtube')

  try {
    if (useDirectStream) {
      const res = await fetch(url, {
        signal: ac.signal,
        headers: { Range: 'bytes=0-1' }
      })
      if (token !== loadToken) return
      if (!res.ok) {
        const detail = await res.json().catch(() => null)
        throw new Error(
          typeof detail?.detail === 'string' ? detail.detail : `预览失败（${res.status}）`
        )
      }
      mediaSrc.value = url
    } else {
      const res = await fetch(url, { signal: ac.signal })
      if (token !== loadToken) return
      if (!res.ok) {
        const detail = await res.json().catch(() => null)
        throw new Error(
          typeof detail?.detail === 'string' ? detail.detail : `预览失败（${res.status}）`
        )
      }
      const blob = await res.blob()
      if (token !== loadToken) return
      objectUrl = URL.createObjectURL(blob)
      mediaSrc.value = objectUrl
    }
  } catch (err) {
    if (err?.name === 'AbortError' || token !== loadToken) return
    playError.value = err?.message || '暂时无法预览，请直接下载'
    mediaSrc.value = ''
  } finally {
    if (token === loadToken) {
      previewLoading.value = false
      if (previewAbort === ac) previewAbort = null
    }
  }
}

watch(
  () => [
    currentItem.value?.webpageUrl,
    props.result.sourceUrl,
    previewQuality.value,
    ui.format,
    isAudio.value
  ],
  () => {
    loadPreview()
  },
  { immediate: true }
)

onUnmounted(() => {
  // 返回首页 / 切走页面：只取消预览请求，不碰浏览器下载栏里的任务
  cancelPreviewLoad()
})

function selectedPageUrls() {
  if (props.result.kind === 'collection') {
    return ui.selectedIds
      .map((id) => props.result.items.find((i) => i.id === id)?.webpageUrl)
      .filter(Boolean)
  }
  return [props.result.item.webpageUrl || props.result.sourceUrl].filter(Boolean)
}

function copyLink() {
  const urls = selectedPageUrls()
  emit(
    'copy',
    downloadJobUrl(urls[0] || '', {
      quality: ui.quality,
      format: ui.format,
      isAudio: isAudio.value
    })
  )
}

function download() {
  emit('download', {
    pageUrls: selectedPageUrls(),
    quality: ui.quality,
    format: ui.format,
    isAudio: isAudio.value
  })
}

async function onCurrentId(id) {
  ui.currentId = id
  if (!isCollection.value) return
  const item = props.result.items.find((i) => i.id === id)
  if (!item) return
  const needs =
    !item.downloadUrl ||
    item.downloadUrl === item.webpageUrl ||
    item.duration === '00:00'
  if (!needs || !item.webpageUrl) return
  ui.resolving = true
  const data = await resolveItemApi(item.webpageUrl)
  ui.resolving = false
  if (!data?.item) return
  Object.assign(item, data.item)
  if (data.qualities?.length) {
    ui.qualities = data.qualities
    ui.quality = data.defaultQuality || data.qualities[0]
  }
}
</script>

<template>
  <main class="page media-layout">
    <section class="card">
      <button class="back-link" type="button" @click="emit('back')">← 返回首页</button>

      <div class="player" :class="{ audio: isAudio }">
        <div v-if="previewLoading" class="player-overlay">正在加载预览…</div>
        <audio
          v-else-if="isAudio && mediaSrc"
          :key="mediaSrc"
          class="native-player"
          :src="mediaSrc"
          controls
          preload="auto"
        />
        <video
          v-else-if="mediaSrc"
          :key="mediaSrc"
          class="native-player"
          :src="mediaSrc"
          :poster="currentItem?.thumbnail || undefined"
          controls
          preload="auto"
          playsinline
        />
        <div v-else class="player-overlay muted">
          {{ playError || '暂无预览' }}
        </div>
      </div>
      <p v-if="playError && mediaSrc" class="player-error">{{ playError }}</p>
      <p v-else-if="ui.resolving" class="player-hint">正在拉取当前集详情…</p>

      <div class="meta-row">
        <span class="badge">{{ result.platform }}</span>
        <span>{{ currentItem?.author || '-' }}</span>
        <span>{{ currentItem?.views || '-' }}播放</span>
        <span>{{ currentItem?.likes || '-' }}赞</span>
        <span>{{ currentItem?.duration || '-' }}</span>
      </div>
      <h2 class="meta-title">{{ currentItem?.title || '…' }}</h2>
      <p class="desc">{{ currentItem?.description || '' }}</p>

      <CollectionPanel
        v-if="isCollection"
        :collection="result"
        :current-id="ui.currentId"
        :selected-ids="ui.selectedIds"
        :page="ui.page"
        @update:current-id="onCurrentId"
        @update:selected-ids="
          (ids) => {
            ui.selectedIds = ids?.length ? ids : [ui.currentId]
          }
        "
        @update:page="ui.page = $event"
      />

      <div class="actions">
        <label v-if="!isAudio">
          <select v-model="ui.quality" class="select" aria-label="清晰度">
            <option v-for="q in ui.qualities" :key="q" :value="q">{{ q }}</option>
          </select>
        </label>
        <label v-else>
          <select v-model="ui.format" class="select" aria-label="音频格式">
            <option v-for="f in result.formats" :key="f" :value="f">{{ f }}</option>
          </select>
        </label>

        <button class="btn btn-primary" type="button" @click="download">
          下载{{ isCollection && selectedCount > 1 ? `（${selectedCount}）` : '' }}
        </button>
        <button
          v-if="showCopy"
          class="btn btn-secondary"
          type="button"
          @click="copyLink"
        >
          复制下载链接
        </button>
      </div>
    </section>
  </main>
</template>
