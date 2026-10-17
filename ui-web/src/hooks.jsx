// hooks.jsx — 帧流组件 + 轮询 hook（真后端数据通道）
import { useEffect, useRef, useState } from 'react'
import { api } from './api.js'

// 帧流组件：链式加载（上一帧 onLoad 完再拉下一帧，请求永不堆积）
// + 页面隐藏暂停 + 2s 加载保底 + paused 属性（暂停时定格停流）+ onFrame 帧回调（统计显示帧率）
export function FrameImg({ kind, gray, intervalMs = 25, paused = false, onFrame, style, ...rest }) {
  const [src, setSrc] = useState('')
  const nextRef = useRef(() => {})
  const cbRef = useRef(onFrame)
  cbRef.current = onFrame
  useEffect(() => {
    let alive = true
    let timer = null        // 帧间隔
    let failsafe = null     // 加载保底
    const schedule = (delay) => {
      if (!alive) return
      clearTimeout(timer)
      clearTimeout(failsafe)
      if (paused) return                          // 暂停：定格当前帧，不再拉流
      timer = setTimeout(() => {
        if (!alive) return
        if (document.hidden) { schedule(400); return }
        setSrc(api.frameUrl(kind, gray))
        failsafe = setTimeout(() => schedule(intervalMs), 2000)   // 2s 没加载完也继续
      }, delay)
    }
    nextRef.current = (delay) => schedule(delay)
    schedule(0)
    const onVis = () => { if (!document.hidden) schedule(0) }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      alive = false
      clearTimeout(timer)
      clearTimeout(failsafe)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [kind, gray, intervalMs, paused])
  const done = () => {
    if (cbRef.current) { try { cbRef.current() } catch (e) {} }
    nextRef.current(intervalMs)
  }
  return (
    <img src={src} alt={kind} onLoad={done} onError={done}
      style={{ display: 'block', borderRadius: 9, ...style }} {...rest} />
  )
}

// 轮询 hook：定期拉数据（默认 1s）
export function usePoll(fn, intervalMs = 1000, enabled = true) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    if (!enabled) return
    let alive = true
    const tick = async () => {
      try {
        const d = await fn()
        if (alive) { setData(d); setErr(null) }
      } catch (e) {
        if (alive) setErr(String(e.message || e))
      }
    }
    tick()
    const id = setInterval(tick, intervalMs)
    return () => { alive = false; clearInterval(id) }
  }, [fn, intervalMs, enabled])
  return [data, err]
}
