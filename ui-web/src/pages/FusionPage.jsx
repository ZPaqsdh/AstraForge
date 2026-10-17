import { useEffect, useState } from 'react'
import PageIntro from '../components/PageIntro.jsx'
import { api } from '../api.js'
import { usePoll } from '../hooks.jsx'

const STAGES = { read: '读帧+点云', icp: 'ICP 位姿精修', fuse: '体素融合', mesh: '网格化', done: '完成' }

export default function FusionPage({ app }) {
  const { showToast } = app
  const [dirs, setDirs] = useState([])
  const [sel, setSel] = useState('')
  const [prog, setProg] = useState(null)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)

  const loadDirs = () => api.listDirs().then(r => {
    setDirs(r.dirs || [])
    if (r.dirs && r.dirs.length && !sel) setSel(r.dirs[0].path)
  }).catch(() => {})

  useEffect(() => { loadDirs() }, [])

  // 进度轮询（任务运行中 1s 一次）
  useEffect(() => {
    if (!running) return
    const id = setInterval(async () => {
      try {
        const p = await api.fuseProgress()
        setProg(p)
        if (p.done || p.error) {
          setRunning(false)
          if (p.error && p.error !== '已取消') {
            showToast(`✗ 融合失败: ${p.error}`, 5000)
          } else if (p.done) {
            showToast(`✓ 融合完成 → ${p.out_dir}`, 5000)
            setResult(p.out_dir)
          }
        }
      } catch { /* 后端未就绪 */ }
    }, 1000)
    return () => clearInterval(id)
  }, [running])

  const start = async () => {
    if (!sel) { showToast('请先选择采集目录'); return }
    const d = dirs.find(x => x.path === sel)
    if (d && d.frames < 2) {
      showToast(`「${d.name}」只有 ${d.frames} 帧（至少 2 帧才能融合）——请重新采集一整圈`, 5200)
      return
    }
    setRunning(true); setResult(null)
    try {
      const r = await api.fuse(sel)
      if (!r.ok) { showToast(`✗ ${r.error}`); setRunning(false) }
      else showToast('融合任务已启动（后台运行，可切换页面）')
    } catch (e) { showToast(`✗ ${e.message}`); setRunning(false) }
  }

  const pct = prog ? Math.round((prog.pct || 0) * 100) : 0

  return (
    <div className="fade-in page-grid">
      <PageIntro id="fusion">
        <b>融合</b>：把转台拍的一圈帧拼成完整 3D 模型。选转台目录 → 点「开始融合」→ 进度走完得到 STL（可打印）+ PLY（彩色点云）。融合后台运行，可随时切去别的页面。
      </PageIntro>
      <div className="layout-side">
        <div className="side-col">
          <div className="card">
            <h3>选择采集目录</h3>
            {dirs.length === 0 ? (
              <div>
                <div className="hint" style={{ marginBottom: 10, color: 'var(--fg)' }}>
                  <b>还没有可融合的数据。</b>融合需要一整圈采集，两种方式产生：
                </div>
                <div className="hint" style={{ marginBottom: 10 }}>
                  1）<b>转台</b>：每转一格拍一帧，转满一圈后点「完成采集」<br />
                  2）<b>3D 扫描</b>：点「开始记录」，缓慢绕物体一圈后停止
                </div>
                <div className="row">
                  <button className="btn primary" onClick={() => app.setPage('turntable')}>去转台采集</button>
                  <button className="btn" onClick={() => app.setPage('scan3d')}>去 3D 扫描</button>
                  <button className="btn" onClick={loadDirs}>刷新列表</button>
                </div>
              </div>
            ) : (
              <>
            <div className="field">
              <select value={sel} onChange={e => setSel(e.target.value)} style={{ flex: 1, minWidth: 0 }}>
                {dirs.map(d => (
                  <option key={d.path} value={d.path}>
                    {d.name}（{d.frames} 帧{d.frames < 2 ? ' · 不足，需重采' : ''}）
                  </option>
                ))}
              </select>
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn" onClick={loadDirs}>刷新列表</button>
            </div>
              </>
            )}
            <button className="btn primary wide" style={{ marginTop: 10 }}
              disabled={running || !sel} onClick={start}>
              {running ? '融合进行中…' : '开始融合'}
            </button>
            {running && (
              <button className="btn wide" style={{ marginTop: 8 }}
                onClick={async () => { await api.fuseCancel().catch(() => {}); showToast('已请求取消（当前阶段完成后停止）') }}>
                取消融合
              </button>
            )}
          </div>
          <div className="card">
            <h3>进度</h3>
            <div className="progress"><div style={{ width: `${pct}%`, transition: 'width .3s' }} /></div>
            <div className="stat"><span className="k">阶段</span><span className="v">{prog && prog.stage ? (STAGES[prog.stage] || prog.stage) : '空闲'}</span></div>
            <div className="stat"><span className="k">进度</span><span className="v">{pct}%</span></div>
            <div className="hint" style={{ marginTop: 6, wordBreak: 'break-all' }}>{prog && prog.msg ? prog.msg : '（未开始）'}</div>
          </div>
        </div>
        <div style={{ display: 'grid', gap: 12, alignContent: 'start' }}>
          <div className="card">
            <h3>产物</h3>
            {!result && <div className="hint">融合完成后，产物会出现在所选目录内：</div>}
            {result && <div className="hint" style={{ color: 'var(--ok)' }}>✓ 已完成 → {result}</div>}
            <div className="stat"><span className="k">fused_points.ply</span><span className="v">彩色点云</span></div>
            <div className="stat"><span className="k">fused_mesh.stl</span><span className="v">可打印网格</span></div>
            <div className="stat"><span className="k">fused_preview.png</span><span className="v">明暗预览</span></div>
            <div className="row" style={{ marginTop: 9 }}>
              <button className="btn" disabled={!result}
                onClick={() => api.openDir(result || sel).catch(e => showToast(e.message))}>打开目录</button>
              <button className="btn" disabled={!result}
                onClick={() => showToast('提示：STL 可直接进切片软件（PrusaSlicer/Orca）打印')}>拿去打印</button>
            </div>
          </div>
          <div className="card">
            <h3>性能说明</h3>
            <div className="hint">
              融合为 CPU 多进程并行（读帧阶段并行，ICP 串行精修）。worker 数随性能模式变化：标准/性能 = 核数−1（保留 1 核给系统），狂暴 = 全核。NVIDIA 显卡 + cuPy 可启用 GPU 加速（性能模式自动检测）。
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
