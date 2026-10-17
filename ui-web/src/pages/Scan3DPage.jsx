import { useEffect, useRef, useState } from 'react'
import PageIntro from '../components/PageIntro.jsx'
import { api } from '../api.js'
import { FrameImg, usePoll } from '../hooks.jsx'

export default function Scan3DPage({ app }) {
  const { showToast, setPage } = app
  const [recording, setRecording] = useState(false)
  const [count, setCount] = useState(0)
  const [sec, setSec] = useState(0)
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)
  // 预览镜像（显示层）：与采集页共用同一全局值
  const [flip, setFlip] = useState(true)
  const flipSynced = useRef(false)
  const st = usePoll(api.state, 1500)[0]
  useEffect(() => {
    if (!flipSynced.current && st && typeof st.preview_mirror === 'boolean') {
      flipSynced.current = true
      setFlip(st.preview_mirror)
    }
  }, [st])
  const toggleMirror = async () => {
    const v = !flip; setFlip(v)
    await api.setFlip(v).catch(() => {})
    showToast(`预览镜像: ${v ? '开' : '关'}`)
  }

  // 记录中：每 500ms 拍一帧（后端 scan_shoot）
  useEffect(() => {
    if (!recording) return
    const id = setInterval(async () => {
      try {
        const r = await api.scanShoot()
        if (r.ok) setCount(r.count)
      } catch { /* 忽略单帧失败 */ }
    }, 500)
    const t = setInterval(() => setSec(s => s + 1), 1000)
    return () => { clearInterval(id); clearInterval(t) }
  }, [recording])

  const start = async () => {
    setBusy(true)
    try {
      await api.scanStart()
      setCount(0); setSec(0); setRecording(true)
      showToast('✓ 手持记录开始 —— 缓慢围绕物体移动相机')
    } catch (e) { showToast(`✗ ${e.message}`) }
    finally { setBusy(false) }
  }

  const stop = async () => {
    setRecording(false)
    setBusy(true)
    try {
      const r = await api.scanFinish()
      if (r.ok) showToast(`✓ 记录完成 → ${r.dir}（共 ${count} 帧）去融合页生成模型`, 5000)
      else showToast('✗ 一帧都没记上')
    } catch (e) { showToast(`✗ ${e.message}`) }
    finally { setBusy(false) }
  }

  const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`

  return (
    <div className="fade-in page-grid">
      <PageIntro id="scan3d">
        <b>3D 扫描（手持记录）</b>：没有转台时的方案。点「开始记录」后拿相机<b>缓慢</b>围绕物体移动，软件每 0.5 秒记一帧；记录完成后去「融合」页把这一串帧拼成完整模型。移动越快、场景越单调，拼合越容易失败——慢一点、多绕一圈效果最好。
      </PageIntro>
      <div className="layout-side">
        <div className="side-col">
          <div className="card">
            <h3>记录控制</h3>
            {!recording ? (
              <button className="btn primary wide" disabled={busy} onClick={start}>● 开始记录</button>
            ) : (
              <button className="btn rec-on wide" onClick={stop}>■ 停止记录（{fmt(sec)}）</button>
            )}
            <div className="stat" style={{ marginTop: 10 }}><span className="k">已记帧数</span><span className="v">{count}</span></div>
            <div className="stat"><span className="k">记录时长</span><span className="v">{fmt(sec)}</span></div>
            <div className="stat"><span className="k">记录节奏</span><span className="v">每 0.5 秒 1 帧</span></div>
            <div className="row" style={{ marginTop: 8, marginBottom: 0 }}>
              <button className="btn" style={{ marginLeft: 'auto' }} onClick={toggleMirror}>镜像 (M)</button>
            </div>
            <button className="btn wide" style={{ marginTop: 8 }} onClick={() => setPage('fusion')}>完成 → 去融合</button>
          </div>
          <div className="card">
            <h3>操作要领</h3>
            <div className="hint">
              ① 相机对准物体，距离 0.5~1.5 米最佳<br />
              ② <b>缓慢</b>围绕物体移动（一圈 20~40 秒）<br />
              ③ 保持物体在画面中心，光照稳定<br />
              ④ 纹理丰富的物体拼合效果好；纯白墙面会失败<br />
              ⑤ 记录完成后到「融合」页选 scan_session_* 目录
            </div>
          </div>
        </div>
        <div style={{ display: 'grid', gap: 12, alignContent: 'start' }}>
          <div className="card" style={{ padding: 9 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)', gap: 10, alignItems: 'stretch' }}>
              <div>
                <div className="hint" style={{ marginBottom: 6 }}>彩色画面</div>
                <FrameImg kind="rgb" style={{ width: '100%', height: 'auto' }} />
              </div>
              <div>
                <div className="hint" style={{ marginBottom: 6 }}>深度画面</div>
                <FrameImg kind="depth" style={{ width: '100%', height: 'auto' }} />
              </div>
            </div>
            {recording && (
              <div style={{
                marginTop: 8, display: 'flex', alignItems: 'center', gap: 8,
                color: 'var(--err)', fontWeight: 600, fontSize: 13,
              }}>
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: 'var(--err)', animation: 'blink 1s infinite' }} />
                正在记录 {fmt(sec)} · 已记 {count} 帧
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
