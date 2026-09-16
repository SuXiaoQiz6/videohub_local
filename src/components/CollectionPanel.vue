<script setup>
import { computed } from 'vue'
import { PAGE_SIZE } from '../mock'

const props = defineProps({
  collection: { type: Object, required: true },
  currentId: { type: String, required: true },
  selectedIds: { type: Array, required: true },
  page: { type: Number, required: true }
})

const emit = defineEmits(['update:currentId', 'update:selectedIds', 'update:page'])

const totalPages = computed(() => Math.ceil(props.collection.items.length / PAGE_SIZE))

const pageItems = computed(() => {
  const start = (props.page - 1) * PAGE_SIZE
  return props.collection.items.slice(start, start + PAGE_SIZE)
})

const selectedSet = computed(() => new Set(props.selectedIds))
const allSelected = computed(
  () =>
    props.collection.items.length > 0 &&
    props.selectedIds.length === props.collection.items.length
)
const masterClass = computed(() => {
  if (allSelected.value) return 'is-all'
  if (props.selectedIds.length > 0) return 'is-partial'
  return ''
})

function ensureCurrentSelected(ids) {
  const current = props.currentId
  if (current && ids.includes(current)) return ids
  if (current) return [current]
  const first = props.collection.items[0]?.id
  return first ? [first] : ids
}

function toggleMaster() {
  if (allSelected.value) {
    // 取消全选：只保留当前详情这一集
    emit('update:selectedIds', ensureCurrentSelected([]))
  } else {
    emit(
      'update:selectedIds',
      props.collection.items.map((i) => i.id)
    )
  }
}

function toggleItem(id, checked) {
  const next = new Set(props.selectedIds)
  if (checked) {
    next.add(id)
  } else {
    // 至少保留一个勾选
    if (next.size <= 1) return
    next.delete(id)
    if (next.size === 0) return
  }
  emit('update:selectedIds', [...next])
}

function viewDetails(id) {
  if (id === props.currentId) return
  emit('update:currentId', id)
}

function isLastSelected(id) {
  return selectedSet.value.has(id) && props.selectedIds.length === 1
}

const selectedSummary = computed(() => {
  const map = new Map(props.collection.items.map((i) => [i.id, i]))
  const labels = props.selectedIds
    .map((id) => map.get(id))
    .filter(Boolean)
    .sort((a, b) => a.index - b.index)
    .map((i) => `P${i.index}`)
  if (labels.length <= 12) return labels.join('、')
  return `${labels.slice(0, 8).join('、')} 等 ${labels.length} 集`
})
</script>

<template>
  <section class="collection">
    <div class="collection-head">
      <div class="left">
        <button
          class="master-box"
          :class="masterClass"
          type="button"
          :aria-label="allSelected ? '取消全选' : '全选'"
          @click="toggleMaster"
        >
          <span v-if="allSelected">✓</span>
          <span v-else class="dash" />
        </button>
        <h3>{{ collection.collectionName }}</h3>
      </div>
      <span class="count">共 {{ collection.collectionCount }} 集</span>
    </div>

    <div
      v-for="item in pageItems"
      :key="item.id"
      class="item"
      :class="{ 'is-current': item.id === currentId }"
    >
      <input
        type="checkbox"
        :checked="selectedSet.has(item.id)"
        :disabled="isLastSelected(item.id)"
        :aria-label="'选择 ' + item.title"
        @change="toggleItem(item.id, $event.target.checked)"
      />
      <span class="title">{{ item.title }}</span>
      <button
        class="btn btn-ghost"
        type="button"
        :disabled="item.id === currentId"
        @click="viewDetails(item.id)"
      >
        {{ item.id === currentId ? '当前详情' : '查看详情' }}
      </button>
    </div>

    <p class="selected-bar">
      已选 {{ selectedIds.length }} 条：{{ selectedSummary }}
    </p>

    <nav class="pager" aria-label="合集分页">
      <button
        class="page-btn"
        type="button"
        :disabled="page <= 1"
        @click="emit('update:page', page - 1)"
      >
        上一页
      </button>
      <button
        v-for="p in totalPages"
        :key="p"
        class="page-btn"
        :class="{ 'is-active': p === page }"
        type="button"
        @click="emit('update:page', p)"
      >
        {{ p }}
      </button>
      <button
        class="page-btn"
        type="button"
        :disabled="page >= totalPages"
        @click="emit('update:page', page + 1)"
      >
        下一页
      </button>
    </nav>
  </section>
</template>
