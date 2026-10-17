import { useEffect, useState } from 'react'
import Sidebar from './components/Sidebar.jsx'
import Topbar from './components/Topbar.jsx'
import BottomBar from './components/BottomBar.jsx'
import CapturePage from './pages/CapturePage.jsx'
import Scan3DPage from './pages/Scan3DPage.jsx'
import TurntablePage from './pages/TurntablePage.jsx'
import FusionPage from './pages/FusionPage.jsx'
import ToolboxPage from './pages/ToolboxPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'
import AboutPage from './pages/AboutPage.jsx'
import { api } from './api.js'
import { usePoll } from './hooks.jsx'

const PAGES = {
  capture: CapturePage,
  scan3d: Scan3DPage,
  turntable: TurntablePage,
  fusion: FusionPage,
  toolbox: ToolboxPage,
  settings: SettingsPage,
  about: AboutPage,
}

export default function App() {
  const [page, setPage] = useState(() => location.hash.replace('#', '') || 'capture')
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('af-theme') || 'light' } catch (e) { return 'light' }
  })
  const [state] = usePoll(api.state, 1500)
  const [logs] = usePoll(api.logs, 2000)
  const [toast, setToast] = useState(null)
  const [recSec, setRecSec] = useState(0)

  const status = {
    device: !!(state && state.device && state.device.streaming),
    rgb: !!(state && String(state.rgb).includes('已连接')),
    fps: state ? state.fps || 0 : 0,
  }
  const rec = { on: !!(state && state.rec_continuous) }
  const logList = logs ? logs.logs : []

  const showToast = (msg, ms = 3400) => {
    setToast(msg)
    setTimeout(() => setToast(t => (t === msg ? null : t)), ms)
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('af-theme', theme) } catch (e) {}
  }, [theme])

  // 窗口存活心跳（Edge 多进程模型：Python 侧以此判定窗口关闭 → 收尾关红外）
  useEffect(() => {
    const beat = () => fetch('/api/heartbeat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    }).catch(() => {})
    beat()
    const id = setInterval(beat, 3000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const onHash = () => {
      const h = location.hash.replace('#', '')
      if (PAGES[h]) setPage(h)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    if (location.hash !== '#' + page) history.replaceState(null, '', '#' + page)
  }, [page])

  // REC 计时（后端 continuous 开 → 走秒）
  useEffect(() => {
    if (!rec.on) { setRecSec(0); return }
    const id = setInterval(() => setRecSec(s => s + 1), 1000)
    return () => clearInterval(id)
  }, [rec.on])

  const Page = PAGES[page] || CapturePage
  const app = {
    page, setPage, status, rec, recSec, state, showToast,
    logs: logList,
    addLog: showToast,
  }
  return (
    <div className="flex" style={{ height: '100vh' }}>
      <Sidebar active={page} onChange={setPage} />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar status={status} theme={theme} onTheme={setTheme} />
        <main className="flex-1 overflow-auto" style={{ padding: 12 }}>
          <Page app={app} />
        </main>
        <BottomBar rec={{ ...rec, sec: recSec }} task={logList[logList.length - 1] || ''}
                    onFeedback={() => setPage('about')} />
      </div>
      {toast && (
        <div style={{
          position: 'fixed', left: '50%', top: 64, transform: 'translateX(-50%)',
          background: 'var(--card)', color: 'var(--fg)', padding: '8px 18px',
          borderRadius: 9, fontSize: 12.5, zIndex: 300, maxWidth: '70vw',
          border: '1px solid var(--border-strong)', wordBreak: 'break-all',
          textAlign: 'center', boxShadow: '0 8px 26px rgba(0,0,0,.35)',
        }}>{toast}</div>
      )}
    </div>
  )
}
