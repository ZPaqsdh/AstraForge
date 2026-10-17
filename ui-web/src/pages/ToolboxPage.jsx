import { useEffect, useRef, useState } from 'react'
import PageIntro from '../components/PageIntro.jsx'
import { api } from '../api.js'
import { FrameImg } from '../hooks.jsx'

// 预览深度画幅：640 宽裁掉右缘 21 列固定垃圾带（BUG-009 显示层裁剪）→ 619×480
const DW = 619, DH = 480

export default function ToolboxPage({ app }) {
  const { showToast } = app
  // ---- 标定 ----
  const [knownMm, setKnownMm] = useState('500')
  const [roi, setRoi] = useState('40')
  const [calResult, setCalResult] = useState('')
  const [sampled, setSampled] = useState(null)

  const calSample = async () => {
    try {
      const r = await api.calibSample(parseFloat(knownMm || '500'), parseInt(roi || '40'))
      if (r.ok) {
        setSampled(r.k)
        setCalResult(`采样: ${2 * parseInt(roi || '40')}x${2 * parseInt(roi || '40')} 区，中位深度 ${r.median} shift → mm/shift = ${r.k.toFixed(4)}（点“保存标定”生效）`)
      } else setCalResult(`采样失败: ${r.error}`)
    } catch (e) { setCalResult(`采样失败: ${e.message}`) }
  }

  const calSave = async () => {
    if (!sampled) { setCalResult('先采样再保存'); return }
    try {
      const r = await api.calibSave(sampled)
      setCalResult(r.ok ? `✓ 已保存并生效: ${sampled.toFixed(4)} mm/shift` : '保存失败')
      if (r.ok) showToast(`✓ 标定已保存: ${sampled.toFixed(4)} mm/shift`)
    } catch (e) { setCalResult(`保存失败: ${e.message}`) }
  }

  // ---- 测距（默认关闭：不加载画面流，节省资源） ----
  const [measureOn, setMeasureOn] = useState(false)
  const [pts, setPts] = useState([])
  const [dist, setDist] = useState('')
  const depthRef = useRef(null)

  const onCanvasClick = async (e) => {
    if (!measureOn) return
    const r = e.currentTarget.getBoundingClientRect()
    const x = Math.round((e.clientX - r.left) / r.width * DW)
    const y = Math.round((e.clientY - r.top) / r.height * DH)
    const np = [...pts, [x, y]].slice(-2)
    setPts(np)
    if (np.length === 2) {
      try {
        const r2 = await api.measure(np[0][0], np[0][1], np[1][0], np[1][1])
        setDist(r2.ok ? `${r2.dist_mm} mm` : `失败: ${r2.error}`)
      } catch (err) { setDist(`失败: ${err.message}`) }
      setPts([])
    }
  }

  // ---- 显示设置 ----
  const [lo, setLo] = useState('0')
  const [hi, setHi] = useState('2500')
  // 启动预填已保存的显示范围（设置自动保存 → 界面回显一致）
  useEffect(() => {
    api.settings().then(s => {
      if (s && Array.isArray(s.disp_range)) {
        setLo(String(Math.round(s.disp_range[0])))
        setHi(String(Math.round(s.disp_range[1])))
      }
    }).catch(() => {})
  }, [])
  const applyRange = async () => {
    try {
      await api.setDispRange(parseFloat(lo || '0'), parseFloat(hi || '2500'))
      showToast('✓ 深度显示范围已应用（采集页生效）')
    } catch (e) { showToast(`✗ ${e.message}`) }
  }

  // ---- 诊断 ----
  const copyDiag = async () => {
    try {
      const d = await api.diag()
      const txt = JSON.stringify(d, null, 2)
      await navigator.clipboard.writeText(txt)
      showToast('✓ 诊断信息已复制到剪贴板（反馈时粘贴给开发者/AI）')
    } catch (e) { showToast(`✗ 复制失败: ${e.message}（请手动截图关于页）`) }
  }

  return (
    <div className="fade-in page-grid">
      <PageIntro id="toolbox">
        <b>工具箱</b>：标定（量一次真实距离，软件记住比例，长期有效）、测距（在深度画面上点两个点量距离）、显示设置（调整深度色带）、诊断（一键复制系统信息，反馈问题时用）。
      </PageIntro>
      <div className="layout-cards">
        {/* 标定 */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3>深度标定（shift → mm）</h3>
          <div className="hint" style={{ marginBottom: 8 }}>
            把已知尺寸的平面（白纸/书本）正对镜头放好，用尺子量出相机到它的距离填入，点采样。
          </div>
          <div className="field"><label>已知距离 (mm)</label><input type="text" value={knownMm} onChange={e => setKnownMm(e.target.value)} style={{ width: 90 }} /></div>
          <div className="field"><label>采样区边长 (px)</label><input type="text" value={roi} onChange={e => setRoi(e.target.value)} style={{ width: 90 }} /></div>
          <div style={{ marginTop: 'auto', paddingTop: 10 }}>
            <div className="row">
              <button className="btn" onClick={calSample}>采样</button>
              <button className="btn primary" onClick={calSave}>保存标定</button>
            </div>
            <div className="hint" style={{ marginTop: 9, wordBreak: 'break-all' }}>{calResult || '当前标定值见采集页状态卡'}</div>
          </div>
        </div>

        {/* 测距（默认关闭：开启后才加载深度画面） */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3>测距（深度画面点两点）</h3>
          <div className="hint" style={{ marginBottom: 8 }}>
            {measureOn ? '已开启 —— 在下方深度画面上点两个点，量 3D 直线距离。'
                       : '默认关闭：不加载画面、节省资源。点「开启测距」后加载深度画面。'}
          </div>
          <div style={{
            position: 'relative', flex: 1, minHeight: 200,
            display: 'flex', alignItems: measureOn ? 'flex-start' : 'center', justifyContent: 'center',
            background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 9, overflow: 'hidden',
          }}>
            {measureOn ? (
              <div style={{ position: 'relative', width: '100%' }}>
                <FrameImg kind="depth" onClick={onCanvasClick}
                  style={{ width: '100%', height: 'auto', display: 'block', cursor: 'crosshair' }} />
                {pts.map(([x, y], i) => (
                  <span key={i} style={{
                    position: 'absolute', left: `${x / DW * 100}%`, top: `${y / DH * 100}%`,
                    width: 9, height: 9, marginLeft: -4.5, marginTop: -4.5, borderRadius: '50%',
                    background: 'var(--err)', border: '1.5px solid #fff', pointerEvents: 'none',
                  }} />
                ))}
              </div>
            ) : (
              <div className="hint" style={{ textAlign: 'center', padding: 24 }}>
                测距未开启 —— 深度画面未加载<br />
                <span style={{ fontSize: 11 }}>开启后才拉取画面流（节省资源）</span>
              </div>
            )}
          </div>
          <div style={{ marginTop: 'auto', paddingTop: 10 }}>
            <div className="row">
              <button className={`btn${measureOn ? '' : ' primary'}`}
                onClick={() => { setMeasureOn(v => !v); setPts([]); setDist('') }}>
                {measureOn ? '关闭测距' : '开启测距'}
              </button>
              <span className="hint" style={{ fontSize: 13, color: 'var(--fg)' }}>
                测量结果：<b style={{ color: 'var(--accent)' }}>{dist || '（点两点开始）'}</b>
              </span>
            </div>
          </div>
        </div>

        {/* 显示设置 */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3>深度显示范围</h3>
          <div className="hint" style={{ marginBottom: 8 }}>调整采集页深度画面的色带范围（shift 单位）。</div>
          <div className="field"><label>最小 (shift)</label><input type="text" value={lo} onChange={e => setLo(e.target.value)} style={{ width: 90 }} /></div>
          <div className="field"><label>最大 (shift)</label><input type="text" value={hi} onChange={e => setHi(e.target.value)} style={{ width: 90 }} /></div>
          <div style={{ marginTop: 'auto', paddingTop: 10 }}>
            <button className="btn primary" onClick={applyRange}>应用范围</button>
            <div className="hint" style={{ marginTop: 9 }}>默认 0–2500（约 0–2.5 米，视标定值而定）。</div>
          </div>
        </div>

        {/* 诊断 */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
          <h3>诊断与反馈</h3>
          <div className="hint" style={{ marginBottom: 8 }}>
            遇到问题先复制诊断信息：包含系统、设备、模块版本、运行日志，粘贴给开发者或 AI（DSH / WorkBuddy / GPT）可快速定位。
          </div>
          <div style={{ marginTop: 'auto', paddingTop: 10 }}>
            <div className="row">
              <button className="btn" onClick={copyDiag}>⧉ 复制诊断信息</button>
              <button className="btn" onClick={() => app.setPage('about')}>反馈通道</button>
            </div>
            <div className="hint" style={{ marginTop: 9 }}>驱动装不上/设备异常时，诊断信息里已含 USB 与流状态。</div>
          </div>
        </div>
      </div>
    </div>
  )
}
