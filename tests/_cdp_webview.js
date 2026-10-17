// _cdp_webview.js — WebView2 CDP 诊断（参数化端口 + console 抓取 + 求值）
// 用法：node _cdp_webview.js <port> <js表达式>
const HTTP = require('node:http')

function httpGet(url) {
  return new Promise((res, rej) => {
    HTTP.get(url, (r) => { let d = ''; r.on('data', (c) => (d += c)); r.on('end', () => res(d)) }).on('error', rej)
  })
}

;(async () => {
  const port = process.argv[2] || '9333'
  const expr = process.argv[3] || 'document.readyState'
  const list = JSON.parse(await httpGet(`http://127.0.0.1:${port}/json`))
  console.log('targets:', list.map(t => `${t.type}:${(t.url || '').slice(0, 60)}`).join(' | '))
  const page = list.find((t) => t.type === 'page')
  if (!page) { console.log('无 page target'); process.exit(1) }
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const events = []
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
    else if (m.method === 'Runtime.consoleAPICalled') {
      events.push('CONSOLE[' + m.params.type + '] ' + (m.params.args || []).map(a => a.value ?? a.description ?? '').join(' ').slice(0, 300))
    } else if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails || {}
      events.push('EXCEPTION: ' + (d.exception?.description || d.text || '').slice(0, 400))
    }
  })
  await new Promise((r, j) => { ws.addEventListener('open', r); ws.addEventListener('error', j) })
  const call = (method, params) => new Promise((r) => {
    const i = ++id
    pending.set(i, r)
    ws.send(JSON.stringify({ id: i, method, params }))
  })
  await call('Runtime.enable')
  await new Promise(r => setTimeout(r, 2500))
  const res = await call('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
  console.log('=== console/异常事件 ===')
  console.log(events.length ? events.join('\n') : '(无)')
  console.log('=== 求值结果 ===')
  if (res.result && res.result.exceptionDetails) {
    console.log('ERR:', JSON.stringify(res.result.exceptionDetails.exception || res.result.exceptionDetails).slice(0, 500))
  } else {
    const v = res.result && res.result.result ? res.result.result.value : undefined
    console.log(typeof v === 'string' ? v : JSON.stringify(v))
  }
  ws.close()
})().catch((e) => { console.error('FATAL', e.message); process.exit(1) })
