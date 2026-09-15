const EPISODE_TOPICS = [
  '环境安装与解释器',
  '变量、类型与表达式',
  '字符串与格式化',
  '列表与切片',
  '字典与集合',
  '条件分支',
  'for / while 循环',
  '函数与参数',
  '模块与包',
  '文件读写',
  '异常处理基础',
  '列表推导式',
  '面向对象入门',
  '类与实例',
  'Async/await 与错误处理',
  '生成器与迭代器',
  '装饰器',
  '上下文管理器',
  '标准库常用模块',
  '正则表达式',
  '日期与时间',
  'JSON 与序列化',
  '虚拟环境',
  'pip 与依赖管理',
  '单元测试入门',
  '调试技巧',
  '日志',
  '类型提示',
  '数据类',
  '枚举',
  '路径与 pathlib',
  '命令行参数',
  '并发：线程',
  '并发：进程',
  'asyncio 任务组',
  'HTTP 请求',
  '爬虫礼貌与限制',
  'CSV 处理',
  'Excel 读写',
  'SQLite 基础',
  'SQL 查询',
  '数据清洗',
  'Pandas 入门',
  '可视化入门',
  'NumPy 数组',
  '函数式编程',
  '闭包',
  '作用域',
  '内存与引用',
  '拷贝与可变性',
  '设计小练习 1',
  '设计小练习 2',
  'Web 请求封装',
  '配置文件',
  '环境变量',
  '密钥不要入库',
  'Git 基础',
  '项目结构',
  '代码风格 PEP8',
  '文档字符串',
  '打包发布入门',
  '性能常识',
  '剖析瓶颈',
  '缓存思路',
  '重试与超时',
  '分页数据',
  '流式读写',
  '字幕与文本处理',
  '音视频元数据概念',
  '下载器架构概述',
  'URL 解析思路',
  '合集列表建模',
  '选择状态设计',
  '清晰度与格式',
  '失败重试',
  '本地保存路径',
  '合法使用边界',
  '期末作业讲解',
  '常见坑',
  '课程总结与复习'
]

function pad(n) {
  return String(n).padStart(2, '0')
}

export const DEMO = {
  // YouTube 公开视频（无 cookies 通常可解析）
  single: 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
  // B 站 / 抖音多数环境需要 backend/cookies.txt（见 README）
  collection: 'https://www.bilibili.com/video/BV1GJ411x7h7',
  audio: 'https://www.youtube.com/watch?v=jNQXAC9IVRw',
  invalid: 'notaurl'
}

export const PAGE_SIZE = 10

function collectionItems() {
  return EPISODE_TOPICS.map((topic, i) => {
    const index = i + 1
    return {
      id: `ep-${index}`,
      index,
      title: `P${index} · ${topic}`,
      duration: `${pad(8 + (i % 12))}:${pad((i * 7) % 60)}`,
      author: 'TechLab',
      views: `${(12.4 + (i % 40) * 0.7).toFixed(1)}万`,
      likes: `${(1.2 + (i % 20) * 0.15).toFixed(1)}万`,
      description:
        'Python 系统课第 ' +
        index +
        ' 讲：' +
        topic +
        '。适合离线收藏后反复看，内容来自公开课程页。',
      downloadUrl: `https://cdn.videohub.local/mock/python-${index}.mp4`
    }
  })
}

const COLLECTION = {
  kind: 'collection',
  platform: 'Bilibili',
  collectionName: 'Python 零基础到实战 · 80 讲',
  collectionCount: 80,
  parsedId: 'ep-15',
  qualities: ['1080p', '720p', '480p'],
  defaultQuality: '1080p',
  items: collectionItems()
}

const SINGLE = {
  kind: 'video',
  platform: '抖音',
  qualities: ['1080p', '720p'],
  defaultQuality: '1080p',
  item: {
    id: 'dy-1',
    title: '把办公桌收成一条干净的工作流',
    author: 'DeskCraft',
    views: '86.2万',
    likes: '12.4万',
    duration: '00:47',
    description:
      '三分钟桌面整理：键盘区、显示器支架和线材收纳。公开短视频，适合本地收藏。',
    downloadUrl: 'https://cdn.videohub.local/mock/douyin-desk.mp4'
  }
}

const AUDIO = {
  kind: 'audio',
  platform: 'YouTube',
  formats: ['mp3', 'm4a', 'wav'],
  defaultFormat: 'mp3',
  item: {
    id: 'yt-a1',
    title: 'Loops in Python — lecture audio',
    author: 'CS Primer',
    views: '54.8万',
    likes: '9.1万',
    duration: '18:42',
    description:
      '公开讲座音频：for / while、提前终止与常见循环错误。仅音频资源。',
    downloadUrl: 'https://cdn.videohub.local/mock/python-loops.mp3'
  }
}

export function isEmptyInput(value) {
  return !String(value || '').trim()
}

export function looksLikeUrl(value) {
  const v = String(value || '').trim()
  try {
    const u = new URL(v)
    return u.protocol === 'http:' || u.protocol === 'https:'
  } catch {
    return false
  }
}

export function parseUrl(raw) {
  const url = String(raw || '').trim()
  if (isEmptyInput(url)) {
    return { ok: false, code: 'empty', message: '请输入想要解析的音视频资源链接' }
  }
  if (!looksLikeUrl(url)) {
    return {
      ok: false,
      code: 'format',
      message: 'URL 格式错误。请输入 B 站、抖音或 YouTube 的音视频页面链接。'
    }
  }
  const lower = url.toLowerCase()
  if (lower.includes('bilibili.com') || lower.includes('b23.tv')) {
    return { ok: true, result: structuredClone(COLLECTION), sourceUrl: url }
  }
  if (lower.includes('douyin.com') || lower.includes('iesdouyin.com')) {
    return { ok: true, result: structuredClone(SINGLE), sourceUrl: url }
  }
  if (lower.includes('youtube.com') || lower.includes('youtu.be')) {
    return { ok: true, result: structuredClone(AUDIO), sourceUrl: url }
  }
  return {
    ok: false,
    code: 'platform',
    message: '暂不支持该平台。MVP 仅支持 B 站、抖音、YouTube。'
  }
}

export function pageForIndex(index, pageSize = PAGE_SIZE) {
  return Math.ceil(index / pageSize)
}
