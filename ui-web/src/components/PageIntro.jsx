import { useState } from 'react'

/** 页首介绍条：每页首次打开显示，点 × 后记住不再显示 */
export default function PageIntro({ id, children }) {
  const key = `af-intro-${id}`
  const [shown, setShown] = useState(() => {
    try { return localStorage.getItem(key) !== '1' } catch (e) { return true }
  })
  if (!shown) return null
  return (
    <div
      className="page-intro"
      style={{ display: 'flex', alignItems: 'flex-start', gap: 9, background: 'var(--accent-dim)',
        border: '1px solid var(--border)', borderLeft: '3px solid var(--accent)', borderRadius: 9,
        padding: '9px 13px', marginBottom: 12, fontSize: 13, color: 'var(--fg)', lineHeight: 1.75 }}
    >
      <span>{children}</span>
      <span
        title="知道了，不再显示"
        style={{ marginLeft: 'auto', cursor: 'pointer', color: 'var(--muted)', padding: '0 5px', fontSize: 15, flexShrink: 0 }}
        onClick={() => {
          setShown(false)
          try { localStorage.setItem(key, '1') } catch (e) {}
        }}
      >×</span>
    </div>
  )
}
