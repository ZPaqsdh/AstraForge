import { useEffect, useRef, useState } from 'react'
import { FolderOpen } from 'lucide-react'
import PageIntro from '../components/PageIntro.jsx'
import { api } from '../api.js'
import { usePoll } from '../hooks.jsx'

export default function SettingsPage({ app }) {
  const { showToast, state } = app
  const [st] = usePoll(api.settings, 3000)
  const [exportDir, setExportDir] = useState('')
  const [perf, setPerf] = useState('std')
  const [turboOpen, setTurboOpen] = useState(false)
  const [flip, setFlip] = useState(true)   // 预览镜像（显示层）：默认开（首轮 state 到达后跟随后端持久化值）

  useEffect(() => {
    if (st) {
      if (st.export_dir && !exportDir) setExportDir(st.export_dir)
      if (st.perf_mode) setPerf(st.perf_mode)
    }
  }, [st])

  // 镜像开关一次性对齐（后端可能已从"设置.json"还原上次的选择）
  const flipSynced = useRef(false)
  useEffect(() => {
    if (!flipSynced.current && state && typeof state.preview_mirror === 'boolean') {
      flipSynced.current = true
      setFlip(state.preview_mirror)
    }
  }, [state])

  const cores = st?.cpu_cores || 4
  const gpu = st?.gpu || {}

  const perfDesc = {
    std: `标准：CPU 使用 ${Math.max(cores - 1, 1)} 核（共 ${cores} 核，始终留 1 核给系统）；不使用 GPU。边用电脑边扫描不卡。`,
    perf: `性能：CPU 保持保守（留 1 核，${Math.max(cores - 1, 1)} 核）+ 启用 GPU 加速。${gpu.name ? `已检测到 ${gpu.name}，融合可提速 5-10 倍。` : '未检测到 NVIDIA 显卡 —— 等效标准模式（AMD/Intel 暂走 CPU 多核）。'}`,
    turbo: '狂暴：全部 CPU 核心 + GPU 满功率。若电脑变卡请切回标准模式。',
  }

  const choosePerf = (m) => {
    if (m === 'turbo') { setTurboOpen(true); return }
    setPerf(m)
    api.setPerfMode(m).then(r => {
      if (r.ok) showToast(`✓ 性能模式 → ${m === 'std' ? '标准' : '性能'}（workers=${r.workers}）`)
    }).catch(e => showToast(`✗ ${e.message}`))
  }

  const confirmTurbo = () => {
    setTurboOpen(false)
    setPerf('turbo')
    api.setPerfMode('turbo').then(r => {
      if (r.ok) showToast(`狂暴模式已开启（免责已确认，workers=${r.workers}）`)
    }).catch(e => showToast(`✗ ${e.message}`))
  }

  const applyDir = async () => {
    if (!exportDir.trim()) { showToast('目录不能为空'); return }
    try {
      const r = await api.setExportDir(exportDir.trim())
      if (r.ok) showToast(`✓ 导出目录已保存: ${r.dir}`)
      else showToast(`✗ ${r.error}`)
    } catch (e) { showToast(`✗ ${e.message}`) }
  }

  return (
    <div className="fade-in page-grid">
      <PageIntro id="settings">
        <b>设置</b>：外观主题（深色/浅色/跟随系统）、导出目录（文件保存位置）、性能模式（融合用多少算力）、设备（镜像/RGB 摄像头）、检查更新。
      </PageIntro>
      <div className="layout-cards">
        <div className="card">
          <h3>导出</h3>
          <div className="field"><label>导出目录</label>
            <input type="text" value={exportDir} onChange={e => setExportDir(e.target.value)}
              style={{ flex: 1, minWidth: 0, fontSize: 11.5 }} placeholder="D:\...\扫描输出" />
          </div>
          <div className="row" style={{ marginTop: 7 }}>
            <button className="btn" onClick={() => showToast('提示：直接编辑路径后点“应用”（网页沙箱限制选择对话框）')}><FolderOpen size={14} /> 浏览…</button>
            <button className="btn primary" onClick={applyDir}>应用</button>
          </div>
          <div className="hint" style={{ marginTop: 7 }}>所有导出（快照/点云/转台/融合产物）都保存到这里。</div>
        </div>

        <div className="card">
          <h3>性能</h3>
          <div className="field"><label>模式</label>
            <select value={perf} onChange={e => choosePerf(e.target.value)} style={{ flex: 1, minWidth: 0 }}>
              <option value="std">标准（保留 1 核 · 不用 GPU）</option>
              <option value="perf">性能（保留 1 核 · GPU 启用）</option>
              <option value="turbo">狂暴（全部拉满）</option>
            </select></div>
          <div className="hint" style={{ marginTop: 7 }}>{perfDesc[perf]}</div>
          <div className="stat" style={{ marginTop: 9 }}>
            <span className="k">本机检测</span>
            <span className="v">{cores} 核 / {gpu.name || '无 NVIDIA'}</span>
          </div>
        </div>

        <div className="card">
          <h3>外观</h3>
          <div className="field"><label>主题</label>
            <select defaultValue="light" onChange={e => {
              document.documentElement.dataset.theme = e.target.value
              try { localStorage.setItem('af-theme', e.target.value) } catch {}
            }} style={{ flex: 1, minWidth: 0 }}>
              <option value="light">浅色（默认）</option>
              <option value="dark">深色</option>
              <option value="auto">跟随系统</option>
            </select></div>
          <div className="hint" style={{ marginTop: 7 }}>顶栏右侧也可快速切换；选择会被记住。</div>
          <div className="field" style={{ marginTop: 9 }}><label>预览镜像</label>
            <select value={flip ? '1' : '0'} onChange={async e => {
              const v = e.target.value === '1'
              setFlip(v)
              await api.setFlip(v).catch(() => {})
              showToast(`预览镜像: ${v ? '开' : '关'}`)
            }} style={{ width: 90 }}>
              <option value="1">开</option><option value="0">关</option>
            </select></div>
          <div className="hint" style={{ marginTop: 7 }}>预览与保存/导出统一为"照镜子"方向（人在哪边、画面和文件里也在哪边）；此开关只用于预览翻面对比。</div>
        </div>

        <div className="card">
          <h3>更新</h3>
          <div className="hint" style={{ marginBottom: 8 }}>
            通过 GitHub OTA 更新单个模块（不改动整包）。需先在设置源里配置仓库地址（见 README）。
          </div>
          <div className="row">
            <button className="btn" onClick={async () => {
              try {
                const r = await api.checkUpdate()
                showToast(r.ok ? `检查完成: ${JSON.stringify(r.result).slice(0, 120)}` : `检查失败: ${r.error}`)
              } catch (e) { showToast(`✗ ${e.message}`) }
            }}>检查更新</button>
            <button className="btn" onClick={() => showToast('版本信息见「关于」页')}>当前版本</button>
          </div>
        </div>
      </div>

      {/* 狂暴模式免责模态 */}
      {turboOpen && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,.45)', zIndex: 400,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div className="card" style={{ width: 420, padding: 20 }}>
            <h3 style={{ fontSize: 15, marginBottom: 10 }}>狂暴模式 · 免责声明</h3>
            <div className="hint" style={{ lineHeight: 1.9 }}>
              狂暴模式将使用<b>全部 CPU 核心</b>与<b>显卡满功率</b>算力。<br />
              可能导致：系统卡顿、发热、风扇噪音明显、电池快速耗尽。<br />
              建议：插电使用，期间不要处理重要工作。<br />
              一切后果由使用者自行承担。可随时切回标准或性能模式。
            </div>
            <div className="row" style={{ marginTop: 14, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setTurboOpen(false)}>取消</button>
              <button className="btn" style={{ background: 'var(--err)', borderColor: 'var(--err)', color: '#fff' }}
                onClick={confirmTurbo}>我已知晓，开启狂暴</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
