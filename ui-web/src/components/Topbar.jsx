import { Camera, Activity, Usb } from 'lucide-react'

export default function Topbar({ state, onDeviceClick }) {
  const dev = state && state.device ? state.device : {}
  const connected = !!dev.streaming
  const opened = !!dev.connected
  const text = connected ? '深度流运行中' : opened ? '已连接 · 等待数据' : '设备未连接'
  return (
    <header className="af-top">
      <button className="af-device-chip" onClick={onDeviceClick} title="前往三维扫描的设备连接">
        <span className={`af-dot ${connected ? 'ok' : opened ? 'idle' : 'err'}`} />
        <span className="af-device-name">Astra 深度相机</span>
        <span className="af-device-state">{text}</span>
      </button>
      <div className="af-top-divider" />
      <span className={`af-top-meta ${state && String(state.rgb).includes('已连接') ? '' : 'off'}`}>
        <Camera size={13} /> RGB {state && String(state.rgb).includes('已连接') ? '已连接' : '未连接'}
      </span>
      <span className="af-top-meta">
        <Activity size={13} /> {connected && state ? `${(state.fps || 0).toFixed(1)} fps` : '— fps'}
      </span>
      <div className="af-top-right">
        <span className="af-build"><Usb size={11} /> 2BC5:0403</span>
      </div>
    </header>
  )
}
