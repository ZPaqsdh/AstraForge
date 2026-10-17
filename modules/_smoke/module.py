# -*- coding: utf-8 -*-
"""冒烟模块：验证 pipeline 外置加载/事件/启停全链路。"""
from core.contracts import ModuleContext


class SmokeModule:
    name = "_smoke"
    version = "0.1.0"

    def setup(self, ctx: ModuleContext):
        self.ctx = ctx
        ctx.bus.subscribe("smoke.ping", self._on_ping)
        ctx.log("[smoke] setup ok", True)

    def start(self):
        self.ctx.bus.publish("smoke.ping", {"from": "start"})
        self.ctx.log("[smoke] start ok", True)

    def stop(self):
        self.ctx.log("[smoke] stop ok", True)

    def _on_ping(self, payload):
        self.ctx.log(f"[smoke] 收到 ping: {payload}", True)
