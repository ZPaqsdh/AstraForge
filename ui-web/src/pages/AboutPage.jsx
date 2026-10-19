import { useEffect, useRef, useState } from 'react'
import {
  RefreshCw, Download, Check, AlertTriangle, FolderOpen, Usb, Trash2,
  Copy, Mail, GitBranch, Bug, ExternalLink, Package, ShieldCheck,
  Send, Cpu, HardDrive,
} from 'lucide-react'
import { Btn, Section, Modal, Pill, Field } from '../ui.jsx'
import { api } from '../api.js'

const UPDATE_LOG = [
  { version: '安装器 v4', date: '2026-10-18', note: '单文件双形态、驱动库、轻量卸载器' },
  { version: 'v0.2.10', date: '2026-10-16', note: '出厂标定、采集质量可视化' },
  { version: 'v0.2.9', date: '2026-10-16', note: '方向链统一、设置持久化、4 项修复' },
  { version: 'v0.2.0', date: '2026-10-14', note: 'React UI、模块化管线' },
  { version: 'v0.1.0', date: '2026-10-12', note: 'USB 协议复活、首版' },
]

const GH = 'https://github.com/ZPaqsdh/AstraForge'

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch (e) {
    try {
      const ta = document.createElement('textarea')
      ta.value = text
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      return true
    } catch (err) {
      return false
    }
  }
}

function fmtDiag(d) {
  if (!d) return ''
  const dev = d.device || {}
  return [
    `AstraForge v${d.version || '?'}`,
    `OS：${d.os || '?'} · Python ${d.python || '?'} · ${d.cpu_cores || '?'} 核`,
    `设备：${dev.connected ? '已连接' : '未连接'}${dev.streaming ? ' · 流中' : ''}` +
      ` · 补偿 ${dev.padded || 0} / 拒帧 ${dev.rejected || 0}`,
    `GPU：${d.gpu?.name || '未检测到 NVIDIA'}`,
    `模块：${Object.entries(d.modules || {}).map(([k, v]) => `${k} ${v}`).join(' / ') || '—'}`,
    `日志：`,
    ...(d.logs || []).slice(-10),
    `时间：${d.ts || ''}`,
  ].join('\n')
}

function friendlyUpdateError(msg) {
  const t = String(msg || '')
  if (/RemoteDisconnected|timed out|urlopen|network|Tunnel|Proxy|Connection/i.test(t)) {
    return '无法连接 GitHub 更新源（网络或代理限制）'
  }
  return t
}

function UpdateCard({ app, onChanged }) {
  const { showToast } = app
  const [phase, setPhase] = useState('idle')     // idle|checking|result|downloading|downloaded|error
  const [info, setInfo] = useState(null)
  const [st, setSt] = useState(null)
  const [err, setErr] = useState('')
  const [checkedAt, setCheckedAt] = useState('')
  const timer = useRef(null)

  const check = async () => {
    setPhase('checking')
    setErr('')
    try {
      const r = await api.updateCheck()
      if (!r.ok) throw new Error(r.error || '检查失败')
      setInfo(r)
      setPhase('result')
      setCheckedAt(new Date().toTimeString().slice(0, 5))
      showToast(r.has_update ? `发现新版本 v${r.latest}` : '已是最新版本')
    } catch (e) {
      setErr(friendlyUpdateError(e.message || e))
      setPhase('error')
      showToast(`✗ 检查更新失败：${friendlyUpdateError(e.message || e)}`, 5000)
    }
  }

  const download = async () => {
    if (!info) return
    try {
      const r = await api.updateDownload(info.payload_url, info.payload_sha256, info.latest)
      if (!r.ok) throw new Error(r.error || '下载启动失败')
      setPhase('downloading')
      setSt(r.state)
    } catch (e) {
      setErr(String(e.message || e))
      setPhase('error')
    }
  }

  // 下载进度轮询
  useEffect(() => {
    if (phase !== 'downloading') return
    let alive = true
    const tick = async () => {
      try {
        const s = await api.updateStatus()
        if (!alive) return
        setSt(s)
        if (s.phase === 'done') { setPhase('downloaded'); showToast('✓ 更新包下载完成，校验通过', 4500) }
        if (s.phase === 'error') { setErr(s.error || '下载失败'); setPhase('error') }
      } catch (e) { /* 忽略单次轮询失败 */ }
    }
    tick()
    timer.current = setInterval(tick, 700)
    return () => { alive = false; clearInterval(timer.current) }
  }, [phase])

  const apply = async () => {
    try {
      const r = await api.updateApply()
      if (!r.ok) throw new Error(r.error || '无法启动更新')
      showToast('正在退出并替换程序文件，随后自动重启…', 8000)
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 5000)
    }
  }

  const current = info?.current || app.version || ''
  const latest = info?.latest || current

  return (
    <Section title="版本与更新" aside={
      <Pill tone={phase === 'result' && info?.has_update ? 'warn'
        : phase === 'error' ? 'err' : phase === 'downloaded' ? 'ok' : ''}>
        {phase === 'checking' ? '检查中' : phase === 'downloading' ? '下载中'
          : phase === 'downloaded' ? '待安装' : phase === 'error' ? '失败'
            : phase === 'result' ? (info?.has_update ? '有新版本' : '已是最新') : '未检查'}
      </Pill>
    }>
      <div className="af-version-row">
        <div className="af-version-big">v{current}</div>
        <div className="af-version-meta">
          <span>当前版本</span>
          <small>通道 stable · {info ? (info.mode === 'dev' ? '开发目录' : '安装版') : '—'}</small>
        </div>
        <div className="af-version-spacer" />
        {info?.has_update ? (
          <span className="af-new-version">v{latest} <small>可更新</small></span>
        ) : null}
      </div>

      {phase === 'result' && info?.has_update ? (
        <div className="af-update-box">
          <div className="af-update-head">
            <Download size={15} /><b>v{latest} 可用</b>
            <span>整包更新</span>
          </div>
          <ul>
            <li>更新日志与 Release 说明：{info.notes_url || '—'}</li>
            <li>下载后校验 SHA-256，再替换程序文件</li>
            <li>更新不会删除导出目录里的扫描会话</li>
          </ul>
          <div className="af-row">
            <Btn primary icon={Download} onClick={download}>下载更新包</Btn>
            <Btn ghost onClick={() => api.openUrl(info.notes_url).catch((e) => showToast(e.message))}>
              查看 Release
            </Btn>
          </div>
        </div>
      ) : null}

      {phase === 'result' && !info?.has_update ? (
        <div className="af-callout ok"><Check size={15} /> 已是最新版本 v{current}</div>
      ) : null}

      {phase === 'downloading' ? (
        <div className="af-update-box">
          <div className="af-update-head">
            <Download size={15} /><b>正在下载 v{latest}</b><span>{st?.pct || 0}%</span>
          </div>
          <div className="af-bar"><span style={{ width: `${st?.pct || 0}%` }} /></div>
          <div className="af-hint">{st?.msg || '连接下载源…'}</div>
        </div>
      ) : null}

      {phase === 'downloaded' ? (
        <div className="af-update-box">
          <div className="af-callout ok"><Check size={15} /> 更新包已下载并通过 SHA-256 校验</div>
          <div className="af-mono ellipsis" title={st?.path}>{st?.path}</div>
          <div className="af-row">
            {info?.can_apply ? (
              <Btn primary icon={RefreshCw} onClick={apply}>重启并安装</Btn>
            ) : (
              <Btn icon={FolderOpen}
                onClick={() => api.openDir(st?.path.replace(/[\\/][^\\/]+$/, ''))
                  .catch((e) => showToast(e.message))}>打开更新包位置</Btn>
            )}
            <span className="af-hint">
              {info?.can_apply ? '点击后应用会退出，替换完成后自动重启'
                : '开发目录不能自动覆盖；请用安装器更新'}
            </span>
          </div>
        </div>
      ) : null}

      {phase === 'error' ? (
        <div className="af-callout err">
          <AlertTriangle size={15} /> {err}
          <Btn small ghost onClick={check}>重试</Btn>
        </div>
      ) : null}

      <div className="af-update-foot">
        <Btn icon={RefreshCw} onClick={check} disabled={phase === 'checking' || phase === 'downloading'}>
          {phase === 'checking' ? '检查中…' : '检查更新'}
        </Btn>
        <span className="af-hint">上次检查：{checkedAt || '—'}</span>
        <span className="af-hint">更新源：GitHub Releases</span>
      </div>
    </Section>
  )
}

export default function AboutPage({ app }) {
  const { showToast } = app
  const [about, setAbout] = useState(null)
  const [paths, setPaths] = useState(null)
  const [scan, setScan] = useState(null)
  const [scanning, setScanning] = useState(true)
  const [diag, setDiag] = useState(null)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [fb, setFb] = useState({ type: 'Bug', title: '', body: '', withDiag: true })

  const load = async () => {
    try {
      const [a, p, d] = await Promise.all([api.about(), api.paths(), api.diag()])
      setAbout(a); setPaths(p); setDiag(d)
    } catch (e) { /* 启动瞬间 */ }
  }

  const refreshDriver = async () => {
    setScanning(true)
    try {
      const r = await api.deviceScan(true)
      setScan(r)
      showToast(r.depth?.found
        ? `已检测：2BC5:${r.depth.pid} · ${r.depth.service || '无驱动'}`
        : '未检测到 Astra 设备')
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    } finally {
      setScanning(false)
    }
  }

  useEffect(() => {
    let alive = true
    load()
    // PnP 枚举偶尔比页面慢：没找到时自动再试一次（不轮询，避免常驻 PowerShell）
    const tick = async (attempt = 0) => {
      setScanning(true)
      try {
        const r = await api.deviceScan()
        if (!alive) return
        setScan(r)
        setScanning(false)
        if (!r.depth?.found && attempt < 2) setTimeout(() => { if (alive) tick(attempt + 1) }, 2500)
      } catch (e) {
        if (alive) setScanning(false)
      }
    }
    tick()
    return () => { alive = false }
  }, [])

  const depth = scan?.depth || {}
  const driverState = depth.state === 'ready' ? 'ok'
    : depth.state === 'conflict' ? 'warn' : depth.found ? 'warn' : ''

  const copyDiag = async () => {
    const ok = await copyText(fmtDiag(diag))
    showToast(ok ? '诊断信息已复制到剪贴板' : '诊断已生成，但剪贴板不可用')
  }

  const submitFeedback = async () => {
    if (!fb.title.trim()) { showToast('标题不能为空'); return }
    const body = [
      fb.body.trim() || '（没有填写复现步骤）',
      '',
      '---',
      fb.withDiag ? fmtDiag(diag) : '（未附带诊断信息）',
    ].join('\n').slice(0, 6000)
    const labels = fb.type === 'Bug' ? 'bug' : (fb.type === '建议' ? 'enhancement' : '')
    const url = `${GH}/issues/new?title=${encodeURIComponent('[AstraForge] ' + fb.title.trim())}`
      + `&body=${encodeURIComponent(body)}`
      + (labels ? `&labels=${labels}` : '')
    try {
      const r = await api.openUrl(url)
      if (r && r.ok === false) throw new Error(r.error || '无法打开浏览器')
      setFeedbackOpen(false)
      showToast('已在浏览器打开 GitHub Issue 预填页，确认后提交', 5000)
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 4500)
    }
  }

  const openExe = async (path, label) => {
    if (!path) { showToast(`没有找到${label}`); return }
    try {
      const r = await api.openDir(path)
      if (r && r.ok === false) throw new Error(r.error || '打开失败')
    } catch (e) {
      showToast(`✗ ${e.message || e}`)
    }
  }

  const version = about?.version || app.version || ''

  return (
    <div className="af-page af-about">
      <header className="af-page-head">
        <div>
          <h1>关于与更新</h1>
          <p>版本、更新、安装与驱动、反馈、许可，一页收齐</p>
        </div>
        <div className="af-about-version">AstraForge 星铸 <b>v{version}</b></div>
      </header>

      <div className="af-about-grid">
        <div className="af-about-col">
          <UpdateCard app={app} onChanged={load} />

          <Section title="更新日志" aside={<span className="af-hint">最近 5 条</span>}>
            <div className="af-changelog">
              {UPDATE_LOG.map((x, i) => (
                <div key={x.version} className="af-log-row">
                  <span className={`af-log-dot ${i === 0 ? 'new' : ''}`} />
                  <span className="af-log-version">{x.version}</span>
                  <span className="af-log-date">{x.date}</span>
                  <span className="af-log-note">{x.note}</span>
                </div>
              ))}
            </div>
            <button className="af-link" onClick={() => api.openUrl(`${GH}/releases`).catch((e) => showToast(e.message))}>
              查看全部 <ExternalLink size={12} />
            </button>
          </Section>
        </div>

        <div className="af-about-col">
          <Section title="安装与驱动" aside={<Package size={15} />}>
            <div className="af-kv"><span>安装方式</span>
              <b>{paths?.installed ? '安装版（AstraForge.exe）' : '源码 / 开发目录'}</b></div>
            <div className="af-kv"><span>程序目录</span>
              <b className="af-mono ellipsis" title={paths?.root}>{paths?.root || '—'}</b></div>
            <div className="af-kv"><span>导出目录</span>
              <b className="af-mono ellipsis" title={paths?.export}>{paths?.export || '—'}</b></div>
            <div className="af-driver-box">
              <div className="af-driver-head">
                <span className={`af-dot ${driverState === 'ok' ? 'ok' : driverState === 'warn' ? 'idle' : 'idle'}`} />
                <b>{depth.found ? `Astra 2BC5:${depth.pid}` : scanning ? '正在枚举设备…' : '未检测到深度相机'}</b>
                <Pill tone={driverState === 'ok' ? 'ok' : driverState === 'warn' ? 'warn' : ''}>
                  {scanning ? '检测中' : depth.state === 'ready' ? 'WinUSB' : depth.state === 'conflict' ? '需要切换' :
                    depth.state === 'nodriver' ? '无驱动' : depth.found ? '未知驱动' : '未连接'}
                </Pill>
              </div>
              <div className="af-driver-meta">
                {depth.found
                  ? `${depth.instance || ''} · 服务 ${depth.service || '—'} · 状态 ${depth.status || '—'}`
                  : '插好相机后点「重新检测」；深度相机需要 WinUSB。'}
              </div>
            </div>
            <div className="af-row wrap">
              <Btn small icon={RefreshCw} onClick={refreshDriver}>重新检测</Btn>
              <Btn small icon={Usb} onClick={() => openExe(paths?.driver_tool, '驱动工具（Zadig）')}>
                打开驱动工具
              </Btn>
              <Btn small icon={FolderOpen} onClick={() => openExe(paths?.root, '程序目录')}>打开程序目录</Btn>
              <Btn small danger icon={Trash2} disabled={!paths?.uninstaller}
                onClick={() => openExe(paths?.uninstaller, '卸载器')}>
                卸载
              </Btn>
            </div>
            <div className="af-hint">
              深度 2BC5:0403 需要 WinUSB；彩色 2BC5:0501 为 UVC，系统相机可直接识别。
              驱动切换会短暂断开设备，切换后回到「三维扫描」重新连接。
            </div>
          </Section>

          <Section title="反馈与诊断" aside={<Bug size={15} />}>
            <p className="af-section-copy">
              反馈会附带诊断信息（系统 / 设备 / 模块 / 最近日志）。提交前会打开 GitHub Issue 预填页，
              可在浏览器里确认后提交；也可以复制诊断贴到邮件里。
            </p>
            <div className="af-feedback-actions">
              <Btn primary icon={Send} onClick={() => setFeedbackOpen(true)}>反馈问题</Btn>
              <Btn icon={Copy} onClick={copyDiag}>复制诊断</Btn>
              <Btn icon={Mail} onClick={() => api.openUrl(
                `mailto:1544648188z@gmail.com?subject=${encodeURIComponent('[AstraForge] 反馈')}`
                + `&body=${encodeURIComponent(fmtDiag(diag))}`,
              ).catch((e) => showToast(e.message))}>邮件</Btn>
              <Btn icon={GitBranch} onClick={() => api.openUrl(`${GH}/issues/new/choose`)
                .catch((e) => showToast(e.message))}>GitHub Issue</Btn>
            </div>
            <div className="af-hint">诊断只包含版本、系统、设备状态、模块版本与最近日志；不含序列号。提交前可在预览里检查并删改。</div>
          </Section>
        </div>

        <Section title="关于" className="af-span-2">
          <div className="af-about-foot">
            <div className="af-about-brand">
              <div className="af-logo small">AF</div>
              <div><b>AstraForge 星铸</b><small>Orbbec Astra 深度相机 3D 扫描工作站</small></div>
            </div>
            <div className="af-about-meta">
              <span><ShieldCheck size={13} /> Apache License 2.0</span>
              <span><Cpu size={13} /> Python / React / Lucide</span>
              <span><HardDrive size={13} /> {about?.modules ? `${Object.keys(about.modules).length} 个模块` : '—'}</span>
              <span onClick={() => api.openUrl(GH).catch((e) => showToast(e.message))}
                style={{ cursor: 'pointer' }}>
                <GitBranch size={13} /> github.com/ZPaqsdh/AstraForge
              </span>
            </div>
            <p className="af-disclaimer">
              本软件按「现状」提供，不附带任何担保。深度相机含 Class 1 激光，请勿直视或改装光路。
              本项目为社区实现，与 Orbbec 无隶属关系。
            </p>
          </div>
        </Section>
      </div>

      {feedbackOpen ? (
        <Modal title="反馈问题" onClose={() => setFeedbackOpen(false)} width={580}>
          <div className="af-inline-2">
            <Field label="类型">
              <select value={fb.type} onChange={(e) => setFb({ ...fb, type: e.target.value })}>
                <option>Bug</option><option>建议</option><option>其他</option>
              </select>
            </Field>
            <Field label="标题">
              <input value={fb.title} onChange={(e) => setFb({ ...fb, title: e.target.value })}
                placeholder="一句话描述问题" />
            </Field>
          </div>
          <Field label="描述 / 复现步骤">
            <textarea rows={5} value={fb.body}
              onChange={(e) => setFb({ ...fb, body: e.target.value })}
              placeholder="做了什么、期望什么、实际发生了什么" />
          </Field>
          <label className="af-check">
            <input type="checkbox" checked={fb.withDiag}
              onChange={(e) => setFb({ ...fb, withDiag: e.target.checked })} />
            <span>附带诊断信息（版本 / 设备 / 模块 / 最近日志）</span>
          </label>
          <details className="af-diag-preview">
            <summary>预览诊断信息</summary>
            <pre>{fmtDiag(diag)}</pre>
          </details>
          <div className="af-modal-actions">
            <Btn onClick={() => setFeedbackOpen(false)}>取消</Btn>
            <Btn primary icon={Send} onClick={submitFeedback}>生成 Issue 草稿</Btn>
          </div>
        </Modal>
      ) : null}
    </div>
  )
}
