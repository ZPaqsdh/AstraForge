import { useEffect, useMemo, useState } from 'react'
import {
  Play, Square, FolderOpen, Check, AlertTriangle, FileText, Layers,
  RefreshCw, ChevronRight, ScanLine, Clock, Box,
} from 'lucide-react'
import { Btn, Section, StepBar, Pill } from '../ui.jsx'
import { api } from '../api.js'

const STAGES = ['读取帧 + 点云', 'ICP 位姿精修', '体素融合', '网格化', '完成']
const STAGE_INDEX = { read: 0, icp: 1, fuse: 2, mesh: 3, done: 4 }

function fmtSize(n) {
  if (!n) return ''
  if (n > 1024 * 1024) return `${(n / 1048576).toFixed(1)} MB`
  return `${Math.max(1, Math.round(n / 1024))} KB`
}

function SessionRow({ s, active, onClick }) {
  return (
    <button className={`af-session ${active ? 'active' : ''}`} onClick={onClick}>
      {s.preview
        ? <img src={api.artifactUrl(s.preview)} alt="" />
        : <span className="af-session-thumb"><Layers size={16} /></span>}
      <span className="af-session-copy">
        <b>{s.name}</b>
        <small>{s.type === 'turntable' ? '转台' : '手持'} · {s.frames} 帧
          {s.type === 'turntable' && s.coverage ? ` · ${s.coverage}°` : ''}</small>
        <small className="af-session-date">{s.date}{s.fused ? ' · 已融合' : ''}</small>
      </span>
      {active ? <ChevronRight size={14} /> : null}
    </button>
  )
}

function StageList({ stage, running, error }) {
  return (
    <div className="af-stage-list">
      {STAGES.map((name, i) => {
        const state = error && i === stage ? 'error' : i < stage ? 'done'
          : i === stage && running ? 'active' : i === stage && stage === 4 ? 'done' : 'pending'
        return (
          <div key={name} className={`af-stage ${state}`}>
            <span className="af-stage-dot">
              {state === 'done' ? <Check size={11} />
                : state === 'error' ? <AlertTriangle size={11} /> : i + 1}
            </span>
            <span>{name}</span>
            {state === 'active' ? <span className="af-stage-now">进行中</span> : null}
          </div>
        )
      })}
    </div>
  )
}

export default function FusionPage({ app }) {
  const { showToast, setPage } = app
  const [data, setData] = useState({ dirs: [], base: '' })
  const [selected, setSelected] = useState('')
  const [running, setRunning] = useState(false)
  const [prog, setProg] = useState({ stage: '', pct: 0, msg: '', done: false, error: null })
  const [loading, setLoading] = useState(false)

  const load = async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const d = await api.listDirs()
      setData(d)
      setSelected((cur) => (d.dirs.some((x) => x.path === cur) ? cur : (d.dirs[0]?.path || '')))
      return d
    } catch (e) {
      if (!silent) showToast(`✗ 读取会话失败：${e.message || e}`)
      return null
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  // 融合进度轮询（运行中读取，done/error 落地后收尾并刷新会话）
  useEffect(() => {
    if (!running) return
    let alive = true
    const tick = async () => {
      try {
        const p = await api.fuseProgress()
        if (!alive) return
        setProg(p)
        if (p.done) {
          setRunning(false)
          if (p.error) showToast(`✗ 融合失败：${p.error}`, 5000)
          else showToast('✓ 融合完成，产物已写入会话目录', 4500)
          load(true)
        }
      } catch (e) {
        if (alive) {
          setRunning(false)
          showToast(`✗ 读取融合进度失败：${e.message || e}`)
        }
      }
    }
    tick()
    const id = setInterval(tick, 800)
    return () => { alive = false; clearInterval(id) }
  }, [running])

  const session = useMemo(
    () => data.dirs.find((x) => x.path === selected) || data.dirs[0] || null,
    [data, selected],
  )

  const start = async () => {
    if (!session) { showToast('先选择一个采集会话'); return }
    if (session.frames < 2) { showToast('这个会话少于 2 帧，需要重新采集'); return }
    try {
      const r = await api.fuse(session.path)
      if (!r.ok) throw new Error(r.error || '融合启动失败')
      setProg({ stage: 'read', pct: 0, msg: '启动中…', done: false, error: null })
      setRunning(true)
      showToast('融合任务已启动，可切换到其他页面')
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4500)
    }
  }

  const cancel = async () => {
    try {
      await api.fuseCancel()
      showToast('已请求取消（当前阶段完成后停止）')
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    }
  }

  const openArtifact = async (a) => {
    try {
      const r = await api.openDir(a.path)
      if (r && r.ok === false) throw new Error(r.error || '打开失败')
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    }
  }

  const pct = Math.round((prog.pct || 0) * 100)
  const stage = STAGE_INDEX[prog.stage] ?? 0
  const showPct = running ? pct : (session?.fused ? 100 : 0)
  const showStage = running ? stage : (session?.fused ? 4 : 0)
  const artifacts = session?.artifacts || []
  const activeStep = session?.fused ? 2 : running ? 1 : 0

  return (
    <div className="af-page af-fusion">
      <header className="af-page-head">
        <div>
          <h1>融合工作台</h1>
          <p>选一整个采集会话，融合成完整模型；进度、阶段、产物都在这一页</p>
        </div>
        <StepBar active={activeStep} />
      </header>

      <div className="af-fusion-grid">
        <aside className="af-session-panel">
          <div className="af-panel-head">
            <div><h3>采集会话</h3><span>{data.dirs.length} 个</span></div>
            <button className="af-icon-btn" title="刷新列表" onClick={() => load()}>
              <RefreshCw size={14} className={loading ? 'af-spin' : ''} />
            </button>
          </div>
          <div className="af-session-list">
            {data.dirs.length === 0 ? (
              <div className="af-empty-small">还没有采集会话</div>
            ) : data.dirs.map((s) => (
              <SessionRow key={s.path} s={s} active={s.path === selected}
                onClick={() => setSelected(s.path)} />
            ))}
          </div>
          <div className="af-session-foot">
            <Btn small icon={ScanLine} onClick={() => setPage('scan')}>新建采集</Btn>
          </div>
        </aside>

        <section className="af-canvas-panel">
          <div className="af-canvas-head">
            <div>
              <span className="af-canvas-title">{session ? session.name : '未选择会话'}</span>
              {session ? (
                <span className="af-canvas-meta">
                  {session.frames} 帧 · {session.type === 'turntable' ? `转台 ${session.coverage}°` : '手持'} · {session.date}
                </span>
              ) : null}
            </div>
            {running ? <Pill>融合中 {pct}%</Pill>
              : prog.error ? <Pill tone="err">失败</Pill>
                : session?.fused ? <Pill tone="ok">已完成</Pill>
                  : <Pill>待融合</Pill>}
          </div>

          <div className="af-canvas">
            {running ? (
              <div className="af-canvas-progress">
                <div className="af-ring" style={{ '--p': `${pct}%` }}><span>{pct}%</span></div>
                <b>{STAGES[stage] || '准备中'}</b>
                <small>{prog.msg || '融合在后台运行，可以切到其他页面'}</small>
              </div>
            ) : session?.preview ? (
              <>
                <img src={api.artifactUrl(session.preview)} alt="融合预览" />
                <div className="af-canvas-caption"><Layers size={14} /> fused_preview.png</div>
              </>
            ) : (
              <div className="af-canvas-empty">
                <Box size={34} />
                <b>{session ? '准备融合' : '先选择一个采集会话'}</b>
                <small>{session ? '选中左侧会话，点右侧「开始融合」' : '点左下角「新建采集」'}</small>
              </div>
            )}
          </div>

          <div className="af-artifacts">
            <div className="af-artifacts-head">
              <FileText size={14} /><b>产物</b>
              <span>{artifacts.length ? `${artifacts.length} 个文件` : '融合完成后生成'}</span>
            </div>
            <div className="af-artifact-list">
              {artifacts.length ? artifacts.map((a) => (
                <button key={a.path} className="af-artifact" onClick={() => openArtifact(a)}>
                  <span className="af-file-icon">
                    {a.name.endsWith('.stl') ? <Box size={14} />
                      : a.name.endsWith('.png') ? <Layers size={14} /> : <FileText size={14} />}
                  </span>
                  <b>{a.name}</b>
                  <small>{fmtSize(a.size)}</small>
                  <ChevronRight size={13} />
                </button>
              )) : <span className="af-empty-inline">还没有产物</span>}
            </div>
            <div className="af-artifacts-actions">
              <Btn small icon={FolderOpen} disabled={!session}
                onClick={() => session && api.openDir(session.path).catch((e) => showToast(e.message))}>
                打开会话目录
              </Btn>
              <Btn small icon={FolderOpen} disabled={!data.base}
                onClick={() => data.base && api.openDir(data.base).catch((e) => showToast(e.message))}>
                打开导出目录
              </Btn>
            </div>
          </div>
        </section>

        <aside className="af-fusion-panel">
          <Section title="融合" aside={
            <Pill tone={running ? 'warn' : prog.error ? 'err' : session?.fused ? 'ok' : ''}>
              {running ? 'RUN' : prog.error ? 'ERR' : session?.fused ? 'DONE' : 'READY'}
            </Pill>}>
            <div className="af-kv"><span>输入</span><b>{session ? `${session.frames} 帧` : '—'}</b></div>
            <div className="af-kv"><span>类型</span>
              <b>{session ? (session.type === 'turntable' ? '转台（角度先验）' : '手持（ICP）') : '—'}</b></div>
            <div className="af-kv"><span>覆盖</span>
              <b>{session && session.type === 'turntable' ? `${session.coverage}°` : '—'}</b></div>
            <div className="af-kv"><span>策略</span><b>体素 1.5 mm</b></div>
            <div className="af-kv"><span>网格</span><b>柱面展开 → STL</b></div>
            <div className="af-divider" />
            {running ? (
              <Btn danger icon={Square} onClick={cancel} wide>取消融合</Btn>
            ) : (
              <Btn primary icon={Play} onClick={start}
                disabled={!session || session.frames < 2} wide>
                {session?.fused ? '重新融合' : '开始融合'}
              </Btn>
            )}
            <div className="af-hint">融合在后台多线程运行，可切页面；产物写入会话目录。</div>
          </Section>

          <Section title="阶段" aside={<span className="af-mono">{showPct}%</span>}>
            <div className="af-bar"><span style={{ width: `${showPct}%` }} /></div>
            <StageList stage={showStage} running={running} error={prog.error} />
            {prog.error ? (
              <div className="af-callout err"><AlertTriangle size={14} /> {prog.error}</div>
            ) : (
              <div className="af-hint"><Clock size={12} /> {running ? '预计 30–90 秒' : session?.fused ? '已完成' : '未开始'}</div>
            )}
          </Section>
        </aside>
      </div>
    </div>
  )
}
