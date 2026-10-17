// QualityPanel.jsx — 采集质量可视化（TODO-016）
//   ① 距离条三段色（太近 / 最佳 / 太远 + 当前中位距离指针）
//   ② 状态灯（绿=合格 / 黄=偏弱 / 红=不合格）
//   ③ 质量色谱叠加（6×8 覆盖网格：红=差 → 绿=好）
import { useState } from 'react'

const NEAR = 500, FAR = 1500, MAXV = 2500   // 距离条量程（mm），与后端最佳区一致
const LIGHT_CSS = {
  green: 'var(--ok, #3fd68c)',
  yellow: 'var(--warn, #ffb454)',
  red: 'var(--err, #ff6b6b)',
}

function covColor(c) {
  // 覆盖率 0-100 → 红(255,80,80) → 橙黄(255,200,80) → 绿(60,214,140)
  const t = Math.max(0, Math.min(1, c / 100))
  const stops = [[255, 80, 80], [255, 200, 80], [60, 214, 140]]
  const x = t * (stops.length - 1), i = Math.floor(x), f = x - i
  const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)]
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f]
    .map(v => Math.round(v)).join(',')
}

// 质量色谱叠加层：与深度画面 1:1 对位（画幅 619×480；后端网格已含裁剪/镜像）
export function QualityOverlay({ grid, on }) {
  if (!on || !grid || !grid.length) return null
  const rows = grid.length, cols = grid[0].length
  return (
    <div style={{
      position: 'absolute', inset: 0, display: 'grid', pointerEvents: 'none',
      gridTemplateRows: `repeat(${rows}, 1fr)`, gridTemplateColumns: `repeat(${cols}, 1fr)`,
      gap: 2, padding: 2, borderRadius: 9, overflow: 'hidden',
    }}>
      {grid.flatMap((row, i) => row.map((c, j) => (
        <div key={`${i}-${j}`} style={{
          background: `rgba(${covColor(c)},0.32)`,
          outline: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 2,
        }} />
      )))}
    </div>
  )
}

// 距离条三段色 + 当前中位距离指针
export function DistBar({ q }) {
  const mm = (q && q.d_med) ? q.d_med : 0
  const pos = Math.max(0, Math.min(1, mm / MAXV)) * 100
  const zone = q ? q.zone : 'none'
  const seg = (key, flex, label) => (
    <div style={{
      flex, display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 10, color: '#fff', letterSpacing: 1,
      background: key === 'near' ? '#ff6b6b' : key === 'best' ? '#3fd68c' : '#ffb454',
      opacity: zone === key ? 1 : 0.42, transition: 'opacity .2s',
    }}>{label}</div>
  )
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ position: 'relative', height: 20, borderRadius: 6, overflow: 'hidden', display: 'flex' }}>
        {seg('near', NEAR / MAXV, '太近')}
        {seg('best', (FAR - NEAR) / MAXV, '最 佳')}
        {seg('far', (MAXV - FAR) / MAXV, '太远')}
        {mm > 0 && (
          <div style={{
            position: 'absolute', top: -1, bottom: -1, left: `calc(${pos}% - 1.5px)`, width: 3,
            background: 'var(--fg)', boxShadow: '0 0 4px rgba(0,0,0,.7)', borderRadius: 2,
          }} />
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--dim)', marginTop: 3 }}>
        <span>0</span><span>0.5m</span><span>1.5m</span><span>2.5m+</span>
      </div>
    </div>
  )
}

// 面板（采集页/转台页共用）：状态灯 + 距离条 + 指标 + 色谱开关
// overlay / setOverlay 由父级持有（父级负责把 QualityOverlay 铺到深度画面上）
export default function QualityPanel({ q, overlay, setOverlay }) {
  const [localOv, setLocalOv] = useState(false)
  const ov = overlay !== undefined ? overlay : localOv
  const setOv = setOverlay || setLocalOv
  const ok = !!(q && q.ok)
  const light = ok ? (q.light || 'red') : 'red'
  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>采集质量</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            width: 9, height: 9, borderRadius: 5, display: 'inline-block',
            background: LIGHT_CSS[light],
            boxShadow: `0 0 6px ${LIGHT_CSS[light]}`,
          }} />
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            {ok ? (light === 'green' ? '合格' : light === 'yellow' ? '偏弱' : '不合格') : '待画面'}
          </span>
        </div>
      </div>
      <DistBar q={ok ? q : null} />
      <div style={{
        fontSize: 11.5, marginTop: 8, lineHeight: 1.6,
        color: light === 'green' ? 'var(--ok, #3fd68c)' : 'var(--muted)',
      }}>
        {ok ? q.hint : '等待深度画面…'}
      </div>
      <div className="stat" style={{ marginTop: 4 }}>
        <span className="k">有效覆盖</span>
        <span className="v">{ok ? `${q.valid_pct}%` : '--'}</span>
      </div>
      <div className="stat">
        <span className="k">中位距离</span>
        <span className="v">{ok && q.d_med ? `${q.d_med} mm` : '--'}</span>
      </div>
      <label style={{
        display: 'flex', alignItems: 'center', gap: 7, marginTop: 9,
        fontSize: 12, cursor: 'pointer', color: 'var(--muted)',
      }}>
        <input type="checkbox" checked={ov} onChange={e => setOv(e.target.checked)} />
        质量色谱叠加（红=覆盖差 / 绿=好）
      </label>
      <div style={{ fontSize: 11, color: 'var(--dim)', marginTop: 3 }}>
        只影响本页显示，采集/导出数据不受影响。
      </div>
    </div>
  )
}
