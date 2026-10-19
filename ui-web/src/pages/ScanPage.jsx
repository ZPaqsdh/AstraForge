import { useEffect, useRef, useState } from 'react'
import {
  Camera, Play, Square, Download, FolderOpen, RotateCw, SlidersHorizontal,
  Usb, RefreshCw, Check, AlertTriangle, Copy, ChevronDown, ChevronRight,
  Activity, Layers, Crosshair, Ruler, Boxes,
} from 'lucide-react'
import { Btn, Field, Stat, Section, Modal, Pill } from '../ui.jsx'
import { PreviewPair, QualityPanel } from '../components/Preview.jsx'
import { api } from '../api.js'
import { usePoll } from '../hooks.jsx'

const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch (e) {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      return true
    } catch (err) {
      return false
    }
  }
}

function ModeTabs({ mode, setMode }) {
  const modes = [
    ['live', '实时采集', '快照 / 点云 / 连续'],
    ['handheld', '手持扫描', '每 0.5 秒记一帧'],
    ['turntable', '转台扫描', '串口控制 / 自动'],
  ]
  return (
    <div className="af-mode-tabs">
      {modes.map(([id, label, hint]) => (
        <button key={id} className={mode === id ? 'active' : ''} onClick={() => setMode(id)}>
          <b>{label}</b>
          <small>{hint}</small>
        </button>
      ))}
    </div>
  )
}

function DeviceConnect({ stage, scan, error, connecting, onConnect, onDetect, onDriverHelp, onDiagnose }) {
  const depth = (scan && scan.depth) || {}
  const model = depth.pid === '0403' ? 'ASTRA S Pro' : 'Astra 深度相机'
  if (stage === 'checking') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card">
          <div className="af-connect-icon"><RefreshCw size={28} className="af-spin" /></div>
          <h2>正在枚举 Astra 设备</h2>
          <p>只读检查 USB 设备与驱动绑定，不会打开相机。</p>
          <span className="af-connect-note">首次检测约 1–3 秒</span>
        </div>
      </div>
    )
  }
  if (stage === 'connecting') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card">
          <div className="af-connect-icon"><RefreshCw size={28} className="af-spin" /></div>
          <h2>正在连接设备</h2>
          <div className="af-connect-steps">
            <span className="done">打开 USB</span>
            <span className="active">启动深度流</span>
            <span>启动彩色流</span>
          </div>
          <p>首次连接约 1–2 秒。相机独占，请先关闭其他占用程序。</p>
        </div>
      </div>
    )
  }
  if (stage === 'driver') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card warn">
          <div className="af-connect-icon warn"><AlertTriangle size={28} /></div>
          <h2>驱动需要切换</h2>
          <p>检测到 {model}（2BC5:{depth.pid || '0403'}），当前驱动
            <b> {depth.service || '未知'}</b>，运行时无法打开深度流。需要绑定 WinUSB。</p>
          <div className="af-connect-meta">
            <Stat k="设备" v={model} />
            <Stat k="PID" v={depth.pid || '0403'} />
            <Stat k="当前驱动" v={depth.service || '无驱动'} tone="warn" />
            <Stat k="状态" v={depth.status || '—'} />
          </div>
          <div className="af-row center">
            <Btn primary icon={Usb} onClick={onDriverHelp}>查看驱动方案</Btn>
            <Btn icon={RefreshCw} onClick={onDetect}>重新检测</Btn>
            <Btn icon={Copy} onClick={onDiagnose}>复制诊断</Btn>
          </div>
        </div>
      </div>
    )
  }
  if (stage === 'error') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card err">
          <div className="af-connect-icon err"><AlertTriangle size={28} /></div>
          <h2>连接失败</h2>
          <p>{error || 'USB 已被其他程序占用，或设备刚被重新枚举。关闭占用程序后重试。'}</p>
          <div className="af-row center">
            <Btn primary icon={RefreshCw} onClick={onConnect}>重试</Btn>
            <Btn icon={RefreshCw} onClick={onDetect}>重新检测</Btn>
            <Btn icon={Copy} onClick={onDiagnose}>复制诊断</Btn>
          </div>
        </div>
      </div>
    )
  }
  if (stage === 'nostream') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card warn">
          <div className="af-connect-icon warn"><Activity size={28} /></div>
          <h2>设备已打开，但没有数据流</h2>
          <p>USB 链路已建立，深度流尚未启动。先断开再连接一次；如果反复失败，复制诊断发反馈。</p>
          <div className="af-row center">
            <Btn primary icon={RefreshCw} onClick={onConnect}>重新连接</Btn>
            <Btn icon={Copy} onClick={onDiagnose}>复制诊断</Btn>
          </div>
        </div>
      </div>
    )
  }
  if (stage === 'detected') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card">
          <div className="af-connect-icon ok"><Check size={28} /></div>
          <h2>发现设备</h2>
          <p>确认设备信息后连接。连接成功后，深度流与彩色流会同时启动。</p>
          <div className="af-connect-meta">
            <Stat k="型号" v={model} />
            <Stat k="PID" v={depth.pid || '0403'} />
            <Stat k="驱动" v={depth.service || 'WinUSB'} tone="ok" />
            <Stat k="状态" v={depth.status || 'OK'} />
          </div>
          <div className="af-row center">
            <Btn primary icon={Play} onClick={onConnect}>连接设备</Btn>
            <Btn icon={RefreshCw} onClick={onDetect}>重新检测</Btn>
            <Btn icon={Copy} onClick={onDiagnose}>复制诊断</Btn>
          </div>
        </div>
      </div>
    )
  }
  return (
    <div className="af-connect-wrap">
      <div className="af-connect-card">
        <div className="af-connect-icon"><Usb size={28} /></div>
        <h2>未检测到 Astra 设备</h2>
        <p>插好相机后点「重新检测」。深度相机需要绑定 WinUSB；如果装过 obdrv，需要先切换驱动。</p>
        <div className="af-row center">
          <Btn primary icon={RefreshCw} onClick={onDetect}>重新检测</Btn>
          <Btn icon={Usb} onClick={onDriverHelp}>驱动帮助</Btn>
        </div>
        <span className="af-connect-note">
          {scan && scan.ok ? '已枚举 2BC5 设备：0 个' : '设备枚举不可用（PowerShell 检测失败）'}
        </span>
      </div>
    </div>
  )
}

export default function ScanPage({ app }) {
  const { state, reload, showToast, setPage } = app
  const [mode, setMode] = useState('live')
  const [scan, setScan] = useState(null)
  const [scanning, setScanning] = useState(true)
  const [connecting, setConnecting] = useState(false)
  const [connectError, setConnectError] = useState('')
  const [gray, setGray] = useState(() => {
    try { return localStorage.getItem('af-gray') === '1' } catch (e) { return false }
  })
  const [paused, setPaused] = useState(false)
  const [showQuality, setShowQuality] = useState(false)
  const [mirror, setMirror] = useState(true)
  const [settings, setSettings] = useState(null)
  const [lastSaved, setLastSaved] = useState('')
  const [lastSession, setLastSession] = useState(null)
  const [modal, setModal] = useState(null)
  const [hintOpen, setHintOpen] = useState(true)

  const [qual] = usePoll(api.quality, 1200, !!(state && state.device && state.device.streaming))
  const [stats] = usePoll(api.stats, 1000, !!(state && state.device && state.device.streaming))

  // 手持
  const [hh, setHh] = useState({ recording: false, frames: 0, sec: 0 })
  // 转台
  const [tt, setTt] = useState({
    ports: [], port: '', connected: false, auto: false,
    frames: 0, step: 15, wait: 0.8, camDist: 0,
  })

  // 测距 / 标定 / 视图
  const [measure, setMeasure] = useState({ points: [], result: '', busy: false })
  const [calib, setCalib] = useState({ known: '500', roi: '40', sampled: null, busy: false })
  const [range, setRange] = useState({ lo: '0', hi: '2500', busy: false })

  const streaming = !!(state && state.device && state.device.streaming)
  const opened = !!(state && state.device && state.device.connected)
  const exportDir = (state && state.export_dir) || ''
  const mirrorSynced = useRef(false)

  const refreshScan = async (silent = true, deep = false) => {
    setScanning(true)
    try {
      const r = await api.deviceScan(deep)
      setScan(r)
      return r
    } catch (e) {
      if (!silent) showToast(`✗ 检测失败：${e.message || e}`)
      return null
    } finally {
      setScanning(false)
    }
  }

  useEffect(() => {
    refreshScan()
    api.settings().then((s) => {
      setSettings(s)
      setRange({ lo: String(s.disp_range?.[0] ?? 0), hi: String(s.disp_range?.[1] ?? 2500), busy: false })
    }).catch(() => {})
  }, [])

  // 未连接时每 6 秒重新枚举（插拔自动反映）
  useEffect(() => {
    if (streaming) return
    const id = setInterval(() => { refreshScan() }, 6000)
    return () => clearInterval(id)
  }, [streaming])

  // 镜像状态跟随后端持久化值（只同步一次）
  useEffect(() => {
    if (!mirrorSynced.current && state && typeof state.preview_mirror === 'boolean') {
      mirrorSynced.current = true
      setMirror(state.preview_mirror)
    }
  }, [state])

  // 手持记录：每 0.5 秒存一帧
  useEffect(() => {
    if (!hh.recording) return
    let alive = true
    const shoot = setInterval(async () => {
      try {
        const r = await api.scanShoot()
        if (alive && r && r.ok) setHh((h) => ({ ...h, frames: r.count }))
      } catch (e) { /* 单帧失败不中断 */ }
    }, 500)
    const sec = setInterval(() => setHh((h) => ({ ...h, sec: h.sec + 1 })), 1000)
    return () => { alive = false; clearInterval(shoot); clearInterval(sec) }
  }, [hh.recording])

  // 转台：自动扫描时刷新帧数/状态
  useEffect(() => {
    if (mode !== 'turntable') return
    let alive = true
    const tick = async () => {
      try {
        const [st, au] = await Promise.all([api.ttStatus(), api.ttAutoStatus()])
        if (!alive) return
        setTt((t) => ({ ...t, frames: st.count || 0, auto: !!au.on }))
      } catch (e) {}
    }
    tick()
    const id = setInterval(tick, 1200)
    return () => { alive = false; clearInterval(id) }
  }, [mode])

  useEffect(() => {
    if (mode !== 'turntable') return
    api.serialPorts().then((r) => {
      setTt((t) => ({
        ...t,
        ports: r.ports || [],
        port: t.port || (r.ports?.[0]?.[0] || ''),
      }))
    }).catch(() => {})
    api.ttConnectStatus().then((r) => {
      setTt((t) => ({ ...t, connected: !!r.connected, port: r.port || t.port }))
    }).catch(() => {})
  }, [mode])

  const stage = (() => {
    if (streaming) return 'connected'
    if (connecting) return 'connecting'
    if (connectError) return 'error'
    if (opened) return 'nostream'
    if (!scan && scanning) return 'checking'
    const d = (scan && scan.depth) || {}
    if (d.found) return d.state === 'ready' ? 'detected' : 'driver'
    return 'none'
  })()

  const detect = async () => {
    setConnectError('')
    const r = await refreshScan(false, true)
    if (r && r.depth?.found) {
      showToast(r.depth.state === 'ready'
        ? `✓ 已检测到设备 2BC5:${r.depth.pid}`
        : `⚠ 检测到设备，但驱动是 ${r.depth.service || '未知'}`)
    } else {
      showToast('未检测到 Astra 设备（2BC5:0403）')
    }
  }

  const connect = async () => {
    setConnecting(true)
    setConnectError('')
    try {
      const r = await api.deviceConnect()
      await reload()
      if (!r.ok) {
        setConnectError(r.error || '连接失败')
        showToast(`✗ ${r.error || '连接失败'}`, 4500)
      } else {
        showToast('✓ 设备已连接，深度流已启动')
        refreshScan()
      }
    } catch (e) {
      setConnectError(String(e.message || e))
      showToast(`✗ ${e.message || e}`, 4500)
    } finally {
      setConnecting(false)
    }
  }

  const disconnect = async () => {
    try {
      await api.deviceDisconnect()
      await reload()
      showToast('设备已断开（红外已关）')
      setPaused(false)
      setHh({ recording: false, frames: 0, sec: 0 })
      refreshScan()
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    }
  }

  const diagnose = async () => {
    try {
      const d = await api.diag()
      const text = JSON.stringify(d, null, 2)
      const ok = await copyText(text)
      showToast(ok ? '诊断信息已复制到剪贴板' : '诊断已生成，但剪贴板不可用')
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    }
  }

  const toggleGray = () => {
    const v = !gray
    setGray(v)
    try { localStorage.setItem('af-gray', v ? '1' : '0') } catch (e) {}
  }

  const toggleMirror = async () => {
    const v = !mirror
    setMirror(v)
    try { await api.setFlip(v) } catch (e) { showToast(`✗ ${e.message || e}`) }
  }

  const togglePause = async () => {
    const v = !paused
    setPaused(v)
    try { await api.setPaused(v) } catch (e) {}
  }

  const snapshot = async () => {
    try {
      const r = await api.saveSnapshot()
      if (!r.ok) throw new Error(r.error || '保存失败')
      setLastSaved(r.png || r.path)
      showToast(`✓ 快照已保存 → ${r.png || r.path}`, 4200)
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4000)
    }
  }

  const exportCloud = async () => {
    try {
      const r = await api.exportCloud()
      if (!r.ok) throw new Error(r.error || '导出失败')
      showToast(`✓ 点云已导出 → ${r.path}`, 4200)
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4000)
    }
  }

  const toggleContinuous = async () => {
    try {
      const r = await api.toggleContinuous()
      await reload()
      showToast(r.on ? '连续采集开始（每 2 秒自动保存）' : '连续采集已停止')
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    }
  }

  const startHandheld = async () => {
    try {
      await api.scanStart()
      setHh({ recording: true, frames: 0, sec: 0 })
      showToast('开始记录：缓慢绕物体移动（每 0.5 秒一帧）')
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    }
  }

  const stopHandheld = async () => {
    setHh((h) => ({ ...h, recording: false }))
    try {
      const r = await api.scanFinish()
      if (!r.ok) throw new Error(r.error || '这个会话还没有帧')
      setLastSession({ type: 'handheld', dir: r.dir })
      showToast(`✓ 记录完成：${hh.frames} 帧。去融合工作台生成模型`, 4500)
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4000)
    }
  }

  const ttConnect = async () => {
    if (!tt.port) { showToast('先选择串口'); return }
    try {
      const r = await api.ttConnect(tt.port)
      if (!r.ok) throw new Error(r.error || '连接失败')
      setTt((t) => ({ ...t, connected: true }))
      showToast(`✓ 转台控制器已连接：${r.device || tt.port}`)
    } catch (e) {
      setTt((t) => ({ ...t, connected: false }))
      showToast(`✗ ${e.message || e}`, 4500)
    }
  }

  const ttDisconnect = async () => {
    try {
      await api.ttDisconnect()
      setTt((t) => ({ ...t, connected: false, auto: false }))
      showToast('转台控制器已断开')
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    }
  }

  const ttShoot = async () => {
    try {
      const r = await api.ttShoot(Number(tt.step) || 15, Number(tt.camDist) || 0)
      if (!r.ok) throw new Error(r.error || '拍帧失败')
      setTt((t) => ({ ...t, frames: r.count }))
      showToast(`✓ 已拍第 ${r.count} 帧（${Math.min(360, r.count * tt.step)}°）`)
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4000)
    }
  }

  const ttAuto = async () => {
    if (!tt.connected) { showToast('先连接转台控制器'); return }
    try {
      const r = await api.ttAuto(tt.port, Number(tt.step) || 15, Number(tt.wait) || 0.8)
      if (!r.ok) throw new Error(r.error || '自动扫描启动失败')
      setTt((t) => ({ ...t, auto: !!r.on }))
      showToast(r.on ? '自动扫描开始：转满一圈自动停止' : '自动扫描已暂停')
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4500)
    }
  }

  const ttFinish = async () => {
    try {
      const r = await api.ttFinish()
      if (!r.ok) throw new Error(r.error || '至少拍 2 帧才能完成采集')
      setLastSession({ type: 'turntable', dir: r.dir })
      setTt((t) => ({ ...t, auto: false }))
      showToast(`✓ 转台采集完成：${tt.frames} 帧 / ${Math.min(360, tt.frames * tt.step)}°，去融合`, 4500)
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4200)
    }
  }

  const depthClick = async (x, y) => {
    if (modal !== 'measure' || measure.busy) return
    const pts = [...measure.points, { x, y }]
    if (pts.length < 2) {
      setMeasure({ points: pts, result: '', busy: false })
      return
    }
    setMeasure({ points: pts, result: '', busy: true })
    try {
      const r = await api.measure(pts[0].x, pts[0].y, pts[1].x, pts[1].y)
      if (!r.ok) throw new Error(r.error || '测距失败')
      setMeasure({ points: pts, result: `两点 3D 距离：${r.dist_mm} mm`, busy: false })
    } catch (e) {
      setMeasure({ points: pts, result: `✗ ${e.message || e}`, busy: false })
    }
  }

  const doSample = async () => {
    setCalib((c) => ({ ...c, busy: true }))
    try {
      const r = await api.calibSample(Number(calib.known) || 500, Number(calib.roi) || 40)
      if (!r.ok) throw new Error(r.error || '采样失败')
      setCalib((c) => ({ ...c, sampled: r, busy: false }))
      showToast(`采样完成：中位 shift ${r.median} → k=${r.k}`)
    } catch (e) {
      setCalib((c) => ({ ...c, busy: false }))
      showToast(`✗ ${e.message || e}`, 4200)
    }
  }

  const doSaveCalib = async () => {
    if (!calib.sampled) return
    try {
      await api.calibSave(calib.sampled.k)
      setModal(null)
      showToast(`✓ 标定已保存：${calib.sampled.k} mm/shift`)
      await reload()
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    }
  }

  const applyRange = async () => {
    setRange((r) => ({ ...r, busy: true }))
    try {
      await api.setDispRange(Number(range.lo) || 0, Number(range.hi) || 2500)
      setModal(null)
      showToast(`显示范围已应用：${range.lo}–${range.hi}`)
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    } finally {
      setRange((r) => ({ ...r, busy: false }))
    }
  }

  const hhHint = (
    <div className="af-hint-list">
      <span>相机对准物体，距离 0.5–1.5 m</span>
      <span>缓慢绕物体移动，一圈 20–40 秒</span>
      <span>保持物体在画面中心，光照稳定</span>
    </div>
  )

  return (
    <div className="af-page af-scan">
      <header className="af-page-head">
        <div>
          <h1>三维扫描</h1>
          <p>连接设备 → 实时采集 / 手持 / 转台，一个工作区完成</p>
        </div>
        <ModeTabs mode={mode} setMode={setMode} />
      </header>

      {stage === 'connected' ? (
        <>
          <div className="af-device-bar">
            <span className="af-dot ok" />
            <b>ASTRA S Pro</b>
            <span className="af-mono">2BC5:0403</span>
            <span className="af-sep">·</span>
            <span>深度 {state?.device?.streaming ? '流中' : '停止'}</span>
            <span className="af-sep">·</span>
            <span>RGB {String(state?.rgb || '').includes('已连接') ? '流中' : '未连接'}</span>
            <span className="af-sep">·</span>
            <span className="af-mono">{(state?.fps || 0).toFixed(1)} fps</span>
            <span className="af-device-spacer" />
            <Btn small ghost icon={Copy} onClick={diagnose}>诊断</Btn>
            <Btn small onClick={disconnect}>断开</Btn>
          </div>

          <div className="af-scan-grid">
            <section className="af-preview-panel">
              <div className="af-view-toolbar">
                <div className="af-view-title"><Layers size={14} /><b>预览</b><span>RGB + 深度</span></div>
                <div className="af-view-actions">
                  <button className={gray ? 'on' : ''}
                    title="只切换深度画面为灰度；彩色画面保持彩色"
                    onClick={toggleGray}>深度灰度</button>
                  <button className={mirror ? 'on' : ''} onClick={toggleMirror}
                    title="仅镜像预览画面；保存/导出/点云/融合始终是正常方向">预览镜像</button>
                  <button className={paused ? 'on' : ''} onClick={togglePause}>{paused ? '继续' : '暂停'}</button>
                  <span className="af-tool-divider" />
                  <button onClick={() => {
                    setMeasure({ points: [], result: '', busy: false })
                    setModal(modal === 'measure' ? null : 'measure')
                  }}>
                    <Crosshair size={13} /> 测距
                  </button>
                  <button onClick={() => setModal('calib')}><Ruler size={13} /> 标定</button>
                  <button onClick={() => setModal('view')}><SlidersHorizontal size={13} /> 视图</button>
                </div>
              </div>
              <PreviewPair gray={gray} paused={paused} quality={qual}
                showQuality={showQuality}
                measureActive={modal === 'measure'}
                points={modal === 'measure' ? measure.points : []}
                onDepthClick={depthClick} />
              {modal === 'measure' ? (
                <div className="af-measure-float">
                  <div className="af-measure-head">
                    <Crosshair size={14} /><b>测距</b>
                    <span>在深度画面点两个点</span>
                    <button onClick={() => setModal(null)} title="退出测距">×</button>
                  </div>
                  <div className="af-measure-box">
                    <span>点 1</span>
                    <b>{measure.points[0] ? `(${measure.points[0].x}, ${measure.points[0].y})` : '—'}</b>
                    <span>点 2</span>
                    <b>{measure.points[1] ? `(${measure.points[1].x}, ${measure.points[1].y})` : '—'}</b>
                  </div>
                  <div className="af-measure-result">
                    {measure.busy ? '计算中…' : (measure.result || '等待取点')}
                  </div>
                  <div className="af-row">
                    <Btn small onClick={() => setMeasure({ points: [], result: '', busy: false })}>重来</Btn>
                    <Btn small primary onClick={() => setModal(null)}>完成</Btn>
                  </div>
                </div>
              ) : null}
            </section>

            <aside className="af-control-panel">
              {mode === 'live' ? (
                <Section title="实时采集" aside={<Pill tone="ok">LIVE</Pill>}>
                  <div className="af-kv"><span>导出目录</span>
                    <b className="af-mono ellipsis" title={exportDir}>{exportDir || '（读取中…）'}</b></div>
                  <div className="af-kv"><span>最近保存</span>
                    <b className="ellipsis" title={lastSaved}>{lastSaved || '—'}</b></div>
                  <div className="af-kv"><span>连续采集</span>
                    <b className={state?.rec_continuous ? 'ok' : ''}>
                      {state?.rec_continuous ? '录制中' : '关闭'}</b></div>
                  <div className="af-kv"><span>数据帧率</span><b className="af-mono">{stats?.fps ?? '—'} fps</b></div>
                  <div className="af-kv"><span>丢包补偿</span><b className="af-mono">{stats?.padded ?? 0} 帧</b></div>
                  <div className="af-kv"><span>标定值</span>
                    <b className="af-mono">{state?.calib?.toFixed ? state.calib.toFixed(4) : '—'} mm/shift</b></div>
                  <div className="af-hint">快照写入导出目录（深度 PNG + npy + RGB PNG）；点云为 PLY。</div>
                </Section>
              ) : null}

              {mode === 'handheld' ? (
                <Section title="手持扫描" aside={<Pill tone={hh.recording ? 'warn' : ''}>{hh.recording ? 'REC' : '待机'}</Pill>}>
                  <div className="af-stat-grid">
                    <Stat k="已记帧数" v={hh.frames} />
                    <Stat k="记录时长" v={fmt(hh.sec)} />
                  </div>
                  <button className="af-hint-toggle" onClick={() => setHintOpen(!hintOpen)}>
                    {hintOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />} 操作要领
                  </button>
                  {hintOpen ? hhHint : null}
                  {lastSession && lastSession.type === 'handheld' ? (
                    <div className="af-callout ok">
                      <Check size={14} /> 上次会话已保存
                      <div className="af-mono ellipsis" title={lastSession.dir}>{lastSession.dir}</div>
                    </div>
                  ) : null}
                </Section>
              ) : null}

              {mode === 'turntable' ? (
                <Section title="转台扫描" aside={<Pill tone={tt.connected ? 'ok' : ''}>{tt.connected ? '已连接' : '未连接'}</Pill>}>
                  <Field label="串口">
                    <div className="af-inline">
                      <select value={tt.port} onChange={(e) => setTt({ ...tt, port: e.target.value })}>
                        {tt.ports.length === 0 ? <option value="">（未发现串口）</option> : null}
                        {tt.ports.map(([p, desc]) => <option key={p} value={p}>{p} · {desc}</option>)}
                      </select>
                      {tt.connected
                        ? <Btn small onClick={ttDisconnect}>断开</Btn>
                        : <Btn small icon={Usb} onClick={ttConnect}>连接</Btn>}
                    </div>
                  </Field>
                  <div className="af-inline-2">
                    <Field label="步进 (°)"><input value={tt.step}
                      onChange={(e) => setTt({ ...tt, step: Number(e.target.value) || 15 })} /></Field>
                    <Field label="等待 (s)"><input value={tt.wait}
                      onChange={(e) => setTt({ ...tt, wait: Number(e.target.value) || 0.8 })} /></Field>
                  </div>
                  <Field label="相机距离 (mm)" hint="可选：相机到转台轴的距离，用于点云对齐">
                    <input value={tt.camDist}
                      onChange={(e) => setTt({ ...tt, camDist: Number(e.target.value) || 0 })} />
                  </Field>
                  <div className="af-angle">
                    <div className="af-angle-head"><span>已覆盖角度</span>
                      <b>{Math.min(360, tt.frames * tt.step)}°</b></div>
                    <div className="af-bar"><span style={{ width: `${Math.min(100, tt.frames * tt.step / 360 * 100)}%` }} /></div>
                    <div className="af-angle-sub">{tt.frames} 帧 · 每 {tt.step}°</div>
                  </div>
                  {lastSession && lastSession.type === 'turntable' ? (
                    <div className="af-callout ok"><Check size={14} /> 上次转台会话已保存</div>
                  ) : null}
                </Section>
              ) : null}

              <QualityPanel q={qual} showQuality={showQuality} setShowQuality={setShowQuality} compact />
            </aside>
          </div>

          <footer className="af-actionbar">
            <div className="af-action-info">
              {mode === 'live' ? <><span className="af-dot ok" /> 设备就绪，可直接采集</> : null}
              {mode === 'handheld' ? <><span className={`af-dot ${hh.recording ? 'err' : 'ok'}`} />
                {hh.recording ? `正在记录 ${fmt(hh.sec)} · ${hh.frames} 帧` : '等待开始'}</> : null}
              {mode === 'turntable' ? <><span className={`af-dot ${tt.connected ? 'ok' : 'idle'}`} />
                {tt.connected ? `控制器已连接 · ${tt.port}` : '控制器未连接'}</> : null}
            </div>
            <div className="af-actions">
              {mode === 'live' ? (
                <>
                  <Btn icon={FolderOpen} onClick={() => api.openDir(exportDir).catch((e) => showToast(e.message))}>
                    打开目录
                  </Btn>
                  <Btn icon={Download} onClick={exportCloud}>导出点云</Btn>
                  <Btn className={state?.rec_continuous ? 'rec' : ''}
                    icon={state?.rec_continuous ? Square : Play} onClick={toggleContinuous}>
                    {state?.rec_continuous ? '停止连续采集' : '连续采集'}
                  </Btn>
                  <Btn primary icon={Camera} onClick={snapshot}>保存快照</Btn>
                </>
              ) : null}
              {mode === 'handheld' ? (
                <>
                  {hh.frames > 0 ? <Btn icon={Boxes} onClick={() => setPage('fusion')}>去融合</Btn> : null}
                  <Btn primary={!hh.recording} danger={hh.recording}
                    icon={hh.recording ? Square : Play}
                    onClick={hh.recording ? stopHandheld : startHandheld}>
                    {hh.recording ? '停止记录' : '开始记录'}
                  </Btn>
                </>
              ) : null}
              {mode === 'turntable' ? (
                <>
                  <Btn icon={RotateCw} onClick={ttAuto}>{tt.auto ? '暂停自动扫描' : '自动扫描'}</Btn>
                  <Btn icon={Camera} onClick={ttShoot}>拍这一帧</Btn>
                  <Btn primary icon={Check} onClick={ttFinish}>完成采集</Btn>
                </>
              ) : null}
            </div>
          </footer>
        </>
      ) : (
        <DeviceConnect stage={stage} scan={scan} error={connectError}
          connecting={connecting} onConnect={connect} onDetect={detect}
          onDriverHelp={() => setPage('about')} onDiagnose={diagnose} />
      )}

      {modal === 'calib' ? (
        <Modal title="深度标定（shift → mm）" onClose={() => setModal(null)}>
          <p className="af-modal-hint">把已知距离的平面正对镜头，填入真实距离后采样。保存后长期生效。</p>
          <Field label="已知距离 (mm)"><input value={calib.known}
            onChange={(e) => setCalib({ ...calib, known: e.target.value })} /></Field>
          <Field label="采样区边长 (px)"><input value={calib.roi}
            onChange={(e) => setCalib({ ...calib, roi: e.target.value })} /></Field>
          {calib.sampled ? (
            <div className="af-callout ok">
              中位 shift <b>{calib.sampled.median}</b> → k = <b>{calib.sampled.k}</b> mm/shift
            </div>
          ) : null}
          <div className="af-modal-actions">
            <Btn onClick={doSample} disabled={calib.busy}>{calib.busy ? '采样中…' : '采样'}</Btn>
            <Btn primary disabled={!calib.sampled} onClick={doSaveCalib}>保存标定</Btn>
          </div>
        </Modal>
      ) : null}

      {modal === 'view' ? (
        <Modal title="视图设置" onClose={() => setModal(null)}>
          <p className="af-modal-hint">深度色带范围只影响预览，不改变采集数据。</p>
          <div className="af-inline-2">
            <Field label="最小"><input value={range.lo}
              onChange={(e) => setRange({ ...range, lo: e.target.value })} /></Field>
            <Field label="最大"><input value={range.hi}
              onChange={(e) => setRange({ ...range, hi: e.target.value })} /></Field>
          </div>
          <div className="af-modal-actions">
            <Btn onClick={() => setRange({ lo: '0', hi: '2500', busy: false })}>重置 0–2500</Btn>
            <Btn primary disabled={range.busy} onClick={applyRange}>应用</Btn>
          </div>
        </Modal>
      ) : null}

    </div>
  )
}
