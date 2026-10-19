import { useEffect, useRef, useState } from 'react'
import { Sidebar, Topbar, Toast, StatePanel } from './components.jsx'
import ScanPage from './pages/ScanPage.jsx'
import FusionPage from './pages/FusionPage.jsx'
import SettingsPage from './pages/SettingsPage.jsx'
import AboutPage from './pages/AboutPage.jsx'
import { initialState } from './state.js'

export default function MockApp() {
  const [state, setState] = useState(() => {
    const q = new URLSearchParams(location.search).get('page')
    const h = location.hash.replace('#', '')
    const page = ['scan', 'fusion', 'settings', 'about'].includes(q) ? q : ['scan', 'fusion', 'settings', 'about'].includes(h) ? h : 'scan'
    return { ...initialState(), page }
  })
  const [toastMsg, setToastMsg] = useState('')
  const timer = useRef(null)

  const toast = (text) => {
    setToastMsg(text)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setToastMsg(''), 2800)
  }

  const setPage = (page) => setState((s) => ({ ...s, page }))

  useEffect(() => {
    document.documentElement.dataset.theme = state.theme
  }, [state.theme])

  useEffect(() => {
    const url = `${location.pathname}?page=${state.page}`
    if (location.search !== `?page=${state.page}`) history.replaceState(null, '', url)
  }, [state.page])

  const forceDevice = (id) => {
    setState((s) => ({
      ...s,
      device: id,
      streams: {
        ...s.streams,
        depth: id === 'connected' && !s.view.paused,
        rgb: id === 'connected' && !s.view.paused,
      },
    }))
  }

  const forceUpdate = (id) => {
    setState((s) => ({
      ...s,
      update: {
        ...s.update,
        status: id,
        progress: id === 'downloading' ? 45 : id === 'done' ? 100 : 0,
        checkedAt: id === 'idle' ? '尚未检查' : new Date().toTimeString().slice(0, 5),
      },
    }))
  }

  const forceFusion = (id) => {
    setState((s) => {
      const sel = s.sessions.find((x) => x.id === s.fusion.selected)
      if (id === 'running') {
        return { ...s, fusion: { ...s.fusion, running: true, pct: 45, stage: 2, result: null, error: null } }
      }
      if (id === 'done') {
        return {
          ...s,
          fusion: { ...s.fusion, running: false, pct: 100, stage: 4, result: sel ? `${sel.name}/fused_points.ply` : 'fused_points.ply', error: null },
          sessions: s.sessions.map((x) => x.id === s.fusion.selected
            ? { ...x, artifacts: ['fused_points.ply', 'fused_mesh.stl', 'fused_preview.png'] }
            : x),
        }
      }
      if (id === 'error') {
        return { ...s, fusion: { ...s.fusion, running: false, pct: 45, stage: 2, result: null, error: 'ICP 位姿精修失败：重叠区域不足' } }
      }
      return { ...s, fusion: { ...s.fusion, running: false, pct: 0, stage: 0, result: null, error: null } }
    })
  }

  const onTheme = (theme) => {
    document.documentElement.dataset.theme = theme
    setState((s) => ({ ...s, theme, settings: { ...s.settings, theme } }))
  }

  const pages = {
    scan: <ScanPage state={state} setState={setState} toast={toast} setPage={setPage} />,
    fusion: <FusionPage state={state} setState={setState} toast={toast} setPage={setPage} />,
    settings: <SettingsPage state={state} setState={setState} toast={toast} />,
    about: <AboutPage state={state} setState={setState} toast={toast} />,
  }

  return (
    <div className="af-app">
      <Sidebar page={state.page} setPage={setPage} />
      <div className="af-main">
        <Topbar state={state} setPage={setPage} onTogglePanel={() => setState((s) => ({ ...s, statePanel: !s.statePanel }))} />
        <main className="af-content">{pages[state.page] || pages.scan}</main>
      </div>
      <Toast msg={toastMsg} />
      <StatePanel
        state={state}
        onClose={() => setState((s) => ({ ...s, statePanel: false }))}
        onForceDevice={forceDevice}
        onForceUpdate={forceUpdate}
        onForceFusion={forceFusion}
        onTheme={onTheme}
        onToggle={() => setState((s) => ({ ...s, statePanel: !s.statePanel }))}
      />
    </div>
  )
}
