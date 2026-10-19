import { useState } from 'react'
import {
  FolderOpen, Gauge, Cpu, Sun, Moon, Monitor, RotateCcw, HardDrive,
  SlidersHorizontal, Check, AlertTriangle,
} from 'lucide-react'
import { Btn, Field, Stat, Section, Modal } from '../components.jsx'

export default function SettingsPage({ state, setState, toast }) {
  const { settings } = state
  const [turboOpen, setTurboOpen] = useState(false)
  const [dir, setDir] = useState(settings.exportDir)

  const patchSettings = (p) => setState((s) => ({ ...s, settings: { ...s.settings, ...p } }))

  const applyTheme = (theme) => {
    document.documentElement.dataset.theme = theme
    setState((s) => ({ ...s, theme, settings: { ...s.settings, theme } }))
  }

  const applyDir = () => {
    if (!dir.trim()) { toast('目录不能为空'); return }
    patchSettings({ exportDir: dir.trim() })
    toast(`导出目录已保存：${dir.trim()}`)
  }

  const choosePerf = (perf) => {
    if (perf === 'turbo') { setTurboOpen(true); return }
    patchSettings({ perf })
    toast(`性能模式已切换：${perf === 'std' ? '标准' : '性能'}`)
  }

  const reset = () => {
    setState((s) => ({
      ...s,
      settings: { ...s.settings, exportDir: 'D:\\AstraForge\\扫描输出', perf: 'std', exposure: '自动', resolution: '640 × 480' },
    }))
    setDir('D:\\AstraForge\\扫描输出')
    toast('设置已恢复默认（复刻台）')
  }

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
          <Field label="导出目录" hint="所有快照、点云、转台、融合产物都写入这里">
            <input value={dir} onChange={(e) => setDir(e.target.value)} className="af-mono" />
          </Field>
          <div className="af-row">
            <Btn icon={FolderOpen} onClick={() => toast('打开导出目录（复刻台）')}>打开目录</Btn>
            <Btn primary icon={Check} onClick={applyDir}>应用</Btn>
          </div>
        </Section>

        <Section title="性能" aside={<Gauge size={15} />}>
          <div className="af-perf-list">
            {[
              ['std', '标准', 'CPU 保留 1 核 · 不用 GPU', '边用电脑边扫描'],
              ['perf', '性能', 'CPU 保留 1 核 · GPU 加速', '融合更快'],
              ['turbo', '狂暴', '全部 CPU + GPU 满功率', '需要确认免责'],
            ].map(([id, name, desc, hint]) => (
              <button key={id} className={`af-choice ${settings.perf === id ? 'active' : ''}`} onClick={() => choosePerf(id)}>
                <span className="af-choice-radio" />
                <span className="af-choice-copy"><b>{name}</b><small>{desc}</small></span>
                <span className="af-choice-hint">{hint}</span>
              </button>
            ))}
          </div>
          <div className="af-hint">本机：{8} 核 / 无 NVIDIA（复刻台示例）</div>
        </Section>

        <Section title="外观" aside={<Sun size={15} />}>
          <Field label="主题" hint="唯一主题入口；顶栏不再重复">
            <div className="af-segmented">
              <button className={settings.theme === 'light' ? 'active' : ''} onClick={() => applyTheme('light')}><Sun size={13} /> 浅色</button>
              <button className={settings.theme === 'dark' ? 'active' : ''} onClick={() => applyTheme('dark')}><Moon size={13} /> 深色</button>
              <button className={settings.theme === 'auto' ? 'active' : ''} onClick={() => applyTheme('auto')}><Monitor size={13} /> 跟随系统</button>
            </div>
          </Field>
          <div className="af-note">镜像、显示范围、质量叠加在三维扫描的视图工具条里，不在这里重复。</div>
        </Section>

        <Section title="设备显示" aside={<SlidersHorizontal size={15} />}>
          <Field label="RGB 曝光" hint="负值为手动；设备不支持时无效">
            <select value={settings.exposure} onChange={(e) => patchSettings({ exposure: e.target.value })}>
              <option>自动</option><option>-1</option><option>-2</option><option>-3</option>
            </select>
          </Field>
          <Field label="RGB 分辨率" hint="切换后需要重新连接彩色流">
            <select value={settings.resolution} onChange={(e) => patchSettings({ resolution: e.target.value })}>
              <option>640 × 480</option><option>1280 × 800</option>
            </select>
          </Field>
          <div className="af-note">这两个是旧 Tk 设置里的功能，是否保留待定；复刻台先按保留展示。</div>
        </Section>

        <Section title="高级" className="af-span-2" aside={<Cpu size={15} />}>
          <div className="af-row">
            <Btn icon={RotateCcw} onClick={reset}>恢复默认设置</Btn>
            <Btn icon={FolderOpen} onClick={() => toast('打开日志目录（复刻台）')}>打开日志目录</Btn>
            <span className="af-hint">诊断与反馈统一在「关于与更新」。</span>
          </div>
        </Section>
      </div>

      {turboOpen ? (
        <Modal title="狂暴模式 · 免责声明" onClose={() => setTurboOpen(false)}>
          <div className="af-warning">
            <AlertTriangle size={18} />
            <p>狂暴模式会使用全部 CPU 核心与显卡满功率算力，可能导致系统卡顿、发热、风扇噪音、电池快速耗尽。建议插电使用，期间不要处理重要工作。</p>
          </div>
          <div className="af-modal-actions">
            <Btn onClick={() => setTurboOpen(false)}>取消</Btn>
            <Btn danger onClick={() => { setTurboOpen(false); patchSettings({ perf: 'turbo' }); toast('狂暴模式已开启（复刻台）') }}>我已知晓，开启</Btn>
          </div>
        </Modal>
      ) : null}
    </div>
  )
}
