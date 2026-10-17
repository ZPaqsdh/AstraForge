export default function BottomBar({ rec, task, onFeedback }) {
  const fmt = (s) => `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
  return (
    <footer
      className="shrink-0 flex items-center px-4 gap-4"
      style={{ height: 34, background: 'var(--panel)', borderTop: '1px solid var(--border)', fontSize: 12, color: 'var(--muted)' }}
    >
      <div className="flex items-center gap-2" style={{ color: rec.on ? 'var(--err)' : 'var(--dim)', fontWeight: rec.on ? 600 : 400 }}>
        <span style={{
          width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
          background: rec.on ? 'var(--err)' : 'var(--dim)',
          animation: rec.on ? 'blink 1s infinite' : 'none',
        }} />
        {rec.on ? `连续采集 ${fmt(rec.sec)}` : '未录制'}
      </div>
      <div id="task-txt" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {task || '空闲'}
      </div>
      <div className="ml-auto flex items-center gap-3">
        <button
          onClick={onFeedback}
          style={{
            background: 'var(--btn)', border: '1px solid var(--border-strong)', color: 'var(--muted)',
            padding: '3px 12px', borderRadius: 9, fontSize: 11.5, cursor: 'pointer',
          }}
        >反馈</button>
        <span style={{ color: 'var(--dim)' }}>AstraForge v0.2.10</span>
      </div>
    </footer>
  )
}
