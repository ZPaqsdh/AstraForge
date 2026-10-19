import { useEffect, useState } from 'react'
import {
  FolderOpen, Gauge, Cpu, Sun, Moon, Monitor, RotateCcw, HardDrive,
  SlidersHorizontal, Check, AlertTriangle, FileText,
} from 'lucide-react'
import { Btn, Field, Section, Modal } from '../ui.jsx'
import { api } from '../api.js'

export default function SettingsPage({ app }) {
  const { showToast, theme, setTheme } = app
  const [s, setS] = useState(null)
  const [paths, setPaths] = useState(null)
  const [dir, setDir] = useState('')
  const [range, setRange] = useState({ lo: '0', hi: '2500' })
  const [busy, setBusy] = useState(false)
  const [turboOpen, setTurboOpen] = useState(false)

  const load = async () => {
    try {
      const v = await api.settings()
      setS(v)
      setDir(v.export_dir || '')
      setRange({ lo: String(v.disp_range?.[0] ?? 0), hi: String(v.disp_range?.[1] ?? 2500) })
    } catch (e) {
      showToast(`✗ 读取设置失败：${e.message || e}`)
    }
  }

  useEffect(() => {
    load()
    api.paths().then(setPaths).catch(() => {})
  }, [])

  const applyDir = async () => {
    if (!dir.trim()) { showToast('目录不能为空'); return }
    setBusy(true)
    try {
      const r = await api.setExportDir(dir.trim())
      if (r && r.ok === false) throw new Error(r.error || '保存失败')
      showToast(`✓ 导出目录已保存：${dir.trim()}`, 4200)
      load()
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4200)
    } finally {
      setBusy(false)
    }
  }

  const choosePerf = async (mode) => {
    if (mode === 'turbo') { setTurboOpen(true); return }
    await applyPerf(mode)
  }

  const applyPerf = async (mode) => {
    try {
      const r = await api.setPerfMode(mode)
      if (r && r.ok === false) throw new Error(r.error || '切换失败')
      showToast(`✓ 性能模式：${mode === 'std' ? '标准' : '性能'}`)
      load()
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4200)
    }
  }

  const applyRange = async () => {
    setBusy(true)
    try {
      await api.setDispRange(Number(range.lo) || 0, Number(range.hi) || 2500)
      showToast(`✓ 显示范围：${range.lo}–${range.hi}`)
      load()
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  const reset = async () => {
    setBusy(true)
    try {
      await api.setPerfMode('std')
      await api.setDispRange(0, 2500)
      setTheme('light')
      setRange({ lo: '0', hi: '2500' })
      showToast('✓ 已恢复默认：标准性能 / 显示范围 0–2500 / 浅色主题')
      load()
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    } finally {
      setBusy(false)
    }
  }

  const perf = s?.perf_mode || 'std'
  const gpu = s?.gpu || {}
  const cores = s?.cpu_cores || 0

  return (
    <div className="af-page af-settings">
      <header className="af-page-head">
        <div>
          <h1>设置</h1>
          <p>只放长期生效的默认值；临时视图操作在三维扫描的视图工具条里</p>
        </div>
      </header>

      <div className="af-settings-grid">
        <Section title="导出" aside={<HardDrive size={15} />}>
          <Field label="导出目录" hint="快照、点云、转台/手持会话、融合产物都写入这里">
            <input value={dir} onChange={(e) => setDir(e.target.value)} className="af-mono"
              placeholder="例如 D:\AstraForge\扫描输出" />
          </Field>
          <div className="af-row">
            <Btn icon={FolderOpen} disabled={!dir}
              onClick={() => api.openDir(dir).catch((e) => showToast(e.message))}>打开目录</Btn>
            <Btn primary icon={Check} disabled={busy} onClick={applyDir}>应用</Btn>
          </div>
          <div className="af-note">切换目录后新采集写入新位置；已有会话仍在原目录。</div>
        </Section>

        <Section title="性能" aside={<Gauge size={15} />}>
          <div className="af-perf-list">
            {[
              ['std', '标准', 'CPU 保留 1 核 · 不用 GPU', '边用电脑边扫描'],
              ['perf', '性能', 'CPU 保留 1 核 · GPU 加速', '融合更快'],
              ['turbo', '狂暴', '全部 CPU + GPU 满功率', '需要确认免责'],
            ].map(([id, name, desc, hint]) => (
              <button key={id} className={`af-choice ${perf === id ? 'active' : ''}`}
                onClick={() => choosePerf(id)}>
                <span className="af-choice-radio" />
                <span className="af-choice-copy"><b>{name}</b><small>{desc}</small></span>
                <span className="af-choice-hint">{hint}</span>
              </button>
            ))}
          </div>
          <div className="af-hint">
            本机：{cores} 核 / {gpu.cuda ? 'CUDA 可用' : (gpu.name || '未检测到 NVIDIA')}
          </div>
        </Section>

        <Section title="外观" aside={<Sun size={15} />}>
          <Field label="主题" hint="全应用唯一主题入口">
            <div className="af-segmented">
              <button className={theme === 'light' ? 'active' : ''} onClick={() => setTheme('light')}>
                <Sun size={13} /> 浅色</button>
              <button className={theme === 'dark' ? 'active' : ''} onClick={() => setTheme('dark')}>
                <Moon size={13} /> 深色</button>
              <button className={theme === 'auto' ? 'active' : ''} onClick={() => setTheme('auto')}>
                <Monitor size={13} /> 跟随系统</button>
            </div>
          </Field>
          <div className="af-note">镜像、深度灰度、暂停、显示范围在三维扫描的视图工具条里，不在这里重复。</div>
        </Section>

        <Section title="深度显示" aside={<SlidersHorizontal size={15} />}>
          <div className="af-inline-2">
            <Field label="最小色带值"><input value={range.lo}
              onChange={(e) => setRange({ ...range, lo: e.target.value })} /></Field>
            <Field label="最大色带值"><input value={range.hi}
              onChange={(e) => setRange({ ...range, hi: e.target.value })} /></Field>
          </div>
          <div className="af-row">
            <Btn icon={RotateCcw} onClick={() => setRange({ lo: '0', hi: '2500' })}>重置 0–2500</Btn>
            <Btn primary icon={Check} disabled={busy} onClick={applyRange}>应用</Btn>
          </div>
          <div className="af-note">只影响预览色带，不改变采集数据与导出文件。</div>
        </Section>

        <Section title="高级" className="af-span-2" aside={<Cpu size={15} />}>
          <div className="af-row wrap">
            <Btn icon={RotateCcw} disabled={busy} onClick={reset}>恢复默认设置</Btn>
            <Btn icon={FolderOpen} disabled={!paths?.root}
              onClick={() => api.openDir(paths.root).catch((e) => showToast(e.message))}>打开程序目录</Btn>
            <Btn icon={FileText} disabled={!paths?.log}
              onClick={() => api.openDir(paths.log).catch((e) => showToast(e.message))}>打开日志文件</Btn>
          </div>
          <div className="af-kv" style={{ marginTop: 8 }}>
            <span>程序目录</span>
            <b className="af-mono ellipsis" title={paths?.root}>{paths?.root || '—'}</b>
          </div>
          <div className="af-kv">
            <span>Python</span><b className="af-mono">{paths?.python || '—'}</b>
          </div>
          <div className="af-hint">诊断、更新日志与反馈统一在「关于与更新」。</div>
        </Section>
      </div>

      {turboOpen ? (
        <Modal title="狂暴模式 · 免责声明" onClose={() => setTurboOpen(false)}>
          <div className="af-warning">
            <AlertTriangle size={18} />
            <p>狂暴模式会使用全部 CPU 核心与显卡满功率算力，可能导致系统卡顿、发热、风扇噪音、
              电池快速耗尽。建议插电使用，期间不要处理重要工作。</p>
          </div>
          <div className="af-modal-actions">
            <Btn onClick={() => setTurboOpen(false)}>取消</Btn>
            <Btn danger onClick={async () => {
              setTurboOpen(false)
              await applyPerf('turbo')
            }}>我已知晓，开启</Btn>
          </div>
        </Modal>
      ) : null}
    </div>
  )
}
