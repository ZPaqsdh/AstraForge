#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe32_updater.py — updater 模块 OTA 全链路验证（M7，mock 源）

用临时目录造"远端"（manifest.json + 模块 zip），以 file:// 作更新源：
  ① check 发现 _smoke 0.1.0→0.9.9
  ② update 成功：文件替换 + 版本生效 + 备份存在
  ③ 坏 SHA256 用例：拒绝安装 + 原模块不动
  ④ 恢复 _smoke 到原版 + 清理
"""
import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))

from core.pipeline import Pipeline
from core.events import EventBus
from core.contracts import ModuleContext

SRC = Path(tempfile.gettempdir()) / "af_ota_mock"
logs = []


def make_zip(zip_path, files):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return hashlib.sha256(zip_path.read_bytes()).hexdigest()


def main():
    # ---- 造 mock 远端 ----
    if SRC.exists():
        shutil.rmtree(SRC)
    SRC.mkdir(parents=True)
    smoke_ver = "0.9.9"
    smoke_py = f'''# -*- coding: utf-8 -*-
class SmokeModule:
    name = "_smoke"
    version = "{smoke_ver}"
    def setup(self, ctx):
        self.ctx = ctx
        ctx.log(f"[smoke] setup v{smoke_ver}", True)
    def start(self):
        pass
    def stop(self):
        pass
'''
    smoke_mj = json.dumps({"name": "_smoke", "version": smoke_ver,
                           "entry": "module.py:SmokeModule", "depends_on": []},
                          ensure_ascii=False, indent=2)
    sha_smoke = make_zip(SRC / "_smoke-0.9.9.zip",
                         {"module.py": smoke_py, "module.json": smoke_mj})
    # fusion 坏哈希用例：包是真的，manifest 哈希写错
    sha_fusion = make_zip(SRC / "fusion-1.0.1.zip", {
        "module.json": json.dumps({"name": "fusion", "version": "1.0.1",
                                   "entry": "module.py:FusionModule",
                                   "depends_on": []}),
        "module.py": "# fake new fusion\nfrom core.contracts import ModuleContext\n"
                     "class FusionModule:\n    name='fusion'\n    version='1.0.1'\n"
                     "    def setup(self,c): pass\n    def start(self): pass\n"
                     "    def stop(self): pass\n"})
    man = {
        "app": "AstraForge", "version": "0.2.0",
        "modules": {
            "_smoke": {"version": smoke_ver,
                       "url": (SRC / "_smoke-0.9.9.zip").as_uri(),
                       "sha256": sha_smoke},
            "fusion": {"version": "1.0.1",
                       "url": (SRC / "fusion-1.0.1.zip").as_uri(),
                       "sha256": "0" * 64},          # 故意错
        }}
    (SRC / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print(f"① mock 远端就绪: {SRC}", flush=True)

    # ---- 装配 ----
    bus = EventBus()
    pipe = Pipeline(ROOT, bus)
    pipe.load_all_modules()
    ctx = ModuleContext(bus=bus, device=None,
                        settings={"update_source": SRC.as_uri()},
                        log=lambda m, ok: logs.append((m, ok)),
                        data_dir=ROOT / 'data', root_dir=ROOT)
    pipe.setup_all(ctx)
    up = pipe.get("updater")
    assert up is not None, "updater 未加载"

    # ② check
    chk = up.check()
    print(f"② check: 发现 {len(chk['updates'])} 个可更新 {list(chk['updates'])}"
          f"（error={chk['error']}）", flush=True)
    assert "_smoke" in chk["updates"] and "fusion" in chk["updates"], "应发现两个更新"

    # ③ 坏哈希拒绝（fusion）
    ok_f, msg_f = up.update("fusion")
    fus = json.loads((ROOT / "modules/fusion/module.json").read_text(encoding="utf-8"))
    print(f"③ 坏哈希用例: ok={ok_f} msg={msg_f[:40]}… fusion 版本={fus['version']}", flush=True)
    assert not ok_f and "SHA256" in msg_f and fus["version"] == "1.0.0"

    # ④ 正常更新（_smoke）
    ok_s, msg_s = up.update("_smoke")
    smk = json.loads((ROOT / "modules/_smoke/module.json").read_text(encoding="utf-8"))
    baks = list((ROOT / "modules/.backup").glob("_smoke-*"))
    print(f"④ 更新 _smoke: ok={ok_s} 新版本={smk['version']} 备份={len(baks)}个", flush=True)
    assert ok_s and smk["version"] == "0.9.9" and baks, "更新/备份异常"

    # 更新后 check 应不再报 _smoke
    chk2 = up.check()
    assert "_smoke" not in chk2["updates"], "更新后不应再报 _smoke"
    print(f"   复查: 剩 {list(chk2['updates'])}", flush=True)

    # ⑤ 恢复 _smoke（用备份还原） + 清理
    bak = sorted(baks)[-1]
    shutil.rmtree(ROOT / "modules/_smoke", ignore_errors=True)
    shutil.copytree(bak, ROOT / "modules/_smoke")
    smk2 = json.loads((ROOT / "modules/_smoke/module.json").read_text(encoding="utf-8"))
    shutil.rmtree(ROOT / "modules/.backup", ignore_errors=True)
    shutil.rmtree(SRC, ignore_errors=True)
    print(f"⑤ 已恢复 _smoke={smk2['version']}，清理完成", flush=True)
    assert smk2["version"] == "0.1.0"

    print("UPDATER MODULE OK", flush=True)


if __name__ == "__main__":
    main()
