import { useEffect, useState } from 'react'
import {
  RefreshCw, Download, Check, AlertTriangle, FolderOpen, Usb, Trash2,
  Copy, Mail, GitBranch, Bug, ExternalLink, FileText, Package, ShieldCheck,
  Send, ChevronRight, Clock,
} from 'lucide-react'
import { Btn, Stat, Section, Modal } from '../components.jsx'
import { UPDATE_LOG } from '../state.js'

function UpdateCard({ state, setState, toast }) {
  const { update } = state

  useEffect(() => {
    if (update.status !== 'downloading') return
    const id = setInterval(() => {
      setState((s) => {
        const p = Math.min(100, s.update.progress + 7)
        if (p >= 100) {
          return { ...s, update: { ...s.update, status: 'done', progress: 100 } }
        }
        return { ...s, update: { ...s.update, progress: p } }
      })
    }, 180)
    return () => clearInterval(id)
  }, [update.status])

  const check = () => {
    setState((s) => ({ ...s, update: { ...s.update, status: 'checking' } }))
    setTimeout(() => {
      setState((s) => ({
        ...s,
        update: { ...s.update, status: 'available', checkedAt: new Date().toTimeString().slice(0, 5) },
        logs: [...s.logs.slice(-19), { t: new Date().toTimeString().slice(0, 8), text: '发现新版本 v0.3.0', ok: true }],
      }))
      toast('发现新版本 v0.3.0')
    }, 900)
  }

  const download = () => {
    setState((s) => ({ ...s, update: { ...s.update, status: 'downloading', progress: 0 } }))
    toast('开始下载更新包')
  }

  return (
    <Section
      title="版本与更新"
      aside={<span className={`af-pill ${update.status === 'available' ? 'warn' : update.status === 'done' ? 'ok' : ''}`}>
        {update.status === 'idle' ? '未检查' : update.status === 'checking' ? '检查中' : update.status === 'available' ? '有新版本' : update.status === 'downloading' ? '下载中' : update.status === 'done' ? '已安装' : '失败'}
      </span>}
    >
      <div className="af-version-row">
        <div className="af-version-big">v0.2.10</div>
        <div className="af-version-meta">
          <span>当前版本</span>
          <small>安装器 v0.2.10 · 通道 stable</small>
        </div>
        <div className="af-version-spacer" />
        {update.status === 'available' ? (
          <span className="af-new-version">v0.3.0 <small>可更新</small></span>
        ) : null}
      </div>

      {update.status === 'available' ? (
        <div className="af-update-box">
          <div className="af-update-head"><Download size={15} /><b>v0.3.0 可用</b><span>约 259 MB</span></div>
          <ul>
            <li>网页版 UI 复刻台与信息架构整理</li>
            <li>真实热更新中心 / 反馈入口</li>
            <li>采集质量与设备连接状态优化</li>
          </ul>
          <div className="af-row">
            <Btn primary icon={Download} onClick={download}>下载并安装</Btn>
            <Btn ghost onClick={check}>稍后</Btn>
          </div>
        </div>
      ) : null}

      {update.status === 'downloading' ? (
        <div className="af-update-box">
          <div className="af-update-head"><Download size={15} /><b>正在下载 v0.3.0</b><span>{update.progress}%</span></div>
          <div className="af-bar"><span style={{ width: `${update.progress}%` }} /></div>
          <div className="af-hint">下载完成后校验 SHA-256，再启动安装器。</div>
        </div>
      ) : null}

      {update.status === 'done' ? (
        <div className="af-callout ok"><Check size={15} /> 已更新到 v0.3.0。重启后生效（复刻台演示）。</div>
      ) : null}

      {update.status === 'error' ? (
        <div className="af-callout err"><AlertTriangle size={15} /> 下载失败：网络不可达或校验失败。<Btn small ghost onClick={check}>重试</Btn></div>
      ) : null}

      <div className="af-update-foot">
        <Btn icon={RefreshCw} onClick={check} disabled={update.status === 'checking' || update.status === 'downloading'}>
          {update.status === 'checking' ? '检查中…' : '检查更新'}
        </Btn>
        <span className="af-hint">上次检查：{update.checkedAt}</span>
      </div>
    </Section>
  )
}

export default function AboutPage({ state, setState, toast }) {
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [fb, setFb] = useState({ type: 'Bug', title: '', body: '', diag: true })

  const diag = `AstraForge v0.2.10
安装器 v0.2.10 · UI 2026-10-19
Windows 10.0.19045 · 8 核 / 无 NVIDIA
ASTRA S Pro · 2BC5:0403 · WinUSB
深度流 640×480 · RGB 640×480 · 10.4 fps
页面：${state.page} · 主题：${state.theme}`

  const copyDiag = async () => {
    try {
      await navigator.clipboard.writeText(diag)
      toast('诊断信息已复制到剪贴板')
    } catch {
      toast('诊断信息已生成（复刻台未获得剪贴板权限）')
    }
  }

  const submitFeedback = () => {
    setFeedbackOpen(false)
    toast('已生成反馈草稿：诊断已附带，可在 GitHub Issue 中提交（复刻台）')
    setState((s) => ({ ...s, logs: [...s.logs.slice(-19), { t: new Date().toTimeString().slice(0, 8), text: `反馈草稿：${fb.type} / ${fb.title || '未填标题'}`, ok: true }] }))
  }

  return (
    <div className="af-page af-about">
      <header className="af-page-head">
        <div>
          <h1>关于与更新</h1>
          <p>版本、更新、安装与驱动、反馈、许可，一页收齐</p>
        </div>
        <div className="af-about-version">AstraForge 星铸 <b>v0.2.10</b></div>
      </header>

      <div className="af-about-grid">
        <div className="af-about-col">
          <UpdateCard state={state} setState={setState} toast={toast} />
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
            <button className="af-link" onClick={() => window.open('https://github.com/ZPaqsdh/AstraForge/releases', '_blank')}>
              查看全部 <ExternalLink size={12} />
            </button>
          </Section>
        </div>

        <div className="af-about-col">
          <Section title="安装与驱动" aside={<Package size={15} />}>
            <div className="af-kv"><span>安装器</span><b>v0.2.10 · 单文件</b></div>
            <div className="af-kv"><span>安装目录</span><b className="af-mono ellipsis" title="C:\\Users\\25934\\AppData\\Local\\Programs\\AstraForge">%LOCALAPPDATA%\\Programs\\AstraForge</b></div>
            <div className="af-driver-box">
              <div className="af-driver-head"><span className="af-dot ok" /><b>ASTRA S Pro</b><span className="af-pill ok">WinUSB</span></div>
              <div className="af-driver-meta">2BC5:0403 · 深度相机就绪；彩色 2BC5:0501 为 UVC，无需处理</div>
            </div>
            <div className="af-row wrap">
              <Btn small icon={RefreshCw} onClick={() => toast('已重新检测：ASTRA S Pro / WinUSB')}>重新检测</Btn>
              <Btn small icon={Usb} onClick={() => toast('安装匹配驱动（复刻台）')}>安装匹配驱动</Btn>
              <Btn small icon={FolderOpen} onClick={() => toast('打开安装目录（复刻台）')}>打开目录</Btn>
              <Btn small danger icon={Trash2} onClick={() => toast('启动卸载器（复刻台）')}>卸载</Btn>
            </div>
          </Section>

          <Section title="反馈与诊断" aside={<Bug size={15} />}>
            <p className="af-section-copy">遇到问题：反馈会自动附带诊断信息（系统 / 设备 / 版本 / 最近日志）。也可以先复制诊断，贴到 Issue 或邮件。</p>
            <div className="af-feedback-actions">
              <Btn primary icon={Send} onClick={() => setFeedbackOpen(true)}>反馈问题</Btn>
              <Btn icon={Copy} onClick={copyDiag}>复制诊断</Btn>
              <Btn icon={Mail} onClick={() => { window.location.href = 'mailto:1544648188z@gmail.com?subject=[AstraForge]%20反馈' }}>邮件</Btn>
              <Btn icon={GitBranch} onClick={() => window.open('https://github.com/ZPaqsdh/AstraForge/issues/new/choose', '_blank')}>GitHub Issue</Btn>
            </div>
            <div className="af-hint">复刻台里不会真正提交；真实版本会打开 GitHub Issue 预填页。</div>
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
              <span><Package size={13} /> PySide6 / React / Lucide</span>
              <span><GitBranch size={13} /> github.com/ZPaqsdh/AstraForge</span>
            </div>
            <p className="af-disclaimer">本软件按「现状」提供，不附带任何担保。深度相机含 Class 1 激光，请勿直视或改装光路。本项目为社区实现，与 Orbbec 无隶属关系。</p>
          </div>
        </Section>
      </div>

      {feedbackOpen ? (
        <Modal title="反馈问题" onClose={() => setFeedbackOpen(false)} width={560}>
          <div className="af-inline-2">
            <label className="af-field"><span className="af-field-label">类型</span>
              <select value={fb.type} onChange={(e) => setFb({ ...fb, type: e.target.value })}>
                <option>Bug</option><option>建议</option><option>其他</option>
              </select>
            </label>
            <label className="af-field"><span className="af-field-label">标题</span>
              <input value={fb.title} onChange={(e) => setFb({ ...fb, title: e.target.value })} placeholder="一句话描述问题" />
            </label>
          </div>
          <label className="af-field"><span className="af-field-label">描述 / 复现步骤</span>
            <textarea rows={5} value={fb.body} onChange={(e) => setFb({ ...fb, body: e.target.value })} placeholder="做了什么、期望什么、实际发生了什么" />
          </label>
          <label className="af-check"><input type="checkbox" checked={fb.diag} onChange={(e) => setFb({ ...fb, diag: e.target.checked })} /><span>附带诊断信息（序列号与路径已打码）</span></label>
          <details className="af-diag-preview">
            <summary>预览诊断信息</summary>
            <pre>{diag}</pre>
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
