import { useEffect } from 'react'
import {
  Boxes, Play, Square, FolderOpen, Check, AlertTriangle, FileText, Layers,
  RefreshCw, ChevronRight, ScanLine, Clock, Box,
} from 'lucide-react'
import { Btn, Stat, Section, StepBar } from '../components.jsx'
import { STAGES } from '../state.js'
import fusedUrl from '../assets/fused.svg'

function SessionRow({ s, active, onClick }) {
  return (
    <button className={`af-session ${active ? 'active' : ''}`} onClick={onClick}>
      <img src={s.thumb} alt="" />
      <span className="af-session-copy">
        <b>{s.name}</b>
        <small>{s.type} · {s.frames} 帧 · {s.coverage}°</small>
        <small className="af-session-date">{s.date}</small>
      </span>
      {active ? <ChevronRight size={14} /> : null}
    </button>
  )
}

function StageList({ stage, running, error }) {
  return (
    <div className="af-stage-list">
      {STAGES.map((name, i) => {
        const state = error && i === stage ? 'error' : i < stage ? 'done' : i === stage && running ? 'active' : i === stage && stage === 4 ? 'done' : 'pending'
        return (
          <div key={name} className={`af-stage ${state}`}>
            <span className="af-stage-dot">{state === 'done' ? <Check size={11} /> : state === 'error' ? <AlertTriangle size={11} /> : i + 1}</span>
            <span>{name}</span>
            {state === 'active' ? <span className="af-stage-now">进行中</span> : null}
          </div>
        )
      })}
    </div>
  )
}

export default function FusionPage({ state, setState, toast, setPage }) {
  const { fusion, sessions } = state
  const selected = sessions.find((s) => s.id === fusion.selected) || sessions[0]
  const running = fusion.running
  const result = fusion.result

  useEffect(() => {
    if (!running) return
    const id = setInterval(() => {
      setState((s) => {
        const pct = Math.min(100, s.fusion.pct + 4)
        const stage = pct < 25 ? 0 : pct < 55 ? 1 : pct < 80 ? 2 : pct < 99 ? 3 : 4
        if (pct >= 100) {
          const sel = s.sessions.find((x) => x.id === s.fusion.selected)
          return {
            ...s,
            fusion: { ...s.fusion, running: false, pct: 100, stage: 4, result: sel ? `${sel.name}/fused_points.ply` : 'fused_points.ply' },
            sessions: s.sessions.map((x) => x.id === s.fusion.selected
              ? { ...x, artifacts: ['fused_points.ply', 'fused_mesh.stl', 'fused_preview.png'] }
              : x),
            logs: [...s.logs.slice(-19), { t: new Date().toTimeString().slice(0, 8), text: '融合完成：fused_points.ply / fused_mesh.stl', ok: true }],
          }
        }
        return { ...s, fusion: { ...s.fusion, pct, stage } }
      })
    }, 180)
    return () => clearInterval(id)
  }, [running])

  const patch = (fn) => setState((s) => fn(s))

  const selectSession = (id) => {
    patch((s) => ({ ...s, fusion: { ...s.fusion, selected: id, result: null, pct: 0, stage: 0, error: null } }))
  }

  const start = () => {
    if (!selected) { toast('先选择一个采集会话'); return }
    if (selected.frames < 2) { toast('这个会话少于 2 帧，需要重新采集'); return }
    patch((s) => ({ ...s, fusion: { ...s.fusion, running: true, pct: 0, stage: 0, result: null, error: null } }))
    toast('融合任务已启动，可切到其他页面')
  }

  const cancel = () => {
    patch((s) => ({ ...s, fusion: { ...s.fusion, running: false, pct: 0, stage: 0 } }))
    toast('已请求取消（当前阶段完成后停止）')
  }

  const artifacts = selected?.artifacts?.length ? selected.artifacts : (result ? ['fused_points.ply', 'fused_mesh.stl', 'fused_preview.png'] : [])
  const activeStep = result ? 2 : running ? 1 : 0

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
            <div><h3>采集会话</h3><span>{sessions.length} 个</span></div>
            <button className="af-icon-btn" title="刷新列表" onClick={() => toast('会话列表已刷新')}><RefreshCw size={14} /></button>
          </div>
          <div className="af-session-list">
            {sessions.length === 0 ? (
              <div className="af-empty-small">还没有采集会话</div>
            ) : sessions.map((s) => (
              <SessionRow key={s.id} s={s} active={s.id === fusion.selected} onClick={() => selectSession(s.id)} />
            ))}
          </div>
          <div className="af-session-foot">
            <Btn small icon={ScanLine} onClick={() => setPage('scan')}>新建采集</Btn>
          </div>
        </aside>

        <section className="af-canvas-panel">
          <div className="af-canvas-head">
            <div>
              <span className="af-canvas-title">{selected ? selected.name : '未选择会话'}</span>
              {selected ? <span className="af-canvas-meta">{selected.frames} 帧 · {selected.coverage}° · {selected.type}</span> : null}
            </div>
            {result ? <span className="af-pill ok">已完成</span> : running ? <span className="af-pill">融合中 {Math.round(fusion.pct)}%</span> : <span className="af-pill">待融合</span>}
          </div>
          <div className="af-canvas">
            {result ? (
              <>
                <img src={fusedUrl} alt="融合预览" />
                <div className="af-canvas-caption"><Layers size={14} /> fused_preview.png</div>
              </>
            ) : running ? (
              <div className="af-canvas-progress">
                <div className="af-ring" style={{ '--p': `${fusion.pct}%` }}>
                  <span>{Math.round(fusion.pct)}%</span>
                </div>
                <b>{STAGES[fusion.stage] || '准备中'}</b>
                <small>融合在后台运行，可以切到其他页面</small>
              </div>
            ) : (
              <div className="af-canvas-empty">
                {selected ? <img src={selected.thumb} alt="" /> : <Box size={34} />}
                <b>{selected ? '准备融合' : '先选择一个采集会话'}</b>
                <small>选中左侧会话，点右侧「开始融合」</small>
              </div>
            )}
          </div>
          <div className="af-artifacts">
            <div className="af-artifacts-head"><FileText size={14} /><b>产物</b><span>{artifacts.length ? `${artifacts.length} 个文件` : '融合完成后生成'}</span></div>
            <div className="af-artifact-list">
              {artifacts.length ? artifacts.map((a) => (
                <button key={a} className="af-artifact" onClick={() => toast(`打开 ${a}（复刻台）`)}>
                  <span className="af-file-icon">{a.endsWith('.stl') ? <Box size={14} /> : a.endsWith('.png') ? <Layers size={14} /> : <FileText size={14} />}</span>
                  <b>{a}</b>
                  <small>{a.endsWith('.stl') ? '网格' : a.endsWith('.png') ? '预览' : '点云'}</small>
                  <ChevronRight size={13} />
                </button>
              )) : <span className="af-empty-inline">还没有产物</span>}
            </div>
            <div className="af-artifacts-actions">
              <Btn small icon={FolderOpen} disabled={!artifacts.length} onClick={() => toast('打开产物目录（复刻台）')}>打开目录</Btn>
            </div>
          </div>
        </section>

        <aside className="af-fusion-panel">
          <Section title="融合" aside={<span className={`af-pill ${running ? 'rec' : result ? 'ok' : ''}`}>{running ? 'RUN' : result ? 'DONE' : 'READY'}</span>}>
            <div className="af-kv"><span>输入</span><b className="ellipsis">{selected ? selected.frames : 0} 帧</b></div>
            <div className="af-kv"><span>覆盖</span><b>{selected ? selected.coverage : 0}°</b></div>
            <div className="af-kv"><span>策略</span><b>体素 1.5 mm</b></div>
            <div className="af-kv"><span>ICP</span><b>10 次精修</b></div>
            <div className="af-kv"><span>网格</span><b>柱面展开 → STL</b></div>
            <div className="af-divider" />
            {running ? (
              <Btn danger icon={Square} onClick={cancel} wide>取消融合</Btn>
            ) : (
              <Btn primary icon={Play} onClick={start} disabled={!selected || selected.frames < 2} wide>{result ? '重新融合' : '开始融合'}</Btn>
            )}
            <div className="af-hint">融合为 CPU 多进程；标准模式保留 1 核给系统。进度在后台推进。</div>
          </Section>
          <Section title="阶段" aside={<span className="af-mono">{Math.round(fusion.pct)}%</span>}>
            <div className="af-bar"><span style={{ width: `${fusion.pct}%` }} /></div>
            <StageList stage={fusion.stage} running={running} error={fusion.error} />
            <div className="af-hint"><Clock size={12} /> {running ? '预计 30–90 秒' : result ? '已完成' : '未开始'}</div>
          </Section>
        </aside>
      </div>
    </div>
  )
}
