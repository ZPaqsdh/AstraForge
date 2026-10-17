import { useEffect, useRef, useState } from 'react'
import { FolderOpen, Download } from 'lucide-react'
import { api } from '../api.js'
import PageIntro from '../components/PageIntro.jsx'
import QualityPanel, { QualityOverlay } from '../components/QualityPanel.jsx'
import { FrameImg, usePoll } from '../hooks.jsx'

// 预览深度画幅：640 宽裁掉右缘 21 列固定垃圾带（BUG-009 显示层裁剪）→ 619×480
const DW = 619, DH = 480

function lutColor(t) {
  t = Math.max(0, Math.min(1, t))
  const stops = [[0, 0, 51], [0, 102, 255], [0, 229, 204], [127, 255, 76], [255, 229, 0], [255, 102, 0], [255, 0, 0]]
  const x = t * (stops.length - 1), i = Math.floor(x), f = x - i
  const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
}

// 色标尺（悬浮于深度画面上：不占列宽 → 深度图与 RGB 图同宽等高，卡片不留白）
function ScaleBar() {
  const ref = useRef(null)
  useEffect(() => {
    const c = ref.current
    if (!c) return
    let raf = 0
    const draw = () => {
      const H = Math.max(100, c.clientHeight || 360)
      if (c.width !== 56 || c.height !== H) { c.width = 56; c.height = H }
      const ctx = c.getContext('2d')
      ctx.clearRect(0, 0, 56, H)
      for (let y = 0; y < H; y++) {
        const [c0, c1, c2] = lutColor(1 - y / (H - 1))
        ctx.fillStyle = `rgb(${c0},${c1},${c2})`
        ctx.fillRect(0, y, 22, 1)
      }
      const fg = getComputedStyle(document.documentElement).getPropertyValue('--fg').trim() || '#cccccc'
      ctx.fillStyle = fg
      ctx.font = '10px Consolas'
      ;[['2.5m', 0], ['2.0m', 0.21], ['1.5m', 0.415], ['1.0m', 0.62], ['0.5m', 0.825], ['0mm', 0.99]]
        .forEach(([s, fr]) => {
          const y = Math.round(fr * (H - 1))
          ctx.fillText(s, 25, Math.min(H - 6, y + 10))
        })
    }
    const schedule = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(draw) }
    draw()
    const t = setTimeout(draw, 60)            // 布局稳定后按实际高度重绘
    window.addEventListener('resize', schedule)
    let ro = null
    try { ro = new ResizeObserver(schedule); ro.observe(c) } catch (e) {}
    const mo = new MutationObserver(schedule)   // 主题切换重绘（文字颜色跟随主题）
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => {
      clearTimeout(t)
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', schedule)
      if (ro) ro.disconnect()
      mo.disconnect()
    }
  }, [])
  return <canvas ref={ref} style={{ width: '100%' }} />
}

export default function CapturePage({ app }) {
  const { showToast, state, rec, recSec } = app
  const [stats] = usePoll(api.stats, 1000)
  const [qual] = usePoll(api.quality, 1200)      // 采集质量（TODO-016）
  const [overlay, setOverlay] = useState(false)  // 质量色谱叠加
  const [hover, setHover] = useState('')
  const [gray, setGray] = useState(() => { try { return localStorage.getItem('af-gray') === '1' } catch { return false } })
  const [flip, setFlip] = useState(true)   // 预览镜像（显示层）：默认开（首轮 state 到达后跟随后端持久化值）
  const [paused, setPaused] = useState(false)
  const [log, setLog] = useState([])
  const [busy, setBusy] = useState(false)
  // 镜像开关一次性对齐：后端可能已从"设置.json"还原（比如上次关掉了）→ 首次拿到 state 时同步
  const flipSynced = useRef(false)
  useEffect(() => {
    if (!flipSynced.current && state && typeof state.preview_mirror === 'boolean') {
      flipSynced.current = true
      setFlip(state.preview_mirror)
    }
  }, [state])
  // 预览帧率统计：3 秒滚动窗口速率（每帧记时间戳）
  // 2026-10-15 修复：原"每秒计数"实现下，单秒抖动（跨秒边界/页面切换）会造成读数
  // 0↔30 闪跳；滚动窗口反映真实"跟手"程度且平滑（真卡顿会随窗口自然衰减而非闪跳）。
  const rgbTs = useRef([])
  const depTs = useRef([])
  const [dispFps, setDispFps] = useState({ rgb: 0, depth: 0 })
  useEffect(() => {
    const rate = (arr) => {
      const now = Date.now()
      while (arr.length && now - arr[0] > 3000) arr.shift()
      if (arr.length < 2) return arr.length
      const dt = (arr[arr.length - 1] - arr[0]) / 1000
      return dt > 0 ? Math.round((arr.length - 1) / dt) : 0
    }
    const id = setInterval(() => {
      setDispFps({ rgb: rate(rgbTs.current), depth: rate(depTs.current) })
    }, 1000)
    return () => clearInterval(id)
  }, [])

  const exportDir = (state && state.export_dir) || ''

  const addLog = (m) => setLog(l => [`[${new Date().toTimeString().slice(0, 8)}] ${m}`, ...l].slice(0, 20))

  const act = async (fn, okMsg) => {
    setBusy(true)
    try {
      const r = await fn()
      if (r && r.path) showToast(`✓ ${okMsg} → ${r.path}`, 4200)
      else if (r && r.dir) showToast(`✓ ${okMsg} → ${r.dir}`, 4200)
      else if (okMsg) showToast(`✓ ${okMsg}`)
      if (r && r.path) addLog(`已导出 ${r.path}`)
      return r
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4000)
      addLog(`失败: ${e.message || e}`)
      return null
    } finally {
      setBusy(false)
    }
  }

  // 悬停查值（节流 120ms）
  const hoverT = useRef(0)
  const onHover = async (e) => {
    const now = Date.now()
    if (now - hoverT.current < 120) return
    hoverT.current = now
    const r = e.currentTarget.getBoundingClientRect()
    const x = Math.round((e.clientX - r.left) / r.width * DW)
    const y = Math.round((e.clientY - r.top) / r.height * DH)
    try {
      const d = await api.pixel(x, y)
      setHover(d.v > 0 ? `(${x}, ${y}) = ${d.v} ≈ ${d.mm} mm` : `(${x}, ${y}) = 无效`)
    } catch { /* 后端未就绪 */ }
  }

  const fs = String(Math.floor(recSec / 3600)).padStart(2, '0')
  const fm = String(Math.floor(recSec % 3600 / 60)).padStart(2, '0')
  const fsec = String(recSec % 60).padStart(2, '0')

  return (
    <div className="fade-in page-grid">
      <PageIntro id="capture">
        <b>采集</b>：实时看画面、存快照。左边彩色画面，右边深度画面（颜色代表远近，蓝近红远）；
        鼠标悬停深度画面可查任意一点的距离。右侧「采集质量」给出距离条与覆盖质量（绿=合格），
        可开「质量色谱叠加」看哪块没扫到。下方按钮：保存帧、导出点云、连续采集。
      </PageIntro>
      <div className="layout-capture">
        <div className="card" style={{ padding: 9 }}>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>RGB 画面</div>
          <FrameImg kind="rgb" paused={paused} onFrame={() => { rgbTs.current.push(Date.now()) }}
            style={{ width: '100%', aspectRatio: '4 / 3', objectFit: 'contain', background: 'var(--bg)' }} />
        </div>
        <div className="card" style={{ padding: 9 }}>
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
            深度画面（伪彩）<span style={{ color: 'var(--accent)', fontFamily: 'Consolas', marginLeft: 14 }}>{hover}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) 56px', gap: 8, alignItems: 'stretch' }}>
            <div style={{ position: 'relative', aspectRatio: '619 / 480' }}>
              <FrameImg kind="depth" gray={gray} paused={paused}
                onFrame={() => { depTs.current.push(Date.now()) }}
                style={{ width: '100%', height: '100%', aspectRatio: '619 / 480', objectFit: 'contain', background: 'var(--bg)', cursor: 'crosshair', opacity: paused ? 0.55 : 1 }}
                onMouseMove={onHover}
                onMouseLeave={() => setHover('')} />
              <QualityOverlay grid={qual && qual.ok ? qual.grid : null} on={overlay} />
            </div>
            <ScaleBar />
          </div>
        </div>
        <div className="side-col">
          <QualityPanel q={qual} overlay={overlay} setOverlay={setOverlay} />
          <div className="card">
            <div style={{ fontSize: 13, marginBottom: 8, fontWeight: 600 }}>实时状态</div>
            <div className="stat"><span className="k">帧数</span><span className="v">{(stats?.frames || 0).toLocaleString()}</span></div>
            <div className="stat"><span className="k">数据帧率</span><span className="v">{stats?.fps?.toFixed ? stats.fps.toFixed(1) : '--'} fps</span></div>
            <div className="stat"><span className="k">预览帧率 (RGB/深度)</span><span className="v">{dispFps.rgb} / {dispFps.depth} fps</span></div>
            <div className="stat"><span className="k">丢包补偿</span><span className="v">{stats?.padded ?? 0} 帧 / {stats?.gap ?? 0} 槽</span></div>
            <div className="stat"><span className="k">拒帧</span><span className="v">{stats?.rejected ?? 0}</span></div>
            <div className="stat"><span className="k">标定值</span><span className="v">{state?.calib?.toFixed ? state.calib.toFixed(4) : '1.0000'} mm/shift</span></div>
          </div>
          <div className="card">
            <div style={{ fontSize: 13, marginBottom: 8, fontWeight: 600 }}>采集</div>
            <div className="flex gap-2" style={{ marginBottom: 8, flexWrap: 'wrap' }}>
              <button className="btn" disabled={busy}
                onClick={() => act(api.saveSnapshot, '已保存快照')}>
                <FolderOpen size={14} /> 保存帧 (S)
              </button>
              <button className="btn" disabled={busy}
                onClick={() => act(api.exportCloud, '点云已导出')}>
                <Download size={14} /> 导出点云 (P)
              </button>
            </div>
            <button
              className={`btn${rec.on ? ' rec-on' : ''}`}
              style={{ width: '100%', justifyContent: 'center' }}
              onClick={async () => {
                setBusy(true)
                try {
                  const r = await api.toggleContinuous()
                  const msg = r.on ? '连续采集开始（每 2 秒自动保存）' : '连续采集停止'
                  addLog(msg); showToast(`✓ ${msg}`)
                } catch (e) { showToast(`✗ ${e.message || e}`) }
                finally { setBusy(false) }
              }}
            >
              {rec.on ? `■ REC ${fs}:${fm}:${fsec}` : '● 连续采集 (C)'}
            </button>
          </div>
          <div className="card">
            <div style={{ fontSize: 13, marginBottom: 8, fontWeight: 600 }}>画面</div>
            <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
              <button className="btn" onClick={async () => { const v = !gray; setGray(v); try { localStorage.setItem('af-gray', v ? '1' : '0') } catch {} await api.setGray(v).catch(() => {}); addLog(`深度显示: ${v ? '灰度' : '伪彩'}`) }}>灰度 (G)</button>
              <button className="btn" onClick={async () => { const v = !flip; setFlip(v); await api.setFlip(v).catch(() => {}); addLog(`预览镜像: ${v ? '开' : '关'}`) }}>镜像 (M)</button>
              <button className="btn" onClick={async () => { const v = !paused; setPaused(v); await api.setPaused(v).catch(() => {}); addLog(v ? '已暂停预览' : '已恢复预览') }}>暂停</button>
            </div>
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,2fr) minmax(0,1fr)', gap: 12 }}>
        <div className="card">
          <div style={{ fontSize: 13, marginBottom: 8, fontWeight: 600 }}>操作日志</div>
          <div style={{ fontFamily: 'Consolas, monospace', fontSize: 11.5, lineHeight: 2, color: 'var(--muted)', maxHeight: 130, overflowY: 'auto' }}>
            {log.length === 0 && <div style={{ color: 'var(--dim)' }}>（操作记录会显示在这里）</div>}
            {log.map((l, i) => <div key={i}>{l}</div>)}
          </div>
        </div>
        <div className="card">
          <div style={{ fontSize: 13, marginBottom: 8, fontWeight: 600 }}>导出目录</div>
          <div style={{
            fontFamily: 'Consolas, monospace', fontSize: 11.5, wordBreak: 'break-all',
            background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 9, padding: '8px 10px',
          }}>{exportDir || '（读取中…）'}</div>
          <div className="flex gap-2" style={{ marginTop: 8 }}>
            <button className="btn" onClick={() => api.openDir(exportDir).catch(e => showToast(e.message))}>
              <FolderOpen size={14} /> 打开目录
            </button>
            <button className="btn" onClick={() => app.setPage('settings')}>更改…</button>
          </div>
        </div>
      </div>
    </div>
  )
}
