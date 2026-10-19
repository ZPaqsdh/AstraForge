import { useEffect, useMemo, useState } from 'react'
import rgbUrl from './assets/rgb.png'
import depthUrl from './assets/depth.png'
import depthGrayUrl from './assets/depth-gray.png'
import {
  ScanLine, Boxes, Settings as SettingsIcon, Info, Usb, RefreshCw, Play, Square,
  Download, FolderOpen, Copy, Mail, GitBranch, Check, AlertTriangle, X, Camera,
  RotateCw, Activity, ChevronDown, ChevronRight, Layers, Monitor, Sun, Moon,
  Cpu, FileText, Package, ExternalLink, Bug, Send,
} from 'lucide-react'

export function Btn({ primary, danger, ghost, small, wide, icon: Icon, className = '', children, ...rest }) {
  const cls = ['af-btn', primary ? 'primary' : '', danger ? 'danger' : '', ghost ? 'ghost' : '', small ? 'small' : '', wide ? 'wide' : '', className]
    .filter(Boolean).join(' ')
  return (
    <button className={cls} {...rest}>
      {Icon ? <Icon size={small ? 13 : 15} strokeWidth={2} /> : null}
      {children}
    </button>
  )
}

export function Field({ label, hint, children }) {
  return (
    <label className="af-field">
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

export function Sidebar({ page, setPage }) {
  const items = [
    { id: 'scan', label: '三维扫描', hint: '设备 · 采集 · 建模', icon: ScanLine },
    { id: 'fusion', label: '融合工作台', hint: '会话 · 融合 · 产物', icon: Boxes },
    { id: 'settings', label: '设置', hint: '导出 · 性能 · 外观', icon: SettingsIcon },
    { id: 'about', label: '关于与更新', hint: '版本 · 驱动 · 反馈', icon: Info },
  ]
  return (
    <aside className="af-side">
      <div className="af-brand">
        <div className="af-logo">AF</div>
        <div className="af-brand-text">
          <b>AstraForge</b>
          <span>星铸 · UI 复刻台</span>
        </div>
      </div>
      <nav className="af-nav">
        {items.map(({ id, label, hint, icon: Icon }) => (
          <button
            key={id}
            className={`af-nav-item ${page === id ? 'active' : ''}`}
            onClick={() => setPage(id)}
          >
            <Icon size={17} strokeWidth={1.9} />
            <span className="af-nav-copy">
              <b>{label}</b>
              <small>{hint}</small>
            </span>
            {page === id ? <ChevronRight size={13} className="af-nav-arrow" /> : null}
          </button>
        ))}
      </nav>
      <div className="af-side-foot">
        <span className="af-mock-badge">MOCK</span>
        <span>假数据 · 不接硬件</span>
      </div>
    </aside>
  )
}

export function Topbar({ state, setPage, onTogglePanel }) {
  const connected = state.device === 'connected'
  const statusText = {
    none: '未检测到设备',
    detected: '设备待连接',
    connecting: '连接中…',
    connected: '深度流运行中',
    driver: '驱动异常',
    error: '连接失败',
  }[state.device] || '未知'
  return (
    <header className="af-top">
      <button className="af-device-chip" onClick={() => setPage('scan')} title="前往三维扫描的设备连接">
        <span className={`af-dot ${connected ? 'ok' : state.device === 'error' || state.device === 'driver' ? 'err' : 'idle'}`} />
        <span className="af-device-name">{state.deviceInfo.model}</span>
        <span className="af-device-state">{statusText}</span>
      </button>
      <div className="af-top-divider" />
      <span className={`af-top-meta ${state.streams.rgb ? '' : 'off'}`}>
        <Camera size={13} /> RGB {state.streams.rgb ? '已连接' : '未连接'}
      </span>
      <span className="af-top-meta">
        <Activity size={13} /> {connected ? `${state.streams.fps.toFixed(1)} fps` : '— fps'}
      </span>
      <div className="af-top-right">
        <span className="af-build">v0.2.10 · mock</span>
        <button className="af-icon-btn" onClick={onTogglePanel} title="场景切换面板">
          <Monitor size={15} />
        </button>
      </div>
    </header>
  )
}

export function Toast({ msg }) {
  if (!msg) return null
  return <div className="af-toast">{msg}</div>
}

export function DeviceBar({ state, onDisconnect, onDiagnose }) {
  if (state.device !== 'connected') return null
  return (
    <div className="af-device-bar">
      <span className="af-dot ok" />
      <b>{state.deviceInfo.model}</b>
      <span className="af-mono">{state.deviceInfo.pid}</span>
      <span className="af-sep">·</span>
      <span>深度 {state.streams.depth ? '流中' : '停止'}</span>
      <span className="af-sep">·</span>
      <span>RGB {state.streams.rgb ? '流中' : '停止'}</span>
      <span className="af-sep">·</span>
      <span className="af-mono">{state.streams.fps.toFixed(1)} fps</span>
      <span className="af-device-spacer" />
      <Btn small ghost icon={Bug} onClick={onDiagnose}>诊断</Btn>
      <Btn small onClick={onDisconnect}>断开</Btn>
    </div>
  )
}

export function ConnectionView({ state, onConnect, onDetect, onDriverHelp, onRetry, onDiagnose }) {
  const info = state.deviceInfo
  if (state.device === 'none') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card">
          <div className="af-connect-icon"><Usb size={28} /></div>
          <h2>未检测到 Astra 设备</h2>
          <p>插好相机后点「重新检测」。深度相机需要绑定 WinUSB；如果装过 obdrv，需要先切换驱动。</p>
          <div className="af-row center">
            <Btn primary icon={RefreshCw} onClick={onDetect}>重新检测</Btn>
            <Btn icon={Usb} onClick={onDriverHelp}>驱动帮助</Btn>
          </div>
          <span className="af-connect-note">复刻台：这里是假数据，点「重新检测」会直接进入已检测状态。</span>
        </div>
      </div>
    )
  }
  if (state.device === 'driver') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card warn">
          <div className="af-connect-icon warn"><AlertTriangle size={28} /></div>
          <h2>驱动需要切换</h2>
          <p>检测到 {info.model}（{info.pid}），当前驱动不是 WinUSB。运行时无法打开深度流。</p>
          <div className="af-connect-meta">
            <Stat k="设备" v={info.model} />
            <Stat k="PID" v={info.pid} />
            <Stat k="当前驱动" v="obdrv" tone="warn" />
          </div>
          <div className="af-row center">
            <Btn primary icon={Usb} onClick={onDriverHelp}>查看驱动方案</Btn>
            <Btn icon={RefreshCw} onClick={onDetect}>重新检测</Btn>
          </div>
        </div>
      </div>
    )
  }
  if (state.device === 'error') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card err">
          <div className="af-connect-icon err"><AlertTriangle size={28} /></div>
          <h2>连接失败</h2>
          <p>USB 已被其他程序占用，或设备刚被重新枚举。关闭占用程序后重试。</p>
          <div className="af-row center">
            <Btn primary icon={RefreshCw} onClick={onRetry}>重试</Btn>
            <Btn icon={Copy} onClick={onDiagnose}>复制诊断</Btn>
          </div>
        </div>
      </div>
    )
  }
  if (state.device === 'connecting') {
    return (
      <div className="af-connect-wrap">
        <div className="af-connect-card">
          <div className="af-connect-icon"><RefreshCw size={28} className="af-spin" /></div>
          <h2>正在连接设备</h2>
          <div className="af-connect-steps">
            <span className="done">打开 USB</span>
            <span className="active">启动深度流</span>
            <span>启动彩色流</span>
          </div>
          <p>首次连接约 1–2 秒。相机独占，请先关闭其他占用程序。</p>
        </div>
      </div>
    )
  }
  return (
    <div className="af-connect-wrap">
      <div className="af-connect-card">
        <div className="af-connect-icon ok"><Check size={28} /></div>
        <h2>发现设备</h2>
        <p>确认设备信息后连接。连接成功后，深度流与彩色流会同时启动。</p>
        <div className="af-connect-meta">
          <Stat k="型号" v={info.model} />
          <Stat k="PID" v={info.pid} />
          <Stat k="序列号" v={info.serial} />
          <Stat k="驱动" v={info.driver} tone="ok" />
        </div>
        <div className="af-row center">
          <Btn primary icon={Play} onClick={onConnect}>连接设备</Btn>
          <Btn icon={RefreshCw} onClick={onDetect}>重新检测</Btn>
        </div>
      </div>
    </div>
  )
}

export function QualityPanel({ quality, view, setView, compact = false }) {
  const pct = Math.max(0, Math.min(100, (quality.distance / 2500) * 100))
  const statusText = quality.status === 'ok' ? '距离合适' : quality.status === 'warn' ? '覆盖偏弱' : '距离不合适'
  return (
    <div className={`af-quality ${compact ? 'compact' : ''}`}>
      <div className="af-quality-head">
        <h4>采集质量</h4>
        <span className={`af-quality-light ${quality.status}`} />
        <span className="af-quality-state">{statusText}</span>
      </div>
      <div className="af-distance">
        <div className="af-distance-track">
          <span className="seg near" />
          <span className="seg best" />
          <span className="seg far" />
          <span className="af-distance-marker" style={{ left: `${pct}%` }} />
        </div>
        <div className="af-distance-labels">
          <span>近</span><span>最佳 0.5–1.5 m</span><span>远</span>
        </div>
        <div className="af-distance-value">{quality.distance} mm</div>
      </div>
      <div className="af-quality-row">
        <span>覆盖</span>
        <div className="af-bar"><span style={{ width: `${quality.coverage * 100}%` }} /></div>
        <b>{Math.round(quality.coverage * 100)}%</b>
      </div>
      <label className="af-check">
        <input type="checkbox" checked={view.quality} onChange={(e) => setView({ ...view, quality: e.target.checked })} />
        <span>显示 6×8 覆盖色谱</span>
      </label>
    </div>
  )
}

export function QualityOverlay({ grid, visible, gray }) {
  if (!visible) return null
  return (
    <div className={`af-quality-overlay ${gray ? 'gray' : ''}`} aria-hidden="true">
      {grid.map((v, i) => (
        <span key={i} style={{
          background: gray
            ? `rgba(255,255,255,${0.035 + v * 0.16})`
            : `rgba(${v > 0.62 ? '108,203,95' : v > 0.32 ? '232,166,60' : '241,76,76'},${0.16 + v * 0.42})`,
        }} />
      ))}
    </div>
  )
}

export function PreviewPair({ state, setView, onHover }) {
  const [hover, setHover] = useState('')
  const gray = state.view.gray
  const mirror = state.view.mirror
  const paused = state.view.paused
  const handleMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const x = Math.round(((e.clientX - r.left) / r.width) * 619)
    const y = Math.round(((e.clientY - r.top) / r.height) * 480)
    const v = 1180 + ((x * 13 + y * 7) % 80)
    setHover(`(${x}, ${y})  shift ${v}  ≈ ${Math.round(342098.34 / (1330 - v))} mm`)
    if (onHover) onHover(hover)
  }
  return (
    <div className="af-preview-pair">
      <figure className="af-frame">
        <figcaption>
          <span className="af-frame-title">彩色 RGB</span>
          <span className="af-frame-meta">640 × 480</span>
        </figcaption>
        <div className="af-frame-body">
          <img src={rgbUrl} alt="RGB 预览" style={{ transform: mirror ? 'scaleX(-1)' : 'none' }} />
          {paused ? <span className="af-paused">已暂停</span> : null}
          <span className="af-live"><i />LIVE</span>
        </div>
      </figure>
      <figure className="af-frame">
        <figcaption>
          <span className="af-frame-title">深度 DEPTH</span>
          <span className="af-frame-meta">619 × 480 · {gray ? '灰度' : '伪彩'}</span>
        </figcaption>
        <div className="af-frame-body" onMouseMove={handleMove} onMouseLeave={() => setHover('')}>
          <img src={gray ? depthGrayUrl : depthUrl} alt="深度预览" style={{ transform: mirror ? 'scaleX(-1)' : 'none' }} />
          <QualityOverlay grid={state.quality.grid} visible={state.view.quality} gray={gray} />
          {paused ? <span className="af-paused">已暂停</span> : null}
          {hover ? <span className="af-hover">{hover}</span> : null}
        </div>
      </figure>
    </div>
  )
}

export function StatePanel({ state, onClose, onForceDevice, onForceUpdate, onForceFusion, onTheme, onToggle }) {
  if (!state.statePanel) return null
  return (
    <div className="af-state-panel">
      <header>
        <b>场景切换</b>
        <span>仅复刻台</span>
        <button onClick={onClose} title="收起"><X size={14} /></button>
      </header>
      <div className="af-state-group">
        <label>设备</label>
        <div className="af-chips">
          {[
            ['none', '未检测'], ['detected', '已检测'], ['connecting', '连接中'],
            ['connected', '已连接'], ['driver', '驱动异常'], ['error', '连接失败'],
          ].map(([id, label]) => (
            <button key={id} className={state.device === id ? 'active' : ''} onClick={() => onForceDevice(id)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="af-state-group">
        <label>更新</label>
        <div className="af-chips">
          {[['idle', '无更新'], ['available', '有新版本'], ['downloading', '下载中'], ['done', '已安装'], ['error', '失败']].map(([id, label]) => (
            <button key={id} className={state.update.status === id ? 'active' : ''} onClick={() => onForceUpdate(id)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="af-state-group">
        <label>融合</label>
        <div className="af-chips">
          {[['idle', '空闲'], ['running', '45%'], ['done', '完成'], ['error', '失败']].map(([id, label]) => (
            <button key={id} className={
              (state.fusion.running && id === 'running') || (!state.fusion.running && state.fusion.result && id === 'done') || (!state.fusion.running && !state.fusion.result && id === 'idle') ? 'active' : ''
            } onClick={() => onForceFusion(id)}>{label}</button>
          ))}
        </div>
      </div>
      <div className="af-state-group">
        <label>主题</label>
        <div className="af-chips">
          <button className={state.theme === 'light' ? 'active' : ''} onClick={() => onTheme('light')}><Sun size={12} /> 浅色</button>
          <button className={state.theme === 'dark' ? 'active' : ''} onClick={() => onTheme('dark')}><Moon size={12} /> 深色</button>
        </div>
      </div>
    </div>
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
          <button onClick={onClose}><X size={16} /></button>
        </header>
        {children}
      </div>
    </div>
  )
}
