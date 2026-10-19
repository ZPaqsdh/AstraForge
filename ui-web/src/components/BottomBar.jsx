export default function BottomBar({ rec, task }) {
  const fmt = (s) => `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
  return (
    <footer className="af-bottom">
      <div className={`af-rec ${rec.on ? 'on' : ''}`}>
        <span className="af-rec-dot" />
        {rec.on ? `连续采集 ${fmt(rec.sec)}` : '未录制'}
      </div>
      <div className="af-task" title={task || ''}>{task || '空闲'}</div>
      <div className="af-bottom-right">
        <span>本地服务 127.0.0.1</span>
      </div>
    </footer>
  )
}
