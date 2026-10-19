// ui.jsx — 应用通用控件（单一来源：正式界面与后续调整都改这里）
import { X, Check } from 'lucide-react'

export function Btn({ primary, danger, ghost, small, wide, icon: Icon, className = '', children, ...rest }) {
  const cls = ['af-btn', primary ? 'primary' : '', danger ? 'danger' : '',
    ghost ? 'ghost' : '', small ? 'small' : '', wide ? 'wide' : '', className]
    .filter(Boolean).join(' ')
  return (
    <button className={cls} {...rest}>
      {Icon ? <Icon size={small ? 13 : 15} strokeWidth={2} /> : null}
      {children}
    </button>
  )
}

export function Field({ label, hint, children, className = '' }) {
  return (
    <label className={`af-field ${className}`}>
      <span className="af-field-label">{label}</span>
      <span className="af-field-control">{children}</span>
      {hint ? <span className="af-field-hint">{hint}</span> : null}
    </label>
  )
}

export function Stat({ k, v, tone }) {
  return (
    <div className="af-stat">
      <span className="k">{k}</span>
      <span className={`v ${tone || ''}`}>{v}</span>
    </div>
  )
}

export function Section({ title, aside, children, className = '' }) {
  return (
    <section className={`af-section ${className}`}>
      <header className="af-section-head">
        <h3>{title}</h3>
        {aside}
      </header>
      {children}
    </section>
  )
}

export function StepBar({ active }) {
  const steps = ['选择数据', '融合', '查看 / 导出']
  return (
    <div className="af-steps">
      {steps.map((s, i) => (
        <div key={s} className={`af-step ${i === active ? 'active' : ''} ${i < active ? 'done' : ''}`}>
          <span className="af-step-no">{i < active ? <Check size={12} /> : i + 1}</span>
          <span>{s}</span>
          {i < steps.length - 1 ? <span className="af-step-line" /> : null}
        </div>
      ))}
    </div>
  )
}

export function Modal({ title, children, onClose, width = 460 }) {
  return (
    <div className="af-modal-backdrop" onMouseDown={onClose}>
      <div className="af-modal" style={{ width }} onMouseDown={(e) => e.stopPropagation()}>
        <header>
          <h3>{title}</h3>
          <button onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </header>
        {children}
      </div>
    </div>
  )
}

export function Toast({ msg }) {
  if (!msg) return null
  return <div className="af-toast">{msg}</div>
}

export function Pill({ tone = '', children }) {
  return <span className={`af-pill ${tone}`}>{children}</span>
}

export function Empty({ icon: Icon, title, hint }) {
  return (
    <div className="af-empty">
      {Icon ? <Icon size={26} /> : null}
      <b>{title}</b>
      {hint ? <small>{hint}</small> : null}
    </div>
  )
}
