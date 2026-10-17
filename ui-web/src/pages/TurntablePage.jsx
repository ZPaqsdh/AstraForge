import { useEffect, useRef, useState } from 'react'
import PageIntro from '../components/PageIntro.jsx'
import QualityPanel from '../components/QualityPanel.jsx'
import { api } from '../api.js'
import { FrameImg, usePoll } from '../hooks.jsx'

// 角度环（已覆盖角度可视化）
function AngleRing({ deg }) {
  const ref = useRef(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    const ctx = c.getContext('2d')
    const W = c.width = 220, H = c.height = 104
    ctx.clearRect(0, 0, W, H)
    const fg = getComputedStyle(document.documentElement).getPropertyValue('--fg').trim()
    const dim = getComputedStyle(document.documentElement).getPropertyValue('--dim').trim()
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()
    // 半圆轨道
    ctx.strokeStyle = dim
    ctx.lineWidth = 8
    ctx.beginPath()
    ctx.arc(W / 2, H - 8, 78, Math.PI, 0)
    ctx.stroke()
    // 已覆盖弧
    ctx.strokeStyle = accent
    ctx.beginPath()
    ctx.arc(W / 2, H - 8, 78, Math.PI, Math.PI + Math.PI * Math.min(deg, 360) / 360)
    ctx.stroke()
    ctx.fillStyle = fg
    ctx.font = 'bold 15px Consolas'
    ctx.textAlign = 'center'
    ctx.fillText(`${Math.round(deg)}°`, W / 2, H - 22)
    ctx.font = '10px sans-serif'
    ctx.fillStyle = dim
    ctx.fillText('0°', 30, H - 6)
    ctx.fillText('360°', W - 30, H - 6)
  }, [deg])
  return <canvas ref={ref} style={{ width: '100%', maxWidth: 240, margin: '0 auto', display: 'block', height: 'auto' }} />
}

export default function TurntablePage({ app }) {
  const { showToast, setPage } = app
  // 本地记忆（自动保存：下次启动还原）——端口/步进/等待/相机距离
  const lsGet = (k, d) => { try { return localStorage.getItem('af-tt-' + k) ?? d } catch { return d } }
  const [mode, setMode] = useState('auto')           // auto | manual
  const [ports, setPorts] = useState([])
  const [port, setPort] = useState(() => lsGet('port', ''))
  const [connected, setConnected] = useState(false)
  const [deviceInfo, setDeviceInfo] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [autoOn, setAutoOn] = useState(false)
  const [step, setStep] = useState(() => lsGet('step', '15'))
  const [wait, setWait] = useState(() => lsGet('wait', '0.8'))
  const [dist, setDist] = useState(() => lsGet('dist', '0'))
  const [frames, setFrames] = useState([])
  const [tt] = usePoll(api.ttStatus, 1000)
  const [qual] = usePoll(api.quality, 1200)   // 采集质量（TODO-016）：开扫前先对距离
  // 预览镜像（显示层）：与采集页共用同一全局值（设置页/采集页改也会跟到这里）
  const [flip, setFlip] = useState(true)
  const flipSynced = useRef(false)
  const st = usePoll(api.state, 1500)[0]
  useEffect(() => {
    if (!flipSynced.current && st && typeof st.preview_mirror === 'boolean') {
      flipSynced.current = true
      setFlip(st.preview_mirror)
    }
  }, [st])
  const toggleMirror = async () => {
    const v = !flip; setFlip(v)
    await api.setFlip(v).catch(() => {})
    showToast(`预览镜像: ${v ? '开' : '关'}`)
  }

  // 连接状态跟随后端（页面重开时恢复真实状态；后端只认握过手的连接）
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const r = await api.ttConnectStatus()
        if (alive) { setConnected(!!r.connected); setDeviceInfo(r.device || '') }
      } catch {}
    }
    tick(); const id = setInterval(tick, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const doConnect = async () => {
    if (connecting) return
    if (connected) {
      try { await api.ttDisconnect() } catch {}
      setConnected(false); setDeviceInfo('')
      showToast('控制器已断开')
      return
    }
    if (!port) { showToast('✗ 未选择串口'); return }
    setConnecting(true)
    try {
      const r = await api.ttConnect(port)
      if (r.ok) {
        setConnected(true); setDeviceInfo(r.device || '')
        showToast(`✓ 控制器已连接：${r.device || port}`, 4200)
      } else {
        setConnected(false); setDeviceInfo('')
        showToast(`✗ 连接失败：${r.error || '未识别设备'}`, 5000)
      }
    } catch (e) {
      setConnected(false)
      showToast(`✗ 连接失败：${e.message || e}`, 5000)
    } finally { setConnecting(false) }
  }

  // 变化即存
  useEffect(() => {
    try {
      localStorage.setItem('af-tt-port', port)
      localStorage.setItem('af-tt-step', step)
      localStorage.setItem('af-tt-wait', wait)
      localStorage.setItem('af-tt-dist', dist)
    } catch {}
  }, [port, step, wait, dist])

  const count = frames.length
  const angle = count * parseFloat(step || '15')

  useEffect(() => {
    api.serialPorts().then(r => {
      setPorts(r.ports || [])
      if (r.ports && r.ports.length) {
        // 上次记住的端口仍在 → 沿用；否则默认第一个
        const has = r.ports.some(([p]) => p === port)
        setPort(has ? port : r.ports[0][0])
      }
      if (!r.ok) showToast(`转台控制器：${r.error || '未检测到'}`, 5000)
    }).catch(() => {})
  }, [])

  const shoot = async () => {
    try {
      const r = await api.ttShoot(parseFloat(step || '15'), parseFloat(dist || '0'))
      if (r.ok) {
        setFrames(f => [...f, { n: r.count, angle: f.length * parseFloat(step || '15') }])
        showToast(`✓ 已拍第 ${r.count} 帧（${(r.count - 1) * parseFloat(step || '15')}°）`)
      } else showToast('✗ 拍摄失败：还没有画面')
    } catch (e) { showToast(`✗ ${e.message}`) }
  }

  const finish = async () => {
    try {
      const r = await api.ttFinish()
      if (r.ok) {
        showToast(`✓ 采集完成 → ${r.dir}（去融合页生成模型）`, 5000)
        setFrames([])
      } else showToast('✗ 一帧都没采')
    } catch (e) { showToast(`✗ ${e.message}`) }
  }

  const toggleAuto = async () => {
    try {
      const r = await api.ttAuto(port, parseFloat(step || '15'), parseFloat(wait || '0.8'))
      if (r.ok) {
        setAutoOn(r.on)
        showToast(r.on ? '自动扫描开始 —— 转台与相机全自动配合' : '自动扫描已停止')
      } else showToast(`✗ ${r.error}`)
    } catch (e) { showToast(`✗ ${e.message}`) }
  }

  return (
    <div className="fade-in page-grid">
      <PageIntro id="turntable">
        <b>转台</b>：把小物件放转盘上拍一圈，然后去「融合」页生成完整模型。<b>自动模式</b>：接上转台控制器（开发板），软件自动完成“转→稳→拍”整圈；<b>手动模式</b>：人工转盘 + 逐张拍摄。
      </PageIntro>
      <div className="layout-side">
        <div className="side-col">
          <div className="card">
            <h3>拍摄模式</h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
              <button className={`btn${mode === 'auto' ? ' primary' : ''}`} onClick={() => setMode('auto')}
                style={{ justifyContent: 'center' }}>自动（接控制器）</button>
              <button className={`btn${mode === 'manual' ? ' primary' : ''}`} onClick={() => setMode('manual')}
                style={{ justifyContent: 'center' }}>手动（人工转盘）</button>
            </div>

            {mode === 'auto' ? (
              <div>
                <div className="field"><label>控制器</label>
                  <select value={port} onChange={e => setPort(e.target.value)} style={{ width: 150 }}>
                    {ports.length === 0 && <option>（未检测到设备）</option>}
                    {ports.map(([d, desc]) => <option key={d} value={d}>{d} · {desc}</option>)}
                  </select></div>
                <div className="row" style={{ marginBottom: 8 }}>
                  <button className="btn" disabled={connecting} onClick={doConnect}>
                    {connecting ? '握手中…' : (connected ? '断开' : '连接')}</button>
                  <span className="hint" style={{ color: connected ? 'var(--ok)' : 'var(--muted)' }}>
                    {connected ? `● 已连接${deviceInfo ? '：' + deviceInfo : ''}` : '未连接（需握手识别）'}</span>
                  <button className="btn" style={{ marginLeft: 'auto' }} onClick={toggleMirror}>镜像 (M)</button>
                </div>
                <div className="field"><label>步进角度 (°)</label><input type="text" value={step} onChange={e => setStep(e.target.value)} /></div>
                <div className="field"><label>每步稳定等待 (s)</label><input type="text" value={wait} onChange={e => setWait(e.target.value)} /></div>
                <button className="btn primary wide" onClick={toggleAuto} style={{ marginTop: 6 }}>
                  {autoOn ? '■ 停止扫描' : '▶ 开始自动扫描'}
                </button>
                <div className="progress" style={{ marginTop: 9 }}><div style={{ width: `${Math.min(100, count / (360 / parseFloat(step || '15')) * 100)}%` }} /></div>
                <div className="hint">
                  {autoOn ? `自动扫描中：已拍 ${count} 帧（转动 → 稳定 → 拍摄 全自动）` : '待开始 —— 连接控制器后开始，整圈无需人工。'}
                </div>
                <div className="hint" style={{ marginTop: 8, color: 'var(--dim)' }}>
                  控制器接口：串口 115200；连接时发 <span className="mono">WHO</span> → 控制器回
                  <span className="mono"> ASTRATT:&lt;ID&gt;:&lt;版本&gt;</span>（前缀不符拒绝连接）；
                  自动扫描指令 <span className="mono">ROT &lt;角度&gt;</span> → 回 <span className="mono">READY</span>。
                </div>
              </div>
            ) : (
              <div>
                <div className="field"><label>步进角度 (°)</label><input type="text" value={step} onChange={e => setStep(e.target.value)} /></div>
                <div className="field"><label>转台距离 (mm)</label><input type="text" value={dist} onChange={e => setDist(e.target.value)} /></div>
                <div className="hint" style={{ marginBottom: 9 }}>距离 0 = 用画面中心深度自动估计</div>
                <button className="btn primary wide" onClick={shoot}>拍这一帧（Enter）</button>
                <div className="hint" style={{ marginTop: 8 }}>拍完把转盘转过一个步进角，再点下一张。转满一圈后点「完成采集」。</div>
                <div className="row" style={{ marginTop: 8, marginBottom: 0 }}>
                  <button className="btn" style={{ marginLeft: 'auto' }} onClick={toggleMirror}>镜像 (M)</button>
                </div>
                <button className="btn wide" style={{ marginTop: 8 }} onClick={finish}>✓ 完成采集</button>
              </div>
            )}
          </div>

          <div className="card">
            <h3>进度</h3>
            <div className="stat"><span className="k">已采帧数</span><span className="v">{count}</span></div>
            <div className="stat"><span className="k">已覆盖角度</span><span className="v">{Math.round(angle)}°</span></div>
            <AngleRing deg={angle} />
            <button className="btn wide" style={{ marginTop: 4 }} onClick={finish}>✓ 完成去融合</button>
          </div>
        </div>
        <div style={{ display: 'grid', gap: 12 }}>
          <QualityPanel q={qual} />
          <div className="card" style={{ padding: 9 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 10, alignItems: 'stretch' }}>
              <div>
                <div className="hint" style={{ marginBottom: 6 }}>彩色画面（转台上的物体）</div>
                <FrameImg kind="rgb" style={{ width: '100%', height: 'auto' }} />
              </div>
              <div>
                <div className="hint" style={{ marginBottom: 6 }}>深度画面（页内实时预览）</div>
                <FrameImg kind="depth" style={{ width: '100%', height: 'auto' }} />
              </div>
            </div>
          </div>
          <div className="card">
            <div className="hint" style={{ marginBottom: 6 }}>已拍帧</div>
            <div className="framelist" style={{ display: 'flex', flexWrap: 'wrap', gap: 6, minHeight: 34 }}>
              {frames.length === 0 && <span className="hint" id="tt-empty">还没有拍帧 —— 选择上方模式开始采集（自动模式需先连接控制器）。</span>}
              {frames.map(f => (
                <span key={f.n} style={{
                  background: 'var(--accent-dim)', border: '1px solid var(--border)',
                  borderRadius: 9, padding: '4px 10px', fontSize: 12, fontFamily: 'Consolas',
                }}>#{String(f.n).padStart(3, '0')} · {Math.round(f.angle)}°</span>
              ))}
            </div>
            {count > 0 && (
              <button className="btn" style={{ marginTop: 8 }} onClick={() => setPage('fusion')}>前往融合 →</button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
