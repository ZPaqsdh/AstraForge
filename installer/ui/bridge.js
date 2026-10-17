/* AstraForge 星铸 · 安装器/卸载器 Python 桥
 * 注入方式：build_ui.py 把本文件追加到 UI 草稿的 </script> 之后（草稿本体不改）。
 * 作用：把草稿里的"演示行为"换成真实行为（环境检测 / 真目录浏览 / 真安装卸载）。
 * 无桥时（浏览器直接打开草稿）自动退回草稿原行为，方便继续做设计评审。
 */
(function () {
  'use strict';
  var MODE = document.getElementById('pg-home') ? 'uninstall' : 'install';
  var B = null, BOOT = null;
  var $ = function (id) { return document.getElementById(id); };
  var Q = function (sel) { return document.querySelector(sel); };
  var S = { sep: '\\', dir: '', version: '', mode: 'fresh', installed: null };

  /* 隐藏"设计稿说明"块（真实运行时不需要） */
  var note = Q('.page-note'); if (note) note.style.display = 'none';

  /* ---------------- 工具 ---------------- */
  function setStage(text) { var t = $('stagetext') || $('stageText'); if (t) t.textContent = text; }
  function setPct(p) {
    var b = $('progbar') || $('barFill');
    if (b) { b.style.width = Math.max(0, Math.min(100, p)) + '%'; }
    var n = $('pctNum'); if (n) n.textContent = Math.round(p);
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>]/g, function (c) { return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]; }); }
  function fmtSize(kb) { return kb > 1048576 ? (kb / 1048576).toFixed(2) + ' GB' : Math.round(kb / 1024) + ' MB'; }

  /* ---------------- 与 Python 对话 ---------------- */
  function boot() {
    if (typeof QWebChannel === 'undefined' || !window.qt || !qt.webChannelTransport) return false;
    new QWebChannel(qt.webChannelTransport, function (ch) {
      B = ch.objects.bridge;
      B.bootstrap(function (json) { BOOT = JSON.parse(json); onBoot(); });
    });
    return true;
  }

  /* Python → JS 回调（由 setup_main.py 调 runJavaScript 触发） */
  window.__afProgress = function (p, s) { setStage(s); setPct(p); };
  window.__afFailed = function (msg, detail) {
    var e = Q('#pg-error .errs'); if (e) e.innerHTML = esc(msg).replace(/\n/g, '<br>');
    var d = Q('#pg-error .errdetail'); if (d) d.textContent = detail || '';
    if (typeof go === 'function') go('pg-error');
  };
  window.__afDone = function (ok, msg, dir) {
    S.dir = dir || S.dir;
    if (MODE === 'install') {
      if (!ok) {
        if (String(msg || '').indexOf('取消') >= 0) return;    /* 用户已主动取消：停留在原页 */
        if (typeof window.__afFailed === 'function') window.__afFailed(msg || '安装失败（详情见日志）', '');
        return;
      }
      var t = $('doneTitle');
      var title = { upgrade: '升级完成', repair: '修复完成', downgrade: '降级完成', clean: '安装完成' }[S.mode] || '安装完成';
      if (t) t.textContent = title;
      var ds = $('doneSub');
      if (ds && BOOT && BOOT.version) ds.textContent = 'AstraForge 星铸 v' + BOOT.version + ' 已就绪，插入深度相机即可开始扫描';
      if (typeof go === 'function') go('pg-done');
    } else {
      if (typeof setState === 'function') setState('done');
      var tip = $('doneTip'); if (tip) tip.innerHTML = esc(msg || '卸载完成');
    }
  };

  /* ---------------- 软件运行中拦截（更新前需关闭） ---------------- */
  function gateRunning(proceed) {
    if (!B) { proceed(); return; }
    B.checkRunning(function (json) {
      var r = {}; try { r = JSON.parse(json); } catch (e) {}
      if (r.running) {
        window.__afPendingStart = proceed;
        if (typeof openOverlay === 'function') openOverlay('ov-running');
      } else { proceed(); }
    });
  }
  window.__afContinueRunning = function () {
    if (B) B.killApp();
    if (typeof closeOverlay === 'function') closeOverlay('ov-running');
    var f = window.__afPendingStart; window.__afPendingStart = null;
    if (f) setTimeout(f, 900);          /* 给 taskkill 留出释放文件占用的时间 */
  };
  window.__afCancelRunning = function () {
    if (typeof closeOverlay === 'function') closeOverlay('ov-running');
    window.__afPendingStart = null;
  };

  /* ---------------- 相机与驱动检测（异步只读，可重检） ---------------- */
  function redetectCams() {
    var el = $('camtext'), card = $('camcard');
    if (!el) return;
    el.textContent = '正在检测相机与驱动…';
    if (card) card.className = 'checkbar';
    if (!B) { el.textContent = '— 相机检测不可用（跳过）'; return; }
    B.detectCams();                     /* 结果异步经 window.__afCams 回传（PowerShell 约 2~4 秒） */
  }
  window.__afRedetect = redetectCams;
  window.__afDriverWizard = function () { if (typeof openOverlay === 'function') openOverlay('ov-driver'); };
  window.__afOpenZadig = function () {
    if (!B) return;
    B.openDriverTool(function (json) {
      var r = {}; try { r = JSON.parse(json); } catch (e) {}
      if (!r.ok) alert('未找到驱动工具：' + (r.msg || '') + '\n（应位于安装包「驱动工具」目录）');
    });
  };
  window.__afDriverRedetect = function () {
    if (typeof closeOverlay === 'function') closeOverlay('ov-driver');
    redetectCams();
  };
  window.__afCams = function (json) {
    var el = $('camtext'), card = $('camcard');
    if (!el) return;
    var r = {}; try { r = JSON.parse(json); } catch (e) {}
    var rep = camReport(r);
    el.innerHTML = rep.html;
    if (card) card.className = 'checkbar' + (rep.cls ? ' ' + rep.cls : '');
  };
  function camReport(r) {
    if (!r || !r.ok) return { html: '— 相机检测不可用（跳过）', cls: '' };
    var d = r.depth || {}, c = r.color || {};
    var dl, cls = '';
    if (!d.found) { dl = '— 深度相机：未检测到（可先安装软件，插上即用）'; }
    else if (d.state === 'ready') { dl = '✓ 深度相机：就绪 —— 驱动「' + esc(d.service || 'WinUSB') + '」'; }
    else if (d.state === 'conflict') { dl = '⚠ 深度相机：驱动「' + esc(d.service) + '」与 AstraForge 不兼容，需切换为 WinUSB　<span class="mini" onclick="window.__afDriverWizard && window.__afDriverWizard()">打开驱动处理向导</span>'; cls = 'low'; }
    else if (d.state === 'nodriver') { dl = '✗ 深度相机：未检测到驱动 —— 需安装 WinUSB 驱动　<span class="mini" onclick="window.__afDriverWizard && window.__afDriverWizard()">打开驱动处理向导</span>'; cls = 'warn'; }
    else { dl = '⚠ 深度相机：驱动「' + esc(d.service || '?') + '」（未知类型，可能不兼容）'; cls = 'low'; }
    var cl = c.found ? '✓ 彩色相机：就绪（系统自带驱动）' : '— 彩色相机：未检测到（可选）';
    return { html: dl + '<br>' + cl, cls: cls };
  }

  /* ---------------- 已安装页（版本三态 / 残留） ---------------- */
  function fillExists(ins, rel) {
    var t = $('existTitle'), s2 = $('existSub'), vr = $('existVer');
    var ct = $('cardTitle'), cd = $('cardDesc');
    if (rel === 'residual') {
      S.mode = 'clean';
      if (t) t.textContent = '检测到旧安装记录（目录已丢失）';
      if (s2) s2.textContent = '残留位置：' + esc(ins.dir) + '　｜　上次版本 v' + esc(ins.version);
      if (vr) vr.innerHTML = '';
      if (ct) ct.textContent = '清理残留并安装 v' + esc(BOOT.version || '');
      if (cd) cd.textContent = '删除失效的卸载记录与快捷方式，然后按全新安装进行';
      return;
    }
    S.dir = ins.dir;
    $('instPath') && ($('instPath').textContent = S.dir);
    if (t) t.textContent = '检测到 AstraForge 星铸 v' + esc(ins.version) + ' 已安装';
    if (s2) s2.textContent = '当前安装位置：' + esc(ins.dir) + '　｜　上次安装：' + esc(ins.date || '?');
    if (rel === 'old') {
      S.mode = 'upgrade';
      if (vr) vr.innerHTML = '将更新 <b>v' + esc(ins.version) + ' → v' + esc(BOOT.version) + '</b>';
      if (ct) ct.textContent = '立即更新到 v' + esc(BOOT.version);
      if (cd) cd.textContent = '重写程序文件；保留「扫描输出」与设置';
    } else if (rel === 'new') {
      S.mode = 'downgrade';
      if (vr) vr.innerHTML = '本安装包 v' + esc(BOOT.version) + ' 将<b style="color:#c42b1c">降级</b>已装版本';
      if (ct) ct.textContent = '仍要降级为 v' + esc(BOOT.version);
      if (cd) cd.textContent = '不建议：已装版本可能包含本包没有的修复';
    } else {
      S.mode = 'repair';
      if (vr) vr.innerHTML = '与已装版本相同（v' + esc(BOOT.version) + '）';
      if (ct) ct.textContent = '修复安装（覆盖重写）';
      if (cd) cd.textContent = '重写程序文件，不动数据';
    }
  }
  function syncExistsLabel() {
    var map = { upgrade: '立即更新', repair: '修复安装', downgrade: '降级安装', clean: '清理并安装' };
    var b = $('btn-main'); if (b && map[S.mode]) b.textContent = map[S.mode];
  }

  /* ---------------- 安装器：启动时填真实数据 ---------------- */
  function onBoot() {
    if (MODE === 'uninstall') {
      /* 注意：桥给的协议是 {installed: {dir,version,date} | null}（与安装器侧一致）。
         曾误读成平铺的 BOOT.dir/BOOT.found 等字段 → 卸载器永远显示"未找到"、按钮锁死。 */
      var ins = BOOT.installed || null;
      var info = $('homeInfo');
      var badge = Q('.brand .ver');
      if (ins && ins.residual) {
        S.installed = ins;
        if (info) info.innerHTML = '检测到残留安装记录（目录已丢失）：' + esc(ins.dir)
          + '　｜　上次版本 v' + esc(ins.version);
        if (badge) badge.textContent = '残留记录';
        var b0 = $('btn-main'); if (b0) b0.textContent = '清理残留记录';
      } else if (ins) {
        S.installed = ins;
        if (info) {
          info.innerHTML = '安装位置：' + esc(ins.dir) + '　｜　版本 v' + esc(ins.version)
            + '　｜　安装于 ' + esc(ins.date);
        }
        if (badge) badge.textContent = '已安装 v' + ins.version;
        S.dir = ins.dir; S.version = ins.version;
      } else {
        if (info) info.innerHTML = '未找到 AstraForge 的安装记录（可能已被手工删除）。';
        if (badge) badge.textContent = '未安装';
        var b = $('btn-main'); if (b) { b.disabled = true; b.textContent = '无可卸载内容'; }
      }
      return;
    }
    /* 安装器 */
    S.installed = BOOT.installed || null;
    var ver = Q('.brand .ver');
    if (ver && BOOT.version) ver.textContent = 'v' + BOOT.version;
    var ct = $('checktext');
    if (ct) {
      var e = BOOT.env;
      var okc = e.cpu_ok && e.ram_ok;
      ct.innerHTML = '本机检测：' + e.cpu + ' 核 / ' + e.ram + ' GB 内存'
        + (e.gpu ? ' / ' + esc(e.gpu) : '') + (e.gpu_cuda ? '（CUDA 可用）' : '')
        + ' — ' + (okc ? '满足运行要求' : '<b style="color:#9d5d00">低于最低要求（'
          + e.min_cpu + ' 核 / ' + e.min_ram + ' GB），可继续安装但性能不保证</b>');
    }
    var p = $('instPath'), p2 = $('instPath2');
    if (p) p.textContent = BOOT.default_dir;
    if (p2) p2.textContent = BOOT.default_dir;
    S.dir = BOOT.default_dir;
    var ns = $('needSize');
    if (ns && BOOT.payload_kb) ns.textContent = '需 ' + fmtSize(BOOT.payload_kb)
      + ' · 剩余 ' + (BOOT.free_gb >= 0 ? BOOT.free_gb + ' GB' : '?');
    redetectCams();                             /* 相机/驱动异步检测（只读） */
    if (BOOT.installed) {                       /* 已装过 → 走更新/修复/残留页 */
      fillExists(BOOT.installed, BOOT.relation || 'same');
      if (typeof go === 'function') { go('pg-exists'); syncExistsLabel(); }
    }
  }

  /* ---------------- 真实目录浏览（替换草稿的演示数据） ---------------- */
  function realRender() {
    var dl = $('driveList');
    if (!dl) return;
    dl.innerHTML = '<div class="dtitle">此电脑</div>' + (BOOT.drives || []).map(function (d) {
      return '<div class="ditem' + (String(curPath).toUpperCase().indexOf(d) === 0 ? ' sel' : '')
        + '" data-drive="' + d + '">' + diskSvg() + '<span>' + d + '</span></div>';
    }).join('');
    dl.querySelectorAll('.ditem').forEach(function (el) { el.onclick = function () { loadPath(el.dataset.drive); }; });

    B.listDir(curPath, function (json) {
      var r = JSON.parse(json), dirs = r.dirs || [];
      var el = $('dirList');
      el.innerHTML = dirs.length
        ? dirs.map(function (n) {
          return '<div class="diritem' + (selPath === join(curPath, n) ? ' sel' : '') + '" data-name="' + esc(n) + '">'
            + folderSvg() + '<span>' + esc(n) + '</span><span class="arr">双击进入</span></div>';
        }).join('')
        : '<div class="tip" style="padding:14px">（这个文件夹是空的）</div>';
      el.querySelectorAll('.diritem').forEach(function (node) {
        node.onclick = function () { selPath = join(curPath, node.dataset.name); realRender(); };
        node.ondblclick = function () { loadPath(join(curPath, node.dataset.name)); };
      });
      var ai = $('addrInput'); if (ai) ai.value = curPath;
      var bt = $('browseTarget'); if (bt) bt.textContent = finalDirOf(selPath);
    });
  }

  function installOpts() {
    var g = function (id, dflt) { var el = $(id); return el ? el.checked : dflt; };
    return JSON.stringify({ dir: S.dir, desktop: g('optDesk', true), startmenu: g('optStart', true),
      autostart: g('optAuto', false), version: (BOOT && BOOT.version) || '0.0.0' });
  }

  /* ---------------- 接管安装器流程 ---------------- */
  function rebind(id, fn) {
    /* 草稿用 addEventListener 绑了按钮 → 必须换节点才能换行为（保留样式与内容） */
    var el = $(id); if (!el) return null;
    var n = el.cloneNode(true);
    el.parentNode.replaceChild(n, el);
    n.addEventListener('click', fn);
    return n;
  }

  function patchInstaller() {
    /* 目录浏览走真实文件系统 */
    renderBrowse = realRender;
    mkNewFolder = function () {
      var inp = $('newFolderName'), name = (inp.value || '').trim();
      if (!name) { alert('请输入文件夹名'); return; }
      if (/[\\/:*?"<>|]/.test(name)) { alert('文件夹名不能包含 \\ / : * ? " < > |'); return; }
      B.mkdir(join(curPath, name), function (json) {
        var r = JSON.parse(json);
        if (!r.ok) { alert('创建失败：' + (r.msg || '')); return; }
        inp.value = ''; selPath = join(curPath, name); realRender();
      });
    };
    browseOK = function () {
      S.dir = finalDirOf(selPath);
      $('instPath').textContent = S.dir;
      if ($('instPath2')) $('instPath2').textContent = S.dir;
      $('footleft').textContent = /^C:\\PROGRAM FILES/i.test(S.dir)
        ? '将请求管理员权限写入 Program Files' : '当前为「仅为我安装」模式（免管理员）';
      closeOverlay('ov-browse');
    };
    var _main = mainAction, _sec = secondary;
    function primaryClick() {
      if (page === 'pg-done') { B.launchApp(S.dir); B.exitSetup(); return; }
      if (page === 'pg-license') { $('agree').checked = true; go('pg-ready'); return; }
      if (page === 'pg-ready' || page === 'pg-custom') { S.mode = 'fresh'; }
      if (page === 'pg-ready' || page === 'pg-custom' || page === 'pg-exists' || page === 'pg-error') {
        gateRunning(function () {
          go('pg-install'); setStage('正在准备安装…'); setPct(0);
          if (S.mode === 'clean' && B) {
            B.cleanResidual(function () { B.startInstall(installOpts()); });
          } else if (B) {
            B.startInstall(installOpts());
          }
        });
        return;
      }
      return _main.apply(null, arguments);
    }
    rebind('btn-main', primaryClick);
    var cardGo = $('cardGo');
    if (cardGo) cardGo.addEventListener('click', function () { if (page === 'pg-exists') primaryClick(); });
    rebind('btn-secondary', function () {
      if (page === 'pg-done') { B.openDoc(S.dir); return; }
      if (page === 'pg-error') { B.exitSetup(); return; }
      if (page === 'pg-install') { openOverlay('ov-cancel'); return; }
      return _sec.apply(null, arguments);
    });
    abortInstall = function () { B.cancelInstall(); closeOverlay('ov-cancel'); go('pg-ready'); };
    handoffUninstall = function () { B.handoffUninstall(); };
    winClose = function () { if (page === 'pg-install') openOverlay('ov-cancel'); else B.exitSetup(); };
    syncFooter();
  }

  /* ---------------- 接管卸载器流程 ---------------- */
  function patchUninstaller() {
    beginUninstall = function () {
      if (S.installed && S.installed.residual) {          /* 残留记录：只清记录，不删文件 */
        setState('running'); setStage('正在清理残留记录…'); setPct(30);
        B.cleanResidual(function (json) {
          var r = {}; try { r = JSON.parse(json); } catch (e) {}
          setPct(100); setState('done'); setStage('完成');
          var tip = $('doneTip');
          if (tip) tip.innerHTML = r.ok ? '残留记录已清理，可关闭本窗口。' : ('清理失败：' + esc(r.msg || ''));
        });
        return;
      }
      setState('running'); setStage('正在准备…'); setPct(0);
      B.startUninstall(!!($('wipe') && $('wipe').checked));
    };
    closeApp = function () { B.exitSetup(); };
    handoffRepair = function () { B.launchRepair(); };
    var _main = mainAction, _sec = secondary;
    rebind('btn-main', function () {
      if (state === 'done') { B.exitSetup(); return; }
      return _main.apply(null, arguments);
    });
    rebind('btn-secondary', function () {
      if (state === 'done') { B.exitSetup(); return; }
      return _sec.apply(null, arguments);
    });
    syncFooter();
  }

  /* ---------------- 标题栏拖动 / 最小化（无边框窗口） ----------------
     注意：B（Python 桥）是**异步**连上的——挂接时不能因为 B 还没到就放弃（拖拽曾因此
     永远没挂上：窗口拖不动）。事件真正触发时桥早已就绪，用到时再判即可。 */
  function patchDrag() {
    var bar = Q('.titlebar'); if (!bar) return;
    var on = false;
    bar.addEventListener('mousedown', function (e) {
      if (e.target && e.target.classList && e.target.classList.contains('wb')) return;  // 窗口按钮不拖
      if (!B) return;
      on = true;
      if (e.preventDefault) e.preventDefault();
      B.dragStart(e.screenX, e.screenY);   // Qt 侧优先 startSystemMove（系统级拖动，更跟手）
    });
    window.addEventListener('mousemove', function (e) { if (on && B) B.dragMove(e.screenX, e.screenY); });
    window.addEventListener('mouseup', function () { if (on) { on = false; if (B) B.dragEnd(); } });
    /* 标题栏「最小化」（草稿标注"由宿主窗口处理"，这里接上） */
    var mb = Q('.wbtns .wb:not(.close)');
    if (mb) mb.addEventListener('click', function () { if (B) B.minimizeWindow(); });
  }

  /* ---------------- 启动 ---------------- */
  if (boot()) {
    if (MODE === 'install') { patchInstaller(); } else { patchUninstaller(); }
    patchDrag();
  }
})();
