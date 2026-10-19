// Preview.jsx — 真实帧流预览（RGB + 深度）、质量叠加、悬停查值、点击取点
import { useRef, useState } from 'react'
import { Activity, Crosshair, Gauge } from 'lucide-react'
import { FrameImg } from '../hooks.jsx'
import { api } from '../api.js'

export const DW = 619
export const DH = 480

function covColor(c) {
  const t = Math.max(0, Math.min(1, c / 100))
  const stops = [[255, 80, 80], [255, 200, 80], [60, 214, 140]]
  const x = t * (stops.length - 1), i = Math.floor(x), f = x - i
  const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
    .map((v) => Math.round(v)).join(',')
}

export function QualityOverlay({ grid, visible, gray }) {
  if (!visible || !grid || !grid.length) return null
  const rows = grid.length, cols = grid[0].length
  return (
    <div className={`af-quality-overlay ${gray ? 'gray' : ''}`} aria-hidden="true"
      style={{ gridTemplateRows: `repeat(${rows}, 1fr)`, gridTemplateColumns: `repeat(${cols}, 1fr)` }}>
      {grid.flatMap((row, i) => row.map((c, j) => (
        <span key={`${i}-${j}`} style={{
          background: gray
            ? `rgba(255,255,255,${0.04 + Math.max(0, Math.min(1, c / 100)) * 0.18})`
            : `rgba(${covColor(c)},${0.18 + Math.max(0, Math.min(1, c / 100)) * 0.34})`,
        }} />
      )))}
    </div>
  )
}

export function PreviewPair({
  gray, paused, quality, showQuality, onHoverChange, onDepthClick,
  measureActive, points = [],
}) {
  const [hover, setHover] = useState('')
  const hoverT = useRef(0)
  const rgbTs = useRef([])
  const depTs = useRef([])
  const [fps, setFps] = useState({ rgb: 0, depth: 0 })
  const fpsTimer = useRef(null)

  const mark = (arr) => {
    arr.current.push(Date.now())
    if (!fpsTimer.current) {
      fpsTimer.current = setInterval(() => {
        const rate = (a) => {
          const now = Date.now()
          while (a.length && now - a[0] > 3000) a.shift()
          if (a.length < 2) return a.length
          const dt = (a[a.length - 1] - a[0]) / 1000
          return dt > 0 ? Math.round((a.length - 1) / dt) : 0
        }
        setFps({ rgb: rate(rgbTs.current), depth: rate(depTs.current) })
      }, 1000)
    }
  }

  const onMove = async (e) => {
    const now = Date.now()
    if (now - hoverT.current < 120) return
    hoverT.current = now
    const r = e.currentTarget.getBoundingClientRect()
    const x = Math.round(((e.clientX - r.left) / r.width) * DW)
    const y = Math.round(((e.clientY - r.top) / r.height) * DH)
    try {
      const d = await api.pixel(x, y)
      const text = d.v > 0 ? `(${x}, ${y}) = ${d.v} ≈ ${d.mm} mm` : `(${x}, ${y}) 无效`
      setHover(text)
      if (onHoverChange) onHoverChange(text)
    } catch (err) {
      setHover('')
    }
  }

  const onClick = (e) => {
    if (!onDepthClick) return
    const r = e.currentTarget.getBoundingClientRect()
    const x = Math.round(((e.clientX - r.left) / r.width) * DW)
    const y = Math.round(((e.clientY - r.top) / r.height) * DH)
    onDepthClick(x, y)
  }

  return (
    <div className="af-preview-pair">
      <figure className="af-frame">
        <figcaption>
          <span className="af-frame-title">彩色 RGB</span>
          <span className="af-frame-meta">640 × 480</span>
        </figcaption>
        <div className="af-frame-body">
          <FrameImg kind="rgb" paused={paused} onFrame={() => mark(rgbTs)}
            alt="RGB 预览" />
          {paused ? <span className="af-paused">已暂停</span> : null}
          <span className="af-live"><i />LIVE</span>
        </div>
      </figure>

      <figure className="af-frame">
        <figcaption>
          <span className="af-frame-title">深度 DEPTH</span>
          <span className="af-frame-meta">619 × 480 · {gray ? '灰度' : '伪彩'}</span>
        </figcaption>
        <div className={`af-frame-body ${measureActive ? 'measuring' : ''}`}
          onMouseMove={onMove} onMouseLeave={() => { setHover(''); onHoverChange && onHoverChange('') }}
          onClick={onClick}>
          <FrameImg kind="depth" gray={gray} paused={paused} onFrame={() => mark(depTs)}
            alt="深度预览" style={{ cursor: onDepthClick ? 'crosshair' : 'default' }} />
          <QualityOverlay grid={quality && quality.ok ? quality.grid : null}
            visible={showQuality} gray={gray} />
          {points.map((p, i) => (
            <span key={i} className="af-measure-point" style={{
              left: `${(p.x / DW) * 100}%`, top: `${(p.y / DH) * 100}%`,
            }}>{i + 1}</span>
          ))}
          {paused ? <span className="af-paused">已暂停</span> : null}
          {hover ? <span className="af-hover">{hover}</span> : null}
        </div>
      </figure>

      <div className="af-preview-foot af-span-2">
        <span><Activity size={13} /> 预览 {fps.rgb}/{fps.depth} fps</span>
        <span><Gauge size={13} /> {quality && quality.ok ? `${quality.d_med} mm` : '— mm'}</span>
        <span className="af-foot-spacer" />
        <span>{measureActive ? <><Crosshair size={12} /> 点深度画面取两点</> : '鼠标移到深度画面可查像素'}</span>
      </div>
    </div>
  )
}

export function QualityPanel({ q, showQuality, setShowQuality, compact = false }) {
  const ok = !!(q && q.ok)
  const tone = !ok ? 'err' : q.light === 'green' ? 'ok' : q.light === 'yellow' ? 'warn' : 'err'
  const stateText = !ok ? '待画面' : q.light === 'green' ? '合格' : q.light === 'yellow' ? '偏弱' : '不合格'
  const pct = ok ? Math.max(0, Math.min(100, (q.d_med / 2500) * 100)) : 0
  return (
    <div className={`af-quality ${compact ? 'compact' : ''}`}>
      <div className="af-quality-head">
        <h4>采集质量</h4>
        <span className={`af-quality-light ${tone === 'ok' ? '' : tone}`} />
        <span className="af-quality-state">{stateText}</span>
      </div>
      <div className="af-distance">
        <div className="af-distance-track">
          <span className="seg near" />
          <span className="seg best" />
          <span className="seg far" />
          {ok ? <span className="af-distance-marker" style={{ left: `${pct}%` }} /> : null}
        </div>
        <div className="af-distance-labels"><span>近</span><span>最佳 0.5–1.5 m</span><span>远</span></div>
        <div className="af-distance-value">{ok ? `${q.d_med} mm` : '-- mm'}</div>
      </div>
      <div className="af-quality-row">
        <span>有效覆盖</span>
        <div className="af-bar"><span style={{ width: `${ok ? q.valid_pct : 0}%` }} /></div>
        <b>{ok ? `${q.valid_pct}%` : '--'}</b>
      </div>
      <div className="af-quality-row" style={{ marginTop: 4 }}>
        <span style={{ color: 'var(--dim)', fontSize: 10.5 }}>{ok ? q.hint : '等待深度画面…'}</span>
      </div>
      <label className="af-check">
        <input type="checkbox" checked={!!showQuality} onChange={(e) => setShowQuality(e.target.checked)} />
        <span>显示 6×8 覆盖色谱（红=差 / 绿=好）</span>
      </label>
    </div>
  )
}
