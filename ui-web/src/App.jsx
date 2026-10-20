import { useEffect, useRef, useState } from 'react'
import { Download } from 'lucide-react'
import Sidebar from './components/Sidebar.jsx'
import Topbar from './components/Topbar.jsx'
import BottomBar from './components/BottomBar.jsx'
import ScanPage from './pages/ScanPage.jsx'
import FusionPage from './pages/FusionPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'
import AboutPage from './pages/AboutPage.jsx'
import { api } from './api.js'
import { Toast } from './ui.jsx'

const PAGES = {
  scan: ScanPage,
  fusion: FusionPage,
  settings: SettingsPage,
  about: AboutPage,
}

const ORDER = ['scan', 'fusion', 'settings', 'about']

export default function App() {
  const [page, setPage] = useState(() => {
    const h = location.hash.replace('#', '')
    return PAGES[h] ? h : 'scan'
  })
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem('af-theme') || 'light' } catch (e) { return 'light' }
  })
  const [state, setState] = useState(null)
  const [logs, setLogs] = useState([])
  const [toast, setToast] = useState('')
  const [recSec, setRecSec] = useState(0)
  const [upd, setUpd] = useState(null)          // 自动更新状态（后端 4s 首检 / 12h 周期）
  const [dismissed, setDismissed] = useState([]) // 本次运行已关掉的版本（不落盘 → 关闭重置）
  const toastTimer = useRef(null)

  const showToast = (msg, ms = 3600) => {
    setToast(msg)
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(''), ms)
  }

  const reload = async () => {
    try {
      const s = await api.state()
      setState(s)
      return s
    } catch (e) {
      return null
    }
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('af-theme', theme) } catch (e) {}
  }, [theme])

  // 状态轮询（1.5s）；页面切走后仍保留，顶栏/底栏不闪
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const s = await api.state()
        if (alive) setState(s)
      } catch (e) { /* 启动瞬间后端未就绪 */ }
    }
    tick()
    const id = setInterval(tick, 1500)
    return () => { alive = false; clearInterval(id) }
  }, [])

  // 日志轮询
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const r = await api.logs(50)
        if (alive) setLogs(r.logs || [])
      } catch (e) {}
    }
    tick()
    const id = setInterval(tick, 2500)
    return () => { alive = false; clearInterval(id) }
  }, [])

  // 窗口存活心跳（Qt 壳关闭 → Python 收尾关红外）
  useEffect(() => {
    const beat = () => fetch('/api/heartbeat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    }).catch(() => {})
    beat()
    const id = setInterval(beat, 3000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (location.hash !== '#' + page) history.replaceState(null, '', '#' + page)
  }, [page])

  useEffect(() => {
    const onHash = () => {
      const h = location.hash.replace('#', '')
      if (PAGES[h]) setPage(h)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // 连续采集计时
  useEffect(() => {
    if (!(state && state.rec_continuous)) { setRecSec(0); return }
    const id = setInterval(() => setRecSec((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [state && state.rec_continuous])

  // 自动更新状态（后端启动 4s 后首检、每 12h 一次；这里只做轻轮询）
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const u = await api.updateState()
        if (alive) setUpd(u)
      } catch (e) { /* 后端未就绪 */ }
    }
    tick()
    const id = setInterval(tick, 20000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const hasUpdate = !!(upd && upd.has_update)
  const bannerOn = hasUpdate && !dismissed.includes(upd.latest)

  const Page = PAGES[page] || ScanPage
  const app = {
    page, setPage, state, reload, logs, showToast, theme, setTheme,
    version: state ? state.version : '',
    update: upd,
    refreshUpdate: async () => {
      try { const u = await api.updateState(); setUpd(u); return u } catch (e) { return null }
    },
  }
  const rec = { on: !!(state && state.rec_continuous), sec: recSec }
  const lastLog = logs.length ? logs[logs.length - 1] : ''

  return (
    <div className="af-app">
      <Sidebar active={page} onChange={setPage} hasUpdate={hasUpdate} />
      <div className="af-main">
        <Topbar state={state} version={app.version} onDeviceClick={() => setPage('scan')} />
        {bannerOn ? (
          <div className="af-update-banner">
            <Download size={14} />
            <span>发现新版本 <b>v{upd.latest}</b>（当前 v{upd.current}）</span>
            <button className="af-update-banner-go"
              onClick={() => { setPage('about'); setDismissed((d) => [...d, upd.latest]) }}>
              查看更新
            </button>
            <button className="af-update-banner-x" title="本次运行不再提示"
              onClick={() => setDismissed((d) => [...d, upd.latest])}>×</button>
          </div>
        ) : null}
        <main className="af-content">
          <Page app={app} />
        </main>
        <BottomBar rec={rec} task={lastLog} />
      </div>
      <Toast msg={toast} />
    </div>
  )
}
