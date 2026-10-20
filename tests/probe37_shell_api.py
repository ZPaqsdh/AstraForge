# -*- coding: utf-8 -*-
"""probe37：shell v1 全 API 同进程真机验证（真 pipeline + 真设备）。

绕开沙箱代理：同进程 socket 直连本地 server，逐 API 打一遍。
覆盖：状态/帧流/查值/统计/采集/转台/标定/测距/设置/性能/关于/诊断/收尾。
"""
import json
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import shell

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name} {detail}")


def req(port, method, path, body=None):
    """同进程 socket 请求（零代理）。返回 (status, headers, body_bytes)。"""
    s = socket.create_connection(("127.0.0.1", port), timeout=25)
    if method == "GET":
        s.sendall(f"GET {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n".encode())
    else:
        data = json.dumps(body or {}).encode()
        s.sendall((f"POST {path} HTTP/1.0\r\nHost: 127.0.0.1\r\n"
                   f"Content-Type: application/json\r\nContent-Length: {len(data)}\r\n\r\n"
                   ).encode() + data)
    buf = b""
    while True:
        try:
            c = s.recv(65536)
        except socket.timeout:
            break
        if not c:
            break
        buf += c
        if b"\r\n\r\n" in buf:
            head, _, rest = buf.partition(b"\r\n\r\n")
            cl = 0
            for ln in head.split(b"\r\n"):
                if ln.lower().startswith(b"content-length:"):
                    cl = int(ln.split(b":")[1])
            if len(rest) >= cl:
                break
    s.close()
    head, _, body = buf.partition(b"\r\n\r\n")
    status = int(head.split(b" ")[1])
    return status, head.decode("utf-8", "replace"), body


def jbody(b):
    try:
        return json.loads(b)
    except Exception:
        return None


def main():
    print("=" * 60)
    print("probe37：shell v1 全 API 真机验证")
    print("=" * 60)

    print("\n[1] 装配真管线（device 连设备）...")
    pipe = shell.build_pipeline()
    time.sleep(3)                      # 等 device.start 连上 + 首帧
    bridge = shell.Bridge(pipe)
    port, httpd = shell.start_server(ROOT / "ui-web" / "dist", bridge)
    print(f"    server port={port} 自检={shell._selfcheck(port)}")

    print("\n[2] GET 类 API:")
    st, _, b = req(port, "GET", "/api/state")
    d = jbody(b).get("data", {}) if jbody(b) else {}
    check("state", st == 200 and d.get("device", {}).get("streaming"),
          f"device={d.get('device')}")
    check("state.rgb", "已连接" in str(d.get("rgb")), str(d.get("rgb")))
    check("state.modules", len(d.get("modules", {})) >= 9,
          f"{len(d.get('modules', {}))} 个模块")
    check("state.gpu", d.get("gpu") is not None, str(d.get("gpu", {}).get("note", ""))[:40])

    st, _, b = req(port, "GET", "/api/stats")
    d = jbody(b).get("data", {})
    check("stats.frames>0", d.get("frames", 0) > 0, f"frames={d.get('frames')}")
    time.sleep(2.2)
    st, _, b = req(port, "GET", "/api/stats")
    d2 = jbody(b).get("data", {})
    check("stats.fps>0", d2.get("fps", 0) > 1, f"fps={d2.get('fps')}")

    st, _, b = req(port, "GET", "/api/logs?n=5")
    check("logs", st == 200 and len(jbody(b).get("data", {}).get("logs", [])) >= 3)

    st, _, b = req(port, "GET", "/api/about")
    d = jbody(b).get("data", {})
    check("about", d.get("license") == "Apache-2.0" and len(d.get("modules", {})) >= 9)

    st, _, b = req(port, "GET", "/api/diag")
    check("diag", st == 200 and jbody(b)["data"].get("os"))

    st, _, b = req(port, "GET", "/api/list_dirs")
    check("list_dirs", st == 200 and "dirs" in jbody(b)["data"])

    st, _, b = req(port, "GET", "/api/settings")
    check("settings", st == 200 and "export_dir" in jbody(b)["data"])

    st, _, b = req(port, "GET", "/api/serial_ports")
    d = jbody(b).get("data", {})
    check("serial_ports(不可用也正常)", st == 200,
          f"ok={d.get('ok')} {str(d.get('error', ''))[:40]}")

    print("\n[3] 帧流:")
    st, h, b = req(port, "GET", "/api/frame?kind=depth")
    check("frame/depth JPEG", st == 200 and b[:2] == b"\xff\xd8",
          f"{len(b)} bytes")
    st, h, b = req(port, "GET", "/api/frame?kind=rgb")
    check("frame/rgb JPEG", st == 200 and b[:2] == b"\xff\xd8", f"{len(b)} bytes")
    st, h, b = req(port, "GET", "/api/frame?kind=depth&gray=1")
    check("frame/depth 灰度", st == 200 and len(b) > 1000)
    # 缓存降载：80ms 内二次请求应同 bytes
    st, _, b2 = req(port, "GET", "/api/frame?kind=depth")
    check("frame 缓存降载", b2 == b)

    print("\n[4] 像素查值 + 测距:")
    st, _, b = req(port, "GET", "/api/pixel?x=320&y=240")
    d = jbody(b).get("data", {})
    check("pixel 中心", d.get("v", 0) > 0, f"v={d.get('v')} mm={d.get('mm')}")
    st, _, b = req(port, "POST", "/api/measure",
                   {"x1": 300, "y1": 240, "x2": 340, "y2": 240})
    d = jbody(b).get("data", {})
    check("measure", d.get("ok"), f"dist={d.get('dist_mm')}mm err={d.get('error')}")

    print("\n[5] 采集:")
    st, _, b = req(port, "POST", "/api/save_snapshot")
    d = jbody(b).get("data", {})
    check("save_snapshot", d.get("ok"), d.get("path", d.get("error")))
    st, _, b = req(port, "POST", "/api/export_cloud")
    d = jbody(b).get("data", {})
    check("export_cloud", d.get("ok"), d.get("path", d.get("error")))
    st, _, b = req(port, "POST", "/api/toggle_continuous")
    d = jbody(b).get("data", {})
    check("toggle_continuous 开", d.get("on"))
    time.sleep(2.5)
    st, _, b = req(port, "POST", "/api/toggle_continuous")
    d = jbody(b).get("data", {})
    check("toggle_continuous 关", not d.get("on"))

    print("\n[6] 转台:")
    st, _, b = req(port, "POST", "/api/tt_shoot", {"step_deg": 15})
    d = jbody(b).get("data", {})
    check("tt_shoot", d.get("ok"), f"count={d.get('count')}")
    st, _, b = req(port, "GET", "/api/tt_status")
    check("tt_status", jbody(b)["data"].get("count") == 1)
    st, _, b = req(port, "POST", "/api/tt_finish")
    d = jbody(b).get("data", {})
    check("tt_finish", d.get("ok"), str(d.get("dir"))[:60])

    print("\n[7] 标定 + 设置 + 性能:")
    st, _, b = req(port, "POST", "/api/calib_sample", {"known_mm": 500, "roi": 40})
    d = jbody(b).get("data", {})
    check("calib_sample", d.get("ok"), f"median={d.get('median')} k={d.get('k')}")
    st, _, b = req(port, "POST", "/api/set_disp_range", {"lo": 100, "hi": 2000})
    check("set_disp_range", jbody(b)["data"].get("ok"))
    st, _, b = req(port, "POST", "/api/set_perf_mode", {"mode": "perf"})
    d = jbody(b).get("data", {})
    check("set_perf_mode perf", d.get("ok"), f"workers={d.get('workers')}")
    st, _, b = req(port, "POST", "/api/set_perf_mode", {"mode": "turbo"})
    d = jbody(b).get("data", {})
    check("set_perf_mode turbo(全核)", d.get("ok"), f"workers={d.get('workers')}")

    print("\n[8] 融合进度接口（无任务时）:")
    st, _, b = req(port, "GET", "/api/fuse_progress")
    check("fuse_progress 空态", st == 200)

    print("\n[9] 收尾（关红外）:")
    pipe.stop_all()
    time.sleep(1.0)
    dev = pipe.get("device")
    link = getattr(dev, "link", None)
    check("ir_off 已执行", link is None or not link.stream_on)
    logs = shell.Bridge._logs
    # 兼容 2 元组 (m, ok) 与 3 元组 (ts, m, ok)：消息固定在倒数第 2 位
    off_logs = [e[-2] for e in logs
                if "关激光" in str(e[-2]) or "停流" in str(e[-2])]
    check("关红外日志", len(off_logs) >= 2, str(off_logs[:2]))

    print("\n" + "=" * 60)
    print(f"结果: {len(PASS)} 过 / {len(FAIL)} 挂")
    if FAIL:
        print("失败项:", FAIL)
    print("=" * 60)
    httpd.shutdown()


if __name__ == "__main__":
    main()
