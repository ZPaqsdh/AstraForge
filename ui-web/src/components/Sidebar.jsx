import {
  Camera, ScanLine, RotateCw, Sparkles, Wrench, SlidersHorizontal, Info,
} from 'lucide-react'

export const NAV = [
  { id: 'capture', label: '采集', icon: Camera, section: '工作区' },
  { id: 'scan3d', label: '3D 扫描', icon: ScanLine },
  { id: 'turntable', label: '转台', icon: RotateCw },
  { id: 'fusion', label: '融合', icon: Sparkles },
  { id: 'toolbox', label: '工具箱', icon: Wrench, section: '工具' },
  { id: 'settings', label: '设置', icon: SlidersHorizontal },
  { id: 'about', label: '关于', icon: Info },
]

export default function Sidebar({ active, onChange }) {
  return (
    <nav
      className="shrink-0 overflow-y-auto"
      style={{
        width: 148, background: 'var(--panel)', borderRight: '1px solid var(--border)',
        padding: '8px 6px',
      }}
    >
      {NAV.map((it) => (
        <div key={it.id}>
          {it.section && (
            <div style={{ fontSize: 10.5, color: 'var(--dim)', padding: '12px 10px 4px', letterSpacing: 0.8 }}>
              {it.section}
            </div>
          )}
          <button
            className={`nav-item${active === it.id ? ' active' : ''}`}
            onClick={() => onChange(it.id)}
          >
            <it.icon size={16} />
            {it.label}
          </button>
        </div>
      ))}
    </nav>
  )
}
