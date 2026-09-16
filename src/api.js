/**
 * Frontend API client for VideoHub parse service.
 * Dev: Vite proxies /api → http://127.0.0.1:8000
 */

export async function parseUrlApi(url) {
  const trimmed = String(url || '').trim()
  if (!trimmed) {
    return {
      ok: false,
      code: 'empty',
      message: '请输入想要解析的音视频资源链接'
    }
  }

  let res
  try {
    res = await fetch('/api/parse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: trimmed })
    })
  } catch {
    return {
      ok: false,
      code: 'network',
      message: '无法连接解析服务。请确认后端已启动（backend/start.bat）。'
    }
  }

  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }

  if (!res.ok) {
    const detail = data?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d) => d.msg || d).join('; ')
          : '解析失败，请稍后重试'
    return {
      ok: false,
      code: res.status === 400 ? 'format' : 'parse',
      message
    }
  }

  if (!data?.ok || !data?.result) {
    return { ok: false, code: 'parse', message: '解析失败：返回数据无效' }
  }

  return { ok: true, result: data.result, sourceUrl: trimmed }
}

function mediaQuery(pageUrl, { quality, format, isAudio } = {}) {
  const q = new URLSearchParams({
    url: pageUrl,
    quality: quality || 'best'
  })
  if (isAudio && format) {
    q.set('format', format)
    q.set('audio', 'true')
  }
  return q.toString()
}

export function downloadJobUrl(pageUrl, opts = {}) {
  return `/api/download?${mediaQuery(pageUrl, opts)}`
}

export function streamJobUrl(pageUrl, opts = {}) {
  return `/api/stream?${mediaQuery(pageUrl, opts)}`
}

export async function resolveItemApi(url) {
  try {
    const res = await fetch('/api/resolve-item', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    })
    const data = await res.json()
    if (!res.ok || !data?.ok) return null
    return data
  } catch {
    return null
  }
}
