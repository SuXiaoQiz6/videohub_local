<script setup>
import { ref, watch } from 'vue'
import { DEMO } from '../mock'

const props = defineProps({
  status: { type: String, required: true },
  errorMessage: { type: String, default: '' },
  initialUrl: { type: String, default: '' }
})

const emit = defineEmits(['parse'])
const url = ref(props.initialUrl)

watch(
  () => props.initialUrl,
  (v) => {
    if (v && !url.value) url.value = v
  }
)

const parsing = () => props.status === 'parsing'

function submit() {
  if (parsing()) return
  emit('parse', url.value)
}

function fill(demo) {
  url.value = demo
}
</script>

<template>
  <main class="home">
    <h1 class="home-logo">VideoHub</h1>
    <p class="home-sub">解析公开音视频链接，用统一方式选择并保存到本地</p>

    <form class="parse-form" @submit.prevent="submit">
      <div class="parse-row">
        <div class="parse-field">
          <input
            class="input"
            :class="{ 'is-error': status === 'error' }"
            :value="url"
            :disabled="parsing()"
            placeholder="输入视频或音频链接开始解析下载"
            @input="url = $event.target.value"
          />
          <p v-if="status === 'error'" class="field-error">
            {{ errorMessage }}
          </p>
        </div>
        <button class="btn btn-primary" type="submit" :disabled="parsing()">
          <span v-if="parsing()" class="spinner" />
          {{ parsing() ? '解析中' : '解析' }}
        </button>
      </div>
    </form>

    <div class="examples">
      <button class="chip" type="button" :disabled="parsing()" @click="fill(DEMO.single)">
        YouTube 单视频（可测）
      </button>
      <button class="chip" type="button" :disabled="parsing()" @click="fill(DEMO.collection)">
        B 站示例（需 cookies）
      </button>
      <button class="chip" type="button" :disabled="parsing()" @click="fill(DEMO.invalid)">
        失败示例
      </button>
    </div>
  </main>
</template>
