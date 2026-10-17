# -*- coding: utf-8 -*-
"""事件总线：模块解耦的唯一通道（线程安全）。

topic 约定：
  depth.frame      -> DepthFrame
  rgb.frame        -> RgbFrame
  device.status    -> DeviceStatus
  pointcloud.ready -> PointCloud
  module.log       -> (str, bool)
"""
import threading


class EventBus:
    def __init__(self):
        self._subs: dict[str, list] = {}
        self._lock = threading.Lock()

    def subscribe(self, topic: str, fn):
        with self._lock:
            self._subs.setdefault(topic, []).append(fn)
        return lambda: self.unsubscribe(topic, fn)

    def unsubscribe(self, topic: str, fn):
        with self._lock:
            if topic in self._subs and fn in self._subs[topic]:
                self._subs[topic].remove(fn)

    def publish(self, topic: str, payload=None):
        with self._lock:
            subs = list(self._subs.get(topic, ()))
        for fn in subs:
            try:
                fn(payload)
            except Exception as e:                 # 单模块异常不拖垮总线
                self.publish("module.log", (f"事件 {topic} 处理失败: {e}", False))
