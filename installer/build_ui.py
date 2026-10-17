# -*- coding: utf-8 -*-
"""把 UI 草稿（设计唯一源）+ bridge.js 合成安装器/卸载器的真实页面。

    python installer/build_ui.py

源： drafts/AstraForge安装器_UI草稿_v3.html（7 页，定稿）
     drafts/AstraForge卸载器_UI草稿_v1.html（4 状态，定稿）
出： ui/installer.html / ui/uninstaller.html（草稿原样 + 末尾注入 bridge.js）
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DRAFTS = HERE / 'drafts'
OUT = HERE / 'ui'
PAIRS = [
    ('AstraForge安装器_UI草稿_v3.html', 'installer.html'),
    ('AstraForge卸载器_UI草稿_v1.html', 'uninstaller.html'),
]

OUT.mkdir(parents=True, exist_ok=True)
for src_name, dst_name in PAIRS:
    src = DRAFTS / src_name
    if not src.exists():
        print(f'!! 缺草稿：{src}')
        sys.exit(1)
    html = src.read_text(encoding='utf-8')
    if '由 build_ui.py 注入' in html:          # 防重注：只认注入标记，不认普通提及
        print(f'   {dst_name}: 草稿已被注入过，跳过')
        continue
    inject = ('\n<!-- ⬇⬇ 真实安装器桥（由 build_ui.py 注入；草稿本体不改） ⬇⬇ -->\n'
              '<style>\n'
              '  /* 草稿是"设计稿对比页"（居中卡片 + 外边距）；真实窗口里要铺满 */\n'
              '  html,body{height:100%;overflow:hidden;padding:0!important;margin:0!important;'
              'display:block!important;background:#eef1f5}\n'
              '  .installer{width:100%!important;height:100vh;border-radius:0!important;'
              'box-shadow:none!important}\n'
              '  .page-note{display:none!important}\n'
              '</style>\n'
              '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>\n'
              '<script src="bridge.js"></script>\n')
    if '</body>' in html:
        html = html.replace('</body>', inject + '</body>')
    else:
        html += inject
    (OUT / dst_name).write_text(html, encoding='utf-8')
    print(f'✓ {dst_name}  ←  {src_name}（{len(html)} 字节）')

print('完成。生成物在', OUT)
