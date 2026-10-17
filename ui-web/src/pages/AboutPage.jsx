import { useState } from 'react'
import { Mail, Upload, Copy } from 'lucide-react'
import PageIntro from '../components/PageIntro.jsx'
import { api } from '../api.js'
import { usePoll } from '../hooks.jsx'

export default function AboutPage({ app }) {
  const { showToast } = app
  const [about] = usePoll(api.about, 10000)
  const [copied, setCopied] = useState(false)

  const copyDiag = async () => {
    try {
      const d = await api.diag()
      await navigator.clipboard.writeText(JSON.stringify(d, null, 2))
      setCopied(true)
      showToast('✓ 诊断信息已复制（反馈时粘贴）')
      setTimeout(() => setCopied(false), 3000)
    } catch (e) { showToast(`✗ ${e.message}`) }
  }

  const mailto = async () => {
    let diagText = '（诊断信息读取失败——可在工具箱页手动复制后粘贴）'
    try {
      const d = await api.diag()
      diagText = JSON.stringify(d, null, 2)
    } catch { /* 保持占位文案 */ }
    const subject = encodeURIComponent('[AstraForge] 问题反馈 / 建议')
    const body = encodeURIComponent(
      '【问题描述】（做了什么 → 期望什么 → 实际什么）\n\n' +
      '【复现步骤】\n1. \n2. \n\n' +
      '【诊断信息】（已自动附带，请勿删除）\n' + diagText + '\n')
    window.location.href = `mailto:1544648188z@gmail.com?subject=${subject}&body=${body}`
  }

  const mods = about?.modules || {}
  const modEntries = Object.entries(mods).sort((a, b) => a[0].localeCompare(b[0]))

  return (
    <div className="fade-in page-grid">
      <PageIntro id="about">
        <b>关于</b>：版本信息、各模块版本（可单独在线更新）、反馈入口（邮件/GitHub）、开源声明。遇到问题先点「复制诊断信息」。
      </PageIntro>
      <div className="layout-cards">
        <div className="card">
          <h3>AstraForge 星铸</h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, margin: '10px 0' }}>
            <div style={{
              width: 52, height: 52, borderRadius: 9, background: 'var(--accent-dim)',
              border: '1px solid var(--border)', display: 'flex', alignItems: 'center',
              justifyContent: 'center', fontWeight: 800, color: 'var(--accent)', fontSize: 18,
            }}>AF</div>
            <div>
              <div style={{ fontSize: 17, fontWeight: 700 }}>AstraForge 星铸 v{about?.version || '0.2.10'}</div>
              <div className="hint">深度相机扫描工作站 · 模块化架构 · 支持 OTA 热更新</div>
            </div>
          </div>
          <div className="stat"><span className="k">许可协议</span><span className="v">{about?.license || 'Apache-2.0'}</span></div>
          <div className="stat"><span className="k">模块数量</span><span className="v">{modEntries.length}</span></div>
          <div className="hint" style={{ marginTop: 9 }}>
            For Orbbec Astra devices. Not affiliated with Orbbec.
          </div>
        </div>

        <div className="card">
          <h3>模块版本（可单独更新）</h3>
          <div style={{ maxHeight: 210, overflowY: 'auto', marginTop: 6 }}>
            {modEntries.length === 0 && <div className="hint">（读取中…）</div>}
            {modEntries.map(([n, v]) => (
              <div className="stat" key={n}>
                <span className="k" style={{ fontFamily: 'Consolas, monospace' }}>{n}</span>
                <span className="v">v{v}</span>
              </div>
            ))}
          </div>
          <div className="hint" style={{ marginTop: 8 }}>core/ 稳定层不随模块更新；模块可经 GitHub OTA 单独热替换。</div>
        </div>

        <div className="card">
          <h3>反馈与求助</h3>
          <div className="hint" style={{ marginBottom: 9 }}>
            遇到问题：走下方任一通道即可——邮件已自动附带诊断信息（也可先「复制诊断信息」自留）。驱动/设备问题建议连同操作系统版本一起说明。
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            <button className="btn" onClick={copyDiag} style={{ justifyContent: 'flex-start' }}>
              {copied ? '✓ 已复制诊断信息' : '复制诊断信息'}
            </button>
            <button className="btn" onClick={mailto} style={{ justifyContent: 'flex-start' }}>
              <Mail size={14} /> 邮件反馈（自动附诊断信息）
            </button>
            <button className="btn" onClick={() => showToast('GitHub 仓库待建立——建立后此处给 Issue/PR 链接')}
              style={{ justifyContent: 'flex-start' }}>
              <Upload size={14} /> GitHub Issue / PR
            </button>
            <button className="btn" onClick={() => showToast('也可把诊断信息贴给 DSH / WorkBuddy / GPT 等 AI 助手求解')}
              style={{ justifyContent: 'flex-start' }}>
              AI 求助（DSH / WorkBuddy / GPT）
            </button>
          </div>
        </div>

        <div className="card">
          <h3>声明</h3>
          <div className="hint" style={{ lineHeight: 1.9 }}>
            本软件按 <b>Apache-2.0</b> 许可开源发布（详见随附 LICENSE 文件）。<br />
            修改设备固件/参数存在风险，操作请谨慎；<b>本软件与 Orbbec 官方无关联</b>。<br />
            社区复活方案基于 USB 逆向实现，不保证兼容所有设备与系统版本。<br /><br />
            热能建议：连续扫描时注意设备散热；长时间不用请关闭软件（设备随软件一同下线，红外不空照）。
          </div>
        </div>
      </div>
    </div>
  )
}
