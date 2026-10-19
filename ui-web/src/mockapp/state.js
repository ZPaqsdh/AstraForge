import depthUrl from './assets/depth.png'

export const STAGES = ['读取帧 + 点云', 'ICP 位姿精修', '体素融合', '网格化', '完成']

export const UPDATE_LOG = [
  { version: '安装器 v4', date: '2026-10-18', note: '单文件双形态、驱动库、轻量卸载器' },
  { version: 'v0.2.10', date: '2026-10-16', note: '出厂标定、采集质量可视化' },
  { version: 'v0.2.9', date: '2026-10-16', note: '方向链统一、设置持久化、4 项修复' },
  { version: 'v0.2.0', date: '2026-10-14', note: 'React UI、模块化管线' },
  { version: 'v0.1.0', date: '2026-10-12', note: 'USB 协议复活、首版' },
]

export const SESSIONS = [
  {
    id: 'tt-2145',
    name: 'turntable_20261018_2145',
    type: '转台',
    frames: 24,
    coverage: 360,
    date: '2026-10-18 21:45',
    thumb: depthUrl,
    artifacts: [],
  },
  {
    id: 'scan-2030',
    name: 'scan_session_20261018_2030',
    type: '手持',
    frames: 38,
    coverage: 280,
    date: '2026-10-18 20:30',
    thumb: depthUrl,
    artifacts: [],
  },
  {
    id: 'tt-1910',
    name: 'turntable_20261017_1910',
    type: '转台',
    frames: 12,
    coverage: 165,
    date: '2026-10-17 19:10',
    thumb: depthUrl,
    artifacts: [],
  },
]

const grid = Array.from({ length: 48 }, (_, i) => {
  const row = Math.floor(i / 8)
  const col = i % 8
  const center = 1 - (Math.abs(col - 3.5) / 4 + Math.abs(row - 2.5) / 3) / 2
  const value = Math.max(0, Math.min(1, center * 0.9 + ((i * 37) % 11) / 55))
  return value
})

export function initialState() {
  return {
    page: 'scan',
    theme: 'light',
    device: 'connected',
    deviceInfo: {
      model: 'ASTRA S Pro',
      pid: '2BC5:0403',
      driver: 'WinUSB',
      serial: '••••••••068',
    },
    streams: { depth: true, rgb: true, fps: 10.4 },
    mode: 'live',
    view: { gray: false, mirror: true, paused: false, quality: true },
    live: { continuous: false, recSec: 0, lastSaved: '尚未保存' },
    handheld: { recording: false, frames: 0, sec: 0 },
    turntable: {
      connected: true,
      port: 'COM3',
      step: 15,
      wait: 0.8,
      dist: 0,
      frames: 0,
      auto: false,
      angle: 0,
    },
    quality: {
      distance: 820,
      status: 'ok',
      coverage: 0.72,
      grid,
    },
    sessions: SESSIONS,
    fusion: {
      selected: 'tt-2145',
      running: false,
      stage: 0,
      pct: 0,
      result: null,
      error: null,
    },
    update: {
      status: 'idle',
      latest: '0.3.0',
      progress: 0,
      checkedAt: '尚未检查',
    },
    settings: {
      exportDir: 'D:\\AstraForge\\扫描输出',
      perf: 'std',
      theme: 'light',
      exposure: '自动',
      resolution: '640 × 480',
    },
    logs: [
      { t: '13:20:01', text: '设备已连接：ASTRA S Pro（WinUSB）', ok: true },
      { t: '13:20:02', text: '深度流 640×480 · 彩色流 640×480', ok: true },
      { t: '13:20:04', text: '采集质量：距离 820 mm · 覆盖 72%', ok: true },
    ],
    toast: null,
    statePanel: false,
  }
}
