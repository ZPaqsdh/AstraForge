import { useEffect, useRef, useState } from 'react'
import {
  RefreshCw, Download, Check, AlertTriangle, FolderOpen, Usb, Trash2,
  Copy, Mail, GitBranch, Bug, ExternalLink, Package, ShieldCheck,
  Send, Cpu, HardDrive, Wrench,
} from 'lucide-react'
import { Btn, Section, Modal, Pill, Field } from '../ui.jsx'
import { api } from '../api.js'

const MAIL = '1544648188z@gmail.com'

const UPDATE_LOG = [
  { version: 'v0.3.5', date: '2026-10-20', note: '驱动按钮不再哑灰（原因可见）、USB 复位、插拔重新识别、复制/邮箱反馈' },
  { version: 'v0.3.4', date: '2026-10-20', note: '驱动随包一体可自修、反馈交互重做、更新自动检测' },
  { version: 'v0.3.3', date: '2026-10-20', note: '导出模型左右边缘颗粒清理、预览竖线修复' },
  { version: 'v0.3.2', date: '2026-10-20', note: '深度预览右缘竖线修复（按方位裁垃圾带）' },
  { version: 'v0.3.1', date: '2026-10-19', note: '成像方向纠正：导出无镜像，镜像只影响预览' },
  { version: 'v0.3.0', date: '2026-10-19', note: '四导航 UI 重做、应用内更新与反馈' },
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

/** 复制按钮：点了**就地**变「已复制 ✓」+ 旁边常驻一行结果（2s 后按钮复原，提示保留 6s）。
 *
 * BUG-025：老大反馈"点了没反馈"。原因有两层——① 只有 toast，容易被忽略/被窗口边缘裁掉；
 * ② 按钮变「已复制」后 2 秒复原，慢一点看就什么都没有。现在三重反馈：
 * 按钮文字变「已复制」+ 行内文字「已复制 N 字，可直接粘贴」+ toast，且**可以反复点**。
 */
function CopyBtn({ text, label, icon = Copy, showToast, small = true, primary = false }) {
  const [done, setDone] = useState(false)
  const [msg, setMsg] = useState('')
  const timer = useRef(null)
  const msgTimer = useRef(null)
  const go = async () => {
    const payload = typeof text === 'function' ? text() : text
    const ok = await copyText(payload)
    clearTimeout(timer.current)
    clearTimeout(msgTimer.current)
    if (!ok) {
      setDone(false)
      setMsg('✗ 复制失败：剪贴板不可用，请手动选中文字复制')
      showToast('✗ 复制失败：剪贴板不可用', 5000)
      msgTimer.current = setTimeout(() => setMsg(''), 8000)
      return
    }
    const n = String(payload == null ? '' : payload).length
    setDone(true)
    setMsg(`✓ 已复制 ${n} 字，可直接粘贴`)
    timer.current = setTimeout(() => setDone(false), 2000)
    msgTimer.current = setTimeout(() => setMsg(''), 6000)
    showToast('✓ 已复制到剪贴板')
  }
  useEffect(() => () => { clearTimeout(timer.current); clearTimeout(msgTimer.current) }, [])
  return (
    <span className="af-copy-wrap">
      <Btn small={small} primary={primary} icon={done ? Check : icon}
        className={done ? 'ok' : ''} onClick={go}>
        {done ? '已复制' : label}
      </Btn>
      {msg ? <span className={msg.startsWith('✓') ? 'af-copy-ok' : 'af-copy-bad'}>{msg}</span> : null}
    </span>
  )
}

/** 邮箱反馈：软件内弹窗显示地址 + 一键复制（不再落到浏览器）。 */
function MailDialog({ diag, onClose, showToast }) {
  return (
    <Modal title="邮箱反馈" onClose={onClose} width={540}>
      <p className="af-section-copy">
        把问题发到这个邮箱即可。建议带上诊断信息（版本 / 系统 / 设备 / 最近日志），定位会快很多。
      </p>
      <div className="af-mail-addr" title="选中后可 Ctrl+C">{MAIL}</div>
      <div className="af-row wrap">
        <CopyBtn text={MAIL} label="复制邮箱" showToast={showToast} />
        <CopyBtn primary
          text={() => `收件人：${MAIL}\n\n【问题描述】\n（做了什么、期望什么、实际发生了什么）\n\n【诊断信息】\n${fmtDiag(diag)}`}
          label="复制邮箱 + 诊断" showToast={showToast} />
      </div>
      <div className="af-hint">
        本机没装邮件客户端时，系统会把邮件链接交给浏览器（网页版邮箱）；所以这里默认只复制，不自动跳转。
        需要的话也可以用
        <button className="af-link" onClick={() => api.openUrl(
          `mailto:${MAIL}?subject=${encodeURIComponent('[AstraForge] 反馈')}`
            + `&body=${encodeURIComponent(fmtDiag(diag))}`,
        ).catch(() => showToast('✗ 系统没有可用的邮件处理程序', 5000))}>系统邮件打开</button>。
      </div>
    </Modal>
  )
}

function UpdateCard({ app, onChanged }) {
  const { showToast } = app
  const auto = app.update || null
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
      showToast(r.needs_installer
        ? '更新已写入；部分运行时文件被占用，若启动异常请用安装器覆盖'
        : '更新已写入，正在重启应用…', 8000)
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
              {info?.can_apply ? '点击后写入更新并自动重启；运行时文件被占用时会提示'
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
        <span className="af-hint">
          自动检测：启动时 + 每 12 小时
          {auto?.checked_at ? ` · 最近 ${String(auto.checked_at).slice(11, 16)}` : ''}
          {auto?.next_check_at ? ` · 下次 ${String(auto.next_check_at).slice(11, 16)}` : ''}
        </span>
      </div>
    </Section>
  )
}

export default function AboutPage({ app }) {
  const { showToast } = app
  const [about, setAbout] = useState(null)
  const [paths, setPaths] = useState(null)
  const [drv, setDrv] = useState(null)          // {scan, depth, driver_pack, matched, can_install}
  const [scanning, setScanning] = useState(true)
  const [installing, setInstalling] = useState(false)
  const [drvMsg, setDrvMsg] = useState('')
  const [diag, setDiag] = useState(null)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [mailOpen, setMailOpen] = useState(false)
  const [fb, setFb] = useState({ type: 'Bug', title: '', body: '', withDiag: true })

  const load = async () => {
    try {
      const [a, p, d] = await Promise.all([api.about(), api.paths(), api.diag()])
      setAbout(a); setPaths(p); setDiag(d)
    } catch (e) { /* 启动瞬间 */ }
  }

  const refreshDriver = async (deep = true) => {
    setScanning(true)
    setDrvMsg('')
    try {
      const r = await api.driverState(deep)
      setDrv(r)
      const d = r.depth || {}
      const b = r.blockers || {}
      if (b.pack) setDrvMsg(b.pack)
      else if (b.zadig) setDrvMsg(b.zadig)
      showToast(d.found
        ? `已检测：2BC5:${d.pid} · ${d.service || '无驱动'}`
        : '未枚举到 2BC5:0403 设备（点「重新检测」做深查）')
    } catch (e) {
      setDrvMsg(`检测失败：${e.message || e}`)
      showToast(`✗ 检测失败：${e.message || e}`, 6000)
    } finally {
      setScanning(false)
    }
  }

  /** 按钮可用性检查：不满足时**点了也会说清楚原因**（而不是一片灰、点了没反应）。 */
  const guard = (reason, fn) => {
    if (reason) {
      setDrvMsg(reason)
      showToast(`✗ ${reason}`, 8000)
      return
    }
    fn()
  }

  const openDriverFolder = async () => {
    try {
      const r = await api.driverOpenFolder()
      if (!r.ok) throw new Error(r.error || '打开失败')
      setDrvMsg(`已打开：${r.path}`)
    } catch (e) {
      setDrvMsg(`打开失败：${e.message || e}`)
      showToast(`✗ ${e.message || e}`, 6000)
    }
  }

  const resetUsb = async () => {
    setInstalling(true)
    setDrvMsg('正在 USB 复位（约 2–4 秒）…')
    try {
      const r = await api.deviceReset()
      setDrvMsg((r.steps || []).join(' · '))
      showToast(r.ok ? (r.streaming ? '✓ USB 复位完成，流已恢复' : '✓ USB 复位完成，设备已打开')
        : `✗ ${r.error || '复位后仍打不开设备'}`, 7000)
      await refreshDriver(true)
    } catch (e) {
      setDrvMsg(`复位失败：${e.message || e}`)
      showToast(`✗ 复位失败：${e.message || e}`, 7000)
    } finally {
      setInstalling(false)
    }
  }

  const installDriver = async () => {
    setInstalling(true)
    try {
      const r = await api.driverInstall(drv?.matched?.id || '')
      if (r.ok) {
        showToast(r.elevated ? '已请求管理员权限，确认后点「重新检测」' : '✓ 驱动已安装', 6000)
      } else if (r.guided) {
        showToast('该设备需用驱动向导（Zadig）切换，点「驱动向导」', 6000)
      } else {
        showToast(`✗ ${r.error || r.msg || '驱动安装失败'}`, 6000)
      }
      await refreshDriver(true)
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 5000)
    } finally {
      setInstalling(false)
    }
  }

  const openZadig = async () => {
    try {
      const r = await api.driverOpenTool()
      if (!r.ok) throw new Error(r.error || '打开失败')
      showToast('已打开驱动向导（Zadig）')
    } catch (e) {
      showToast(`✗ ${e.message || e}`, 6000)
    }
  }

  useEffect(() => {
    let alive = true
    load()
    // PnP 枚举偶尔比页面慢：没找到时自动再试一次（不轮询，避免常驻 PowerShell）
    const tick = async (attempt = 0) => {
      setScanning(true)
      try {
        const r = await api.driverState(attempt > 0)
        if (!alive) return
        setDrv(r)
        setScanning(false)
        if (!(r.depth || {}).found && attempt < 2) setTimeout(() => { if (alive) tick(attempt + 1) }, 2500)
      } catch (e) {
        if (alive) setScanning(false)
      }
    }
    tick()
    return () => { alive = false }
  }, [])

  const depth = drv?.depth || {}
  const pack = drv?.driver_pack || {}
  const matched = drv?.matched || null
  const blockers = drv?.blockers || {}
  const blockKeys = ['pack', 'zadig', 'device', 'match'].filter((k) => blockers[k])
  const driverState = depth.state === 'ready' ? 'ok'
    : depth.state === 'conflict' ? 'warn' : depth.found ? 'warn' : ''

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
                  {scanning ? '检测中' : depth.state === 'ready' ? 'WinUSB 就绪' : depth.state === 'conflict' ? '需要切换' :
                    depth.state === 'nodriver' ? '无驱动' : depth.found ? '未知驱动' : '未连接'}
                </Pill>
              </div>
              <div className="af-driver-meta">
                {depth.found
                  ? `${depth.instance || ''} · 服务 ${depth.service || '—'} · 状态 ${depth.status || '—'}`
                  : '插好相机后点「重新检测」；深度相机需要 WinUSB。'}
              </div>
              <div className="af-driver-meta">
                驱动库：{pack.has_pack
                  ? `${pack.devices?.length || 0} 个机型 · ${pack.devices?.map((x) => x.name).join(' / ') || '—'}`
                  : '未找到（请重新运行安装器）'}
                {pack.has_pack && !pack.zadig_ok ? ' · 驱动向导缺失' : ''}
              </div>
            </div>

            <div className="af-row wrap">
              <Btn small icon={RefreshCw} onClick={() => refreshDriver(true)} disabled={scanning}>
                {scanning ? '检测中…' : '重新检测'}
              </Btn>
              <Btn small primary icon={Wrench} disabled={installing}
                onClick={() => guard(blockers.device || blockers.match || blockers.pack,
                  installDriver)}>
                {installing ? '安装中…' : (depth.state === 'ready' ? '修复驱动' : '安装驱动')}
              </Btn>
              <Btn small icon={Usb} onClick={() => guard(blockers.zadig, openZadig)}>
                驱动向导
              </Btn>
              <Btn small icon={FolderOpen}
                onClick={() => guard(blockers.pack, openDriverFolder)}>
                驱动文件夹
              </Btn>
              <Btn small icon={Cpu} onClick={() => guard(blockers.device, resetUsb)}>
                USB 复位
              </Btn>
              <Btn small icon={FolderOpen} onClick={() => openExe(paths?.root, '程序目录')}>程序目录</Btn>
              <Btn small danger icon={Trash2} disabled={!paths?.uninstaller}
                onClick={() => openExe(paths?.uninstaller, '卸载器')}>
                卸载
              </Btn>
            </div>
            {/* BUG-025：不可用的原因必须写在脸上，不能只留一片灰按钮 */}
            {blockKeys.length ? (
              <div className="af-block-list">
                {blockKeys.map((k) => (
                  <div key={k} className="af-block-item">✗ {blockers[k]}</div>
                ))}
              </div>
            ) : null}
            <div className="af-hint">
              {matched
                ? `已匹配驱动条目：${matched.name}（${matched.method === 'pnputil-inf' ? '签名 INF · 自动安装' : '需 Zadig 向导'}）`
                : '深度 2BC5:0403 需要 WinUSB；彩色 2BC5:0501 为 UVC，系统相机可直接识别。'}
              驱动切换会短暂断开设备，完成后回到「三维扫描」重新连接。
              {drvMsg ? <b className="af-drv-msg"> · {drvMsg}</b> : null}
            </div>
          </Section>

          <Section title="反馈与诊断" aside={<Bug size={15} />}>
            <p className="af-section-copy">
              反馈可走 GitHub Issue（自动预填）或邮箱（{MAIL}）。两种方式都可以附带诊断信息
              （版本 / 系统 / 设备 / 模块 / 最近日志），提交前可自行检查。
            </p>
            <div className="af-feedback-actions">
              <Btn primary icon={Send} onClick={() => {
                setFeedbackOpen(true)
                showToast('已打开反馈窗口：填标题后点「生成 Issue 草稿」', 3500)
              }}>反馈问题</Btn>
              <CopyBtn text={() => fmtDiag(diag)} label="复制诊断" showToast={showToast} />
              <Btn icon={Mail} onClick={() => {
                setMailOpen(true)
                showToast(`已打开邮箱反馈窗口：${MAIL}`, 3500)
              }}>邮箱</Btn>
              <Btn icon={GitBranch} onClick={async () => {
                try {
                  const r = await api.openUrl(`${GH}/issues/new/choose`)
                  if (r && r.ok === false) throw new Error(r.error || '无法打开浏览器')
                  showToast('已在浏览器打开 GitHub Issue 页面', 4000)
                } catch (e) {
                  showToast(`✗ ${e.message || e}`, 4500)
                }
              }}>GitHub Issue</Btn>
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

      {mailOpen ? (
        <MailDialog diag={diag} showToast={showToast} onClose={() => setMailOpen(false)} />
      ) : null}

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
