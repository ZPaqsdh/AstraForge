# -*- coding: utf-8 -*-
"""probe75 —— 自动更新检测（启动即检 / 12h 周期 / 关闭重置 / 失败静默）。

老大 2026-10-20 口径：
  • 打开客户端就检测当前版本 vs 上游
  • 运行期每 12 小时检测一次
  • 软件关闭后重置 → 下次启动重新计时（**不落盘**）
  • 失败不打扰，连续多次才暴露

用法：python tests/probe75_update_watch.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["AF_NO_UPDATE_WATCH"] = "1"        # 测 Bridge 时别真联网

import shell  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'✅' if ok else '❌'} {name}" + (f"  [{detail}]" if detail else ""))


class FakeBridge:
    """假上游：可控返回 manifest 或失败，并记录调用次数。"""

    def __init__(self, latest="0.3.9", fail=False):
        self.latest = latest
        self.fail = fail
        self.calls = 0

    def _fetch_update_manifest(self, timeout=6.0):
        self.calls += 1
        if self.fail:
            return None, "RemoteDisconnected: fake"
        return {"latest": self.latest,
                "payload_url": "http://127.0.0.1:1/x.zip",
                "payload_sha256": "",
                "notes_url": "https://example.invalid/releases"}, None


def main():
    print("=== ① 常量：4s 首检 / 12h 周期 ===")
    check("首检延迟 = 4s", shell._UpdateWatcher.FIRST_DELAY == 4.0,
          str(shell._UpdateWatcher.FIRST_DELAY))
    check("周期 = 43200s（12h）", shell._UpdateWatcher.INTERVAL == 43200.0,
          str(shell._UpdateWatcher.INTERVAL))

    print("\n=== ② 首检 + 周期触发（假时钟加速） ===")
    fb = FakeBridge(latest="9.9.9")
    w = shell._UpdateWatcher(fb, first_delay=0.12, interval=0.15)
    _env = os.environ.pop("AF_NO_UPDATE_WATCH", None)   # 本机测试要真启线程
    try:
        started = w.start()
        time.sleep(0.45)
    finally:
        if _env is not None:
            os.environ["AF_NO_UPDATE_WATCH"] = _env
    check("start() 返回已启动", started is True, str(started))
    st = w.snapshot()
    w.stop()
    check("启动后触发了首检", fb.calls >= 1, f"calls={fb.calls}")
    check("周期内又检测了（≥2 次）", fb.calls >= 2, f"calls={fb.calls}")
    check("识别到新版本", st.get("has_update") is True, f"{st.get('current')} → {st.get('latest')}")
    check("记录了检测时间", bool(st.get("checked_at")), str(st.get("checked_at")))
    check("记录了下次检测时间", bool(st.get("next_check_at")), str(st.get("next_check_at")))

    print("\n=== ③ 无更新时不打扰（has_update=False） ===")
    fb2 = FakeBridge(latest=shell.APP_VERSION)
    w2 = shell._UpdateWatcher(fb2, first_delay=0.05, interval=60)
    w2.check_now()
    check("同版本 → has_update=False", w2.snapshot().get("has_update") is False,
          str(w2.snapshot().get("latest")))

    print("\n=== ④ 失败：计数 + 保留上次结果（不清空） ===")
    fb3 = FakeBridge(latest="9.9.9")
    w3 = shell._UpdateWatcher(fb3, first_delay=0.05, interval=60)
    w3.check_now()
    fb3.fail = True
    for _ in range(2):
        w3.check_now()
    st3 = w3.snapshot()
    check("失败计数累加", int(st3.get("fails") or 0) == 2, str(st3.get("fails")))
    check("失败写 error", bool(st3.get("error")), str(st3.get("error"))[:50])
    check("失败不清空已知新版本", st3.get("has_update") is True and st3.get("latest") == "9.9.9",
          f"{st3.get('has_update')} / {st3.get('latest')}")

    print("\n=== ⑤ 关闭后重置（不落盘） ===")
    w4 = shell._UpdateWatcher(FakeBridge(), first_delay=0.05, interval=60)
    fresh = w4.snapshot()
    check("新实例 checked_at 为空（无跨进程记忆）", not fresh.get("checked_at"),
          str(fresh.get("checked_at")))
    check("新实例 has_update=False", fresh.get("has_update") is False)
    import tempfile
    hits = list(Path(tempfile.gettempdir()).glob("AstraForge*update*state*"))
    check("没有写任何更新状态文件", not hits, str(hits[:3]))

    print("\n=== ⑥ 失败静默阈值（<3 次不暴露给 UI） ===")
    bridge = shell.Bridge(None)          # AF_NO_UPDATE_WATCH=1 → 不启线程
    try:
        class Stub:
            def __init__(self, fails):
                self.fails = fails

            def snapshot(self):
                return {"current": shell.APP_VERSION, "latest": "", "has_update": False,
                        "fails": self.fails, "error": "boom", "checked_at": ""}

        bridge._upd_watch = Stub(1)
        s1 = bridge.api_update_state()
        check("第 1 次失败：对 UI 隐藏", s1.get("error") is None and s1.get("error_hidden") is True,
              str(s1.get("error")))
        bridge._upd_watch = Stub(3)
        s3 = bridge.api_update_state()
        check("连续 3 次失败：暴露错误", s3.get("error") == "boom", str(s3.get("error")))
    finally:
        try:
            bridge._upd_watch.stop()
        except Exception:
            pass

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print(f"\n[75] {passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
