// api.js — 与 Python 后端（shell.py Bridge）通信的统一封装（纯 JS）

async function req(path, method = 'GET', body) {
  const opt = { method, headers: {} }
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json'
    opt.body = JSON.stringify(body)
  }
  const r = await fetch(path, opt)
  const j = await r.json()
  if (!j.ok) throw new Error(j.error || 'api error')
  return j.data
}

export const api = {
  // 状态 / 帧
  state: () => req('/api/state'),
  stats: () => req('/api/stats'),
  quality: () => req('/api/quality'),
  logs: (n = 30) => req(`/api/logs?n=${n}`),
  frameUrl: (kind, gray) => `/api/frame?kind=${kind}${gray ? '&gray=1' : ''}&t=${Date.now()}`,
  pixel: (x, y) => req(`/api/pixel?x=${x}&y=${y}`),

  // 设备
  deviceScan: (opts = {}) => {
    // 兼容旧调用 deviceScan(true) 与新的 { deep, fast }
    const o = typeof opts === 'boolean' ? { deep: opts } : (opts || {})
    const q = [o.deep ? 'deep=1' : '', o.fast ? 'fast=1' : ''].filter(Boolean).join('&')
    return req(`/api/device_scan${q ? '?' + q : ''}`)
  },
  deviceConnect: () => req('/api/device_connect', 'POST', {}),
  deviceDisconnect: () => req('/api/device_disconnect', 'POST', {}),
  deviceReset: () => req('/api/device_reset', 'POST', {}),

  // 采集
  saveSnapshot: () => req('/api/save_snapshot', 'POST', {}),
  exportCloud: () => req('/api/export_cloud', 'POST', {}),
  toggleContinuous: () => req('/api/toggle_continuous', 'POST', {}),
  setGray: (on) => req('/api/set_gray', 'POST', { on }),
  setFlip: (on) => req('/api/set_flip', 'POST', { on }),
  setPaused: (on) => req('/api/set_paused', 'POST', { on }),

  // 转台
  ttShoot: (step_deg, cam_dist) => req('/api/tt_shoot', 'POST', { step_deg, cam_dist }),
  ttFinish: () => req('/api/tt_finish', 'POST', {}),
  ttStatus: () => req('/api/tt_status'),
  serialPorts: () => req('/api/serial_ports'),
  ttConnect: (port) => req('/api/tt_connect', 'POST', { port }),
  ttDisconnect: () => req('/api/tt_disconnect', 'POST', {}),
  ttConnectStatus: () => req('/api/tt_connect_status'),
  ttAuto: (port, step_deg, wait) => req('/api/tt_auto', 'POST', { port, step_deg, wait }),
  ttAutoStatus: () => req('/api/tt_auto_status'),

  // 手持扫描记录
  scanStart: () => req('/api/scan_start', 'POST', {}),
  scanShoot: () => req('/api/scan_shoot', 'POST', {}),
  scanFinish: () => req('/api/scan_finish', 'POST', {}),
  scanCount: () => req('/api/scan_count'),

  // 融合
  fuse: (dir) => req('/api/fuse', 'POST', { dir }),
  fuseProgress: () => req('/api/fuse_progress'),
  fuseCancel: () => req('/api/fuse_cancel', 'POST', {}),
  listDirs: () => req('/api/list_dirs'),

  // 标定 / 测距
  calibSample: (known_mm, roi) => req('/api/calib_sample', 'POST', { known_mm, roi }),
  calibSave: (k) => req('/api/calib_save', 'POST', { k }),
  measure: (x1, y1, x2, y2) => req('/api/measure', 'POST', { x1, y1, x2, y2 }),

  // 设置
  settings: () => req('/api/settings'),
  setExportDir: (dir) => req('/api/set_export_dir', 'POST', { dir }),
  setPerfMode: (mode) => req('/api/set_perf_mode', 'POST', { mode }),
  setDispRange: (lo, hi) => req('/api/set_disp_range', 'POST', { lo, hi }),
  openDir: (path) => req('/api/open_dir', 'POST', { path }),
  openUrl: (url) => req('/api/open_url', 'POST', { url }),
  paths: () => req('/api/paths'),
  artifactUrl: (path) => `/api/artifact?path=${encodeURIComponent(path)}&t=${Date.now()}`,

  // 关于 / 诊断 / OTA
  about: () => req('/api/about'),
  diag: () => req('/api/diag'),
  checkUpdate: () => req('/api/check_update', 'POST', {}),

  // 应用级更新（update.json）
  updateCheck: () => req('/api/update_check'),
  updateDownload: (url, sha256, latest) => req('/api/update_download', 'POST', { url, sha256, latest }),
  updateStatus: () => req('/api/update_status'),
  updateApply: () => req('/api/update_apply', 'POST', {}),
  // 自动检测（启动即检 + 每 12h；关闭后重置）
  updateState: () => req('/api/update_state'),
  updateCheckNow: () => req('/api/update_check_now', 'POST', {}),

  // 驱动库（随包 驱动工具/，程序内可修复/安装）
  driverState: (deep = false) => req(`/api/driver_state${deep ? '?deep=1' : ''}`),
  driverManifest: () => req('/api/driver_manifest'),
  driverInstall: (driverId = '') => req('/api/driver_install', 'POST', { driver_id: driverId }),
  driverOpenTool: () => req('/api/driver_open_tool', 'POST', {}),
  driverOpenFolder: () => req('/api/driver_open_folder', 'POST', {}),

  // 收尾
  shutdown: () => req('/api/shutdown', 'POST', {}),
}
