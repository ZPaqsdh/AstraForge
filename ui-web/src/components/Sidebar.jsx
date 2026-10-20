import { ScanLine, Boxes, SlidersHorizontal, Info, ChevronRight } from 'lucide-react'

export const NAV = [
  { id: 'scan', label: '三维扫描', hint: '设备 · 采集 · 建模', icon: ScanLine },
  { id: 'fusion', label: '融合工作台', hint: '会话 · 融合 · 产物', icon: Boxes },
  { id: 'settings', label: '设置', hint: '导出 · 性能 · 外观', icon: SlidersHorizontal },
  { id: 'about', label: '关于与更新', hint: '版本 · 驱动 · 反馈', icon: Info },
]

export default function Sidebar({ active, onChange, hasUpdate = false }) {
  return (
    <aside className="af-side">
      <div className="af-brand">
        <div className="af-logo">AF</div>
        <div className="af-brand-text">
          <b>AstraForge</b>
          <span>星铸 · 深度扫描工作台</span>
        </div>
      </div>
      <nav className="af-nav">
        {NAV.map(({ id, label, hint, icon: Icon }) => (
          <button key={id} className={`af-nav-item ${active === id ? 'active' : ''}`}
            onClick={() => onChange(id)}>
            <Icon size={17} strokeWidth={1.9} />
            <span className="af-nav-copy">
              <b>{label}</b>
              <small>{hint}</small>
            </span>
            {id === 'about' && hasUpdate ? <span className="af-nav-badge" title="有新版本" /> : null}
            {active === id ? <ChevronRight size={13} className="af-nav-arrow" /> : null}
          </button>
        ))}
      </nav>
      <div className="af-side-foot">
        <span className="af-dot ok" />
        <span>本地运行 · 数据不出本机</span>
      </div>
    </aside>
  )
}
