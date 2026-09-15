<script setup>
import { computed, reactive, watch } from 'vue'
import CollectionPanel from '../components/CollectionPanel.vue'
import { resolveItemApi } from '../api'
import { PAGE_SIZE, pageForIndex } from '../mock'

const props = defineProps({
  result: { type: Object, required: true }
})

const emit = defineEmits(['download', 'copy'])

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

function selectedDownloadUrls() {
  if (props.result.kind === 'collection') {
    return ui.selectedIds
      .map((id) => props.result.items.find((i) => i.id === id)?.downloadUrl)
      .filter(Boolean)
  }
  const u = props.result.item.downloadUrl
  return u ? [u] : []
}

function copyLink() {
  const urls = selectedDownloadUrls()
  emit('copy', urls[0] || '')
}

function download() {
  emit('download', selectedDownloadUrls())
}

async function onCurrentId(id) {
  ui.currentId = id
  if (!isCollection.value) return
  const item = props.result.items.find((i) => i.id === id)
  if (!item) return
  // Enrich when download URL missing or same as webpage
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
      <div class="player" :class="{ audio: isAudio }">
        <button class="play-orb" type="button" aria-label="播放">▶</button>
        <div v-if="isAudio" class="scrubber"><i /></div>
        <span class="hint" style="color:#a1a1aa;margin:0">
          {{ isAudio ? '音频播放器 · 原音频预览' : '简易播放器 · 原视频预览' }}
        </span>
        <span v-if="ui.resolving" class="hint" style="color:#a5b4fc;margin:0">
          正在拉取当前集详情…
        </span>
      </div>

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
        @update:selected-ids="ui.selectedIds = $event"
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
