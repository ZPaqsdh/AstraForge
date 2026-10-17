export default function Topbar({ status, theme, onTheme }) {
  return (
    <header
      className="flex items-center gap-3 px-4 shrink-0"
      style={{ height: 50, background: 'var(--panel)', borderBottom: '1px solid var(--border)' }}
    >
      <div
        className="flex items-center justify-center font-bold"
        style={{
          width: 30, height: 30, borderRadius: 9, background: 'var(--accent)',
          color: '#fff', fontSize: 12, letterSpacing: 0.5,
        }}
      >AF</div>
      <div className="flex items-baseline gap-2">
        <b style={{ fontSize: 15.5 }}>AstraForge 星铸</b>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>深度扫描工作台</span>
        <span
          style={{
            fontSize: 11, color: 'var(--muted)', border: '1px solid var(--border-strong)',
            borderRadius: 9, padding: '1px 8px',
          }}
        >v0.2.10</span>
      </div>
      <div className="flex items-center gap-1.5 ml-2" style={{ fontSize: 13, color: 'var(--fg)' }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: status.device ? 'var(--ok)' : 'var(--dim)', display: 'inline-block' }} />
        {status.device ? '深度流运行中' : '设备未连接'}
      </div>
      <div className="flex items-center gap-1.5" style={{ fontSize: 13, color: 'var(--fg)' }}>
        <span style={{ width: 7, height: 7, borderRadius: '50%', background: status.rgb ? 'var(--ok)' : 'var(--dim)', display: 'inline-block' }} />
        {status.rgb ? 'RGB 已连接' : 'RGB 未连接'}
      </div>
      <div className="ml-auto flex items-center gap-3">
        <span style={{ fontFamily: 'Consolas, monospace', fontSize: 13 }}>{status.fps?.toFixed ? status.fps.toFixed(1) : '--'} fps</span>
        <div id="theme-switch" style={{ display: 'flex', border: '1px solid var(--border-strong)', borderRadius: 9, overflow: 'hidden' }}>
          {[['light', '浅色'], ['dark', '深色'], ['auto', '自动']].map(([k, label]) => (
            <button
              key={k}
              onClick={() => onTheme(k)}
              style={{
                background: theme === k ? 'var(--accent)' : 'transparent',
                color: theme === k ? '#fff' : 'var(--muted)',
                border: 'none', padding: '4px 11px', fontSize: 12, cursor: 'pointer',
              }}
            >{label}</button>
          ))}
        </div>
      </div>
    </header>
  )
}
