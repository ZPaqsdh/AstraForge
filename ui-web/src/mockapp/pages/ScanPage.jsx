import { useEffect, useState } from 'react'
import {
  Camera, Play, Square, Download, FolderOpen, RotateCw, SlidersHorizontal,
  Usb, RefreshCw, Check, AlertTriangle, Copy, ChevronDown, ChevronRight,
  Activity, Layers, Crosshair, Ruler, Gauge, Boxes,
} from 'lucide-react'
import { Btn, Field, Stat, Section, DeviceBar, ConnectionView, PreviewPair, QualityPanel, Modal } from '../components.jsx'
import depthUrl from '../assets/depth.png'

const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

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

export default function ScanPage({ state, setState, toast, setPage }) {
  const { mode, device, view, live, handheld, turntable, quality } = state
  const [modal, setModal] = useState(null)
  const [hintOpen, setHintOpen] = useState(true)
  const [calib, setCalib] = useState({ known: '500', roi: '40', sampled: null })
  const [range, setRange] = useState({ lo: '0', hi: '2500' })

  const patch = (fn) => setState((s) => fn(s))
  const setView = (v) => patch((s) => ({ ...s, view: v }))
  const setMode = (m) => patch((s) => ({ ...s, mode: m }))

  useEffect(() => {
    if (!live.continuous) return
    const id = setInterval(() => {
      patch((s) => ({ ...s, live: { ...s.live, recSec: s.live.recSec + 1 } }))
    }, 1000)
    return () => clearInterval(id)
  }, [live.continuous])

  useEffect(() => {
    if (!handheld.recording) return
    const a = setInterval(() => {
      patch((s) => ({ ...s, handheld: { ...s.handheld, frames: s.handheld.frames + 1 } }))
    }, 500)
    const b = setInterval(() => {
      patch((s) => ({ ...s, handheld: { ...s.handheld, sec: s.handheld.sec + 1 } }))
    }, 1000)
    return () => { clearInterval(a); clearInterval(b) }
  }, [handheld.recording])

  useEffect(() => {
    if (!turntable.auto) return
    const id = setInterval(() => {
      patch((s) => {
        const t = s.turntable
        const frames = Math.min(t.frames + 1, Math.ceil(360 / t.step))
        const angle = Math.min(360, frames * t.step)
        if (frames >= Math.ceil(360 / t.step)) {
          return { ...s, turntable: { ...t, frames, angle, auto: false } }
        }
        return { ...s, turntable: { ...t, frames, angle } }
      })
    }, Math.max(280, turntable.wait * 1000))
    return () => clearInterval(id)
  }, [turntable.auto, turntable.wait, turntable.step])

  const addLog = (text, ok = true) => patch((s) => ({ ...s, logs: [...s.logs.slice(-19), { t: new Date().toTimeString().slice(0, 8), text, ok }] }))

  const connectDevice = () => {
    patch((s) => ({ ...s, device: 'connecting' }))
    setTimeout(() => {
      patch((s) => ({
        ...s,
        device: 'connected',
        streams: { ...s.streams, depth: true, rgb: true },
        logs: [...s.logs.slice(-19), { t: new Date().toTimeString().slice(0, 8), text: '设备已连接：ASTRA S Pro（WinUSB）', ok: true }],
      }))
      toast('设备已连接，深度流与彩色流已启动')
    }, 1100)
  }

  const disconnect = () => {
    patch((s) => ({ ...s, device: 'detected', streams: { ...s.streams, depth: false, rgb: false } }))
    addLog('设备已断开', false)
    toast('设备已断开')
  }

  const detect = () => {
    patch((s) => ({ ...s, device: 'detected' }))
    toast('已重新检测到 ASTRA S Pro')
  }

  const snapshot = () => {
    const name = `snapshot_${new Date().toTimeString().slice(0, 8).replace(/:/g, '')}.png`
    patch((s) => ({ ...s, live: { ...s.live, lastSaved: name } }))
    addLog(`已保存快照 ${name}`)
    toast('快照已保存到导出目录')
  }

  const exportCloud = () => {
    addLog('已导出 pointcloud.ply')
    toast('点云已导出（复刻台：假文件）')
  }

  const toggleContinuous = () => {
    patch((s) => ({ ...s, live: { ...s.live, continuous: !s.live.continuous, recSec: s.live.continuous ? 0 : s.live.recSec } }))
    toast(live.continuous ? '连续采集已停止' : '连续采集已开始（每 2 秒一帧）')
  }

  const startHandheld = () => {
    patch((s) => ({ ...s, handheld: { recording: true, frames: 0, sec: 0 } }))
    addLog('手持扫描开始')
    toast('开始记录：缓慢绕物体移动')
  }

  const stopHandheld = () => {
    const frames = handheld.frames
    const id = `scan-${Date.now()}`
    patch((s) => ({
      ...s,
      handheld: { ...s.handheld, recording: false },
      sessions: [{
        id, name: `scan_session_${new Date().toTimeString().slice(0, 5).replace(':', '')}`,
        type: '手持', frames, coverage: Math.min(360, frames * 8), date: '刚刚', thumb: depthUrl, artifacts: [],
      }, ...s.sessions],
      fusion: { ...s.fusion, selected: id },
    }))
    addLog(`手持扫描完成：${frames} 帧`)
    toast(`记录完成，共 ${frames} 帧。去融合页生成模型`)
  }

  const ttToggleConnect = () => {
    patch((s) => ({ ...s, turntable: { ...s.turntable, connected: !s.turntable.connected } }))
    toast(turntable.connected ? '转台控制器已断开' : '转台控制器已连接（COM3）')
  }

  const ttShoot = () => {
    patch((s) => ({
      ...s,
      turntable: {
        ...s.turntable,
        frames: s.turntable.frames + 1,
        angle: Math.min(360, (s.turntable.frames + 1) * s.turntable.step),
      },
    }))
    addLog(`转台拍帧：第 ${turntable.frames + 1} 帧`)
    toast(`已拍第 ${turntable.frames + 1} 帧（${turntable.frames * turntable.step}°）`)
  }

  const ttAuto = () => {
    if (!turntable.connected) { toast('先连接转台控制器'); return }
    patch((s) => ({ ...s, turntable: { ...s.turntable, auto: !s.turntable.auto, frames: s.turntable.auto ? s.turntable.frames : 0, angle: s.turntable.auto ? s.turntable.angle : 0 } }))
    toast(turntable.auto ? '自动扫描已暂停' : '自动扫描开始：转满一圈自动停止')
  }

  const ttFinish = () => {
    if (turntable.frames < 2) { toast('至少拍 2 帧才能完成采集'); return }
    const id = `tt-${Date.now()}`
    patch((s) => ({
      ...s,
      turntable: { ...s.turntable, auto: false },
      sessions: [{
        id, name: `turntable_${new Date().toTimeString().slice(0, 5).replace(':', '')}`,
        type: '转台', frames: s.turntable.frames, coverage: s.turntable.angle,
        date: '刚刚', thumb: depthUrl, artifacts: [],
      }, ...s.sessions],
      fusion: { ...s.fusion, selected: id },
    }))
    addLog(`转台采集完成：${turntable.frames} 帧 / ${turntable.angle}°`)
    toast(`采集完成，共 ${turntable.frames} 帧。去融合页生成模型`)
  }

  return (
    <div className="af-page af-scan">
      <header className="af-page-head">
        <div>
          <h1>三维扫描</h1>
          <p>设备连接 → 实时采集 / 手持 / 转台，一个工作区完成</p>
        </div>
        <ModeTabs mode={mode} setMode={setMode} />
      </header>

      {device === 'connected' ? (
        <>
          <DeviceBar state={state} onDisconnect={disconnect} onDiagnose={() => toast('诊断信息已复制到剪贴板（复刻台）')} />
          <div className="af-scan-grid">
            <section className="af-preview-panel">
              <div className="af-view-toolbar">
                <div className="af-view-title"><Layers size={14} /><b>预览</b><span>RGB + 深度</span></div>
                <div className="af-view-actions">
                  <button className={view.gray ? 'on' : ''} title="只切换深度画面为灰度；彩色画面保持彩色" onClick={() => setView({ ...view, gray: !view.gray })}>深度灰度</button>
                  <button className={view.mirror ? 'on' : ''} onClick={() => setView({ ...view, mirror: !view.mirror })}>镜像</button>
                  <button className={view.paused ? 'on' : ''} onClick={() => setView({ ...view, paused: !view.paused })}>{view.paused ? '继续' : '暂停'}</button>
                  <span className="af-tool-divider" />
                  <button onClick={() => setModal('measure')}><Crosshair size={13} /> 测距</button>
                  <button onClick={() => setModal('calib')}><Ruler size={13} /> 标定</button>
                  <button onClick={() => setModal('view')}><SlidersHorizontal size={13} /> 视图</button>
                </div>
              </div>
              <PreviewPair state={state} setView={setView} />
              <div className="af-preview-foot">
                <span><Activity size={13} /> {state.streams.fps.toFixed(1)} fps</span>
                <span><Gauge size={13} /> {quality.distance} mm</span>
                <span className="af-foot-spacer" />
                <span>{view.paused ? '画面已暂停，仍在收流' : '鼠标移到深度画面可查像素'}</span>
              </div>
            </section>

            <aside className="af-control-panel">
              {mode === 'live' ? (
                <Section title="实时采集" aside={<span className="af-pill">LIVE</span>}>
                  <div className="af-kv"><span>导出目录</span><b className="af-mono ellipsis" title={state.settings.exportDir}>{state.settings.exportDir}</b></div>
                  <div className="af-kv"><span>最近保存</span><b>{live.lastSaved}</b></div>
                  <div className="af-kv"><span>连续采集</span><b className={live.continuous ? 'ok' : ''}>{live.continuous ? `录制中 ${fmt(live.recSec)}` : '关闭'}</b></div>
                  <div className="af-hint">全部导出写入设置里的导出目录；快照为 PNG，点云为 PLY。</div>
                </Section>
              ) : null}

              {mode === 'handheld' ? (
                <Section title="手持扫描" aside={<span className={`af-pill ${handheld.recording ? 'rec' : ''}`}>{handheld.recording ? 'REC' : '待机'}</span>}>
                  <div className="af-stat-grid">
                    <Stat k="已记帧数" v={handheld.frames} />
                    <Stat k="记录时长" v={fmt(handheld.sec)} />
                  </div>
                  <button className="af-hint-toggle" onClick={() => setHintOpen(!hintOpen)}>
                    {hintOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />} 操作要领
                  </button>
                  {hintOpen ? (
                    <div className="af-hint-list">
                      <span>相机对准物体，距离 0.5–1.5 m</span>
                      <span>缓慢绕物体移动，一圈 20–40 秒</span>
                      <span>保持物体在画面中心，光照稳定</span>
                    </div>
                  ) : null}
                </Section>
              ) : null}

              {mode === 'turntable' ? (
                <Section title="转台扫描" aside={<span className={`af-pill ${turntable.connected ? 'ok' : ''}`}>{turntable.connected ? '已连接' : '未连接'}</span>}>
                  <Field label="串口">
                    <div className="af-inline">
                      <select value={turntable.port} onChange={(e) => patch((s) => ({ ...s, turntable: { ...s.turntable, port: e.target.value } }))}>
                        <option>COM3</option><option>COM4</option><option>COM7</option>
                      </select>
                      <Btn small icon={Usb} onClick={ttToggleConnect}>{turntable.connected ? '断开' : '连接'}</Btn>
                    </div>
                  </Field>
                  <div className="af-inline-2">
                    <Field label="步进 (°)"><input value={turntable.step} onChange={(e) => patch((s) => ({ ...s, turntable: { ...s.turntable, step: Number(e.target.value) || 15 } }))} /></Field>
                    <Field label="等待 (s)"><input value={turntable.wait} onChange={(e) => patch((s) => ({ ...s, turntable: { ...s.turntable, wait: Number(e.target.value) || 0.8 } }))} /></Field>
                  </div>
                  <div className="af-angle">
                    <div className="af-angle-head"><span>已覆盖角度</span><b>{turntable.angle}°</b></div>
                    <div className="af-bar"><span style={{ width: `${Math.min(100, turntable.angle / 360 * 100)}%` }} /></div>
                    <div className="af-angle-sub">{turntable.frames} 帧 · 每 {turntable.step}°</div>
                  </div>
                </Section>
              ) : null}

              <QualityPanel quality={quality} view={view} setView={setView} compact />
            </aside>
          </div>

          <footer className="af-actionbar">
            <div className="af-action-info">
              {mode === 'live' ? <><span className="af-dot ok" /> 设备就绪，可直接采集</> : null}
              {mode === 'handheld' ? <><span className={`af-dot ${handheld.recording ? 'err' : 'ok'}`} /> {handheld.recording ? `正在记录 ${fmt(handheld.sec)} · ${handheld.frames} 帧` : '等待开始'}</> : null}
              {mode === 'turntable' ? <><span className={`af-dot ${turntable.connected ? 'ok' : 'idle'}`} /> {turntable.connected ? `控制器已连接 · ${turntable.port}` : '控制器未连接'}</> : null}
            </div>
            <div className="af-actions">
              {mode === 'live' ? (
                <>
                  <Btn icon={FolderOpen} onClick={() => toast('打开导出目录（复刻台）')}>打开目录</Btn>
                  <Btn icon={Download} onClick={exportCloud}>导出点云</Btn>
                  <Btn className={live.continuous ? 'rec' : ''} icon={live.continuous ? Square : Play} onClick={toggleContinuous}>{live.continuous ? `停止连续采集 ${fmt(live.recSec)}` : '连续采集'}</Btn>
                  <Btn primary icon={Camera} onClick={snapshot}>保存快照</Btn>
                </>
              ) : null}
              {mode === 'handheld' ? (
                <>
                  {handheld.frames > 0 ? <Btn icon={Boxes} onClick={() => setPage('fusion')}>去融合</Btn> : null}
                  <Btn primary={!handheld.recording} danger={handheld.recording} icon={handheld.recording ? Square : Play} onClick={handheld.recording ? stopHandheld : startHandheld}>
                    {handheld.recording ? '停止记录' : '开始记录'}
                  </Btn>
                </>
              ) : null}
              {mode === 'turntable' ? (
                <>
                  <Btn icon={RotateCw} onClick={ttAuto}>{turntable.auto ? '暂停自动扫描' : '自动扫描'}</Btn>
                  <Btn icon={Camera} onClick={ttShoot}>拍这一帧</Btn>
                  <Btn primary icon={Check} onClick={ttFinish}>完成采集</Btn>
                </>
              ) : null}
            </div>
          </footer>
        </>
      ) : (
        <ConnectionView
          state={state}
          onConnect={connectDevice}
          onDetect={detect}
          onDriverHelp={() => setPage('about')}
          onRetry={connectDevice}
          onDiagnose={() => toast('诊断信息已复制（复刻台）')}
        />
      )}

      {modal === 'calib' ? (
        <Modal title="深度标定（shift → mm）" onClose={() => setModal(null)}>
          <p className="af-modal-hint">把已知距离的平面正对镜头，填入真实距离后采样。保存后长期生效。</p>
          <Field label="已知距离 (mm)"><input value={calib.known} onChange={(e) => setCalib({ ...calib, known: e.target.value })} /></Field>
          <Field label="采样区边长 (px)"><input value={calib.roi} onChange={(e) => setCalib({ ...calib, roi: e.target.value })} /></Field>
          {calib.sampled ? <div className="af-callout ok">采样：中位 shift 646 → k = 0.7740 mm/shift</div> : null}
          <div className="af-modal-actions">
            <Btn onClick={() => setCalib({ ...calib, sampled: true })}>采样</Btn>
            <Btn primary disabled={!calib.sampled} onClick={() => { setModal(null); toast('标定已保存（复刻台）') }}>保存标定</Btn>
          </div>
        </Modal>
      ) : null}

      {modal === 'view' ? (
        <Modal title="视图设置" onClose={() => setModal(null)}>
          <p className="af-modal-hint">深度色带范围只影响预览，不改变采集数据。</p>
          <div className="af-inline-2">
            <Field label="最小 (shift)"><input value={range.lo} onChange={(e) => setRange({ ...range, lo: e.target.value })} /></Field>
            <Field label="最大 (shift)"><input value={range.hi} onChange={(e) => setRange({ ...range, hi: e.target.value })} /></Field>
          </div>
          <div className="af-modal-actions">
            <Btn onClick={() => setRange({ lo: '0', hi: '2500' })}>重置 0–2500</Btn>
            <Btn primary onClick={() => { setModal(null); toast(`显示范围已应用：${range.lo}–${range.hi} shift`) }}>应用</Btn>
          </div>
        </Modal>
      ) : null}

      {modal === 'measure' ? (
        <Modal title="测距" onClose={() => setModal(null)}>
          <p className="af-modal-hint">在深度画面上点两个点，量 3D 直线距离。复刻台会用假数据返回结果。</p>
          <div className="af-measure-box">
            <span>点 1</span><b>—</b><span>点 2</span><b>—</b>
          </div>
          <div className="af-callout">结果：<b>184.6 mm</b></div>
          <div className="af-modal-actions"><Btn primary onClick={() => setModal(null)}>完成</Btn></div>
        </Modal>
      ) : null}
    </div>
  )
}
