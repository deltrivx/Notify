"""Web 控制面板渲染（人用的交互界面）。

设计原则：
- 用户看到的是表单，不是 API 说明；填完点保存即可，保存后服务自动重载生效，无需重启容器
- token / secret 一律不回显明文：password 类型，只提示「已设置（N 位），留空保持不变」
- 命令与自定义 SQL 用 YAML 文本框编辑（灵活、非硬编码）
- 项目可增删改，改完立刻生效

实现说明：
- CSS 作为独立常量字符串，不参与格式化，避免花括号转义地狱
- HTML 用拼接生成，可读性优先
- YAML 文本用 yaml.safe_dump 生成（保证回显格式正确）
"""
from __future__ import annotations

import html

import yaml

LEVELS = ("normal", "warning", "alert")
SOURCE_TYPES = ("file", "sqlite", "http", "none")

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#222;font-size:14px}
header{background:#2b3a55;color:#fff;padding:14px 20px;font-size:18px;font-weight:600}
.wrap{max-width:940px;margin:0 auto;padding:20px}
.msg.ok{background:#e7f6ec;border-left:4px solid #2f9e5f;padding:10px;margin-bottom:16px}
.msg.err{background:#fdeaea;border-left:4px solid #d64b4b;padding:10px;margin-bottom:16px}
section{background:#fff;border:1px solid #e3e6ea;border-radius:8px;padding:16px;margin-bottom:18px}
h2{font-size:16px;margin:0 0 12px}
label{display:block;margin-bottom:12px;font-size:13px;color:#555}
input,select,textarea{width:100%;box-sizing:border-box;padding:8px;border:1px solid #ccd2d9;border-radius:5px;font:14px/1.4 system-ui,sans-serif}
textarea{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;resize:vertical}
button{padding:8px 14px;border:0;border-radius:5px;cursor:pointer;font-size:14px}
.b-save{background:#2f6fed;color:#fff}
.b-test{background:#eef1f6;color:#333}
.b-del{background:#fdeaea;color:#c0392b}
.btns{display:flex;gap:8px;margin-top:8px;flex-wrap:wrap}
.card{border:1px solid #e3e6ea;border-radius:8px;padding:14px;margin-bottom:14px;background:#fcfcfd}
.card-h{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.tag{font-size:12px;background:#eef1f6;border-radius:4px;padding:2px 6px;color:#666}
.empty{color:#888;font-size:14px}
.hint{font-size:12px;color:#888;margin-top:4px}
"""

JS = """
function bodyOf(form){
  const fd = new FormData(form);
  const p = {};
  fd.forEach((v,k)=>{ p[k]=v; });
  // checkbox 未勾选时 FormData 不带该键，显式补 false
  ["enable_notify","enable_cmd"].forEach(k=>{
    const el = form.querySelector('[name="'+k+'"]');
    if(el) p[k] = el.checked ? "true" : "false";
  });
  return p;
}

function postJSON(url, payload){
  return fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}).then(r=>r.text());
}

document.getElementById("f-global").onsubmit = function(e){
  e.preventDefault();
  postJSON("/api/global", bodyOf(this)).then(t=>{ location.reload(); });
};

document.getElementById("f-new").onsubmit = function(e){
  e.preventDefault();
  postJSON("/api/projects", bodyOf(this)).then(t=>{ location.reload(); });
};

document.getElementById("projects").onclick = function(e){
  const b = e.target.closest("button");
  if(!b) return;
  const card = b.closest(".card");
  const name = b.dataset.name;
  if(b.dataset.act==="save"){
    const p = {};
    card.querySelectorAll("input,select,textarea").forEach(el=>{ p[el.name]=el.value; });
    p.name = name;
    postJSON("/api/projects", p).then(t=>{ location.reload(); });
  } else if(b.dataset.act==="test"){
    const p = {};
    card.querySelectorAll("input,select,textarea").forEach(el=>{ p[el.name]=el.value; });
    p.name = name;
    const cmd = prompt("要测试的指令名（留空=help）","");
    p.test_cmd = (cmd===null||cmd.trim()==="") ? "help" : cmd.trim();
    postJSON("/api/test", p).then(t=>{ alert(t); });
  } else if(b.dataset.act==="del"){
    if(!confirm("删除项目「"+name+"」？")) return;
    postJSON("/api/projects/delete",{name:name}).then(t=>{ location.reload(); });
  }
};

document.getElementById("b-reload").onclick = function(){
  fetch("/api/reload",{method:"POST"}).then(r=>r.text()).then(t=>{ location.reload(); });
};
"""


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""))


def _yaml_of(obj) -> str:
    """把 dict 转成可编辑的 YAML 文本（保证回显非空）。"""
    if not obj:
        return ""
    try:
        return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()
    except Exception:
        return str(obj)


def _opt(value, current) -> str:
    return " selected" if str(value) == str(current) else ""


def render(cfg: dict, message: str = "", ok: bool = True) -> str:
    g = cfg.get("global", {}) or {}
    projects = cfg.get("projects", []) or []

    def val(k, d=""):
        return _esc(g.get(k, d) if g.get(k, d) is not None else d)

    def tok_ph(k):
        v = str(g.get(k, "") or "")
        return f"已设置（{len(v)} 位，留空保持不变）" if v else "例如 RELAY_PUSH_TOKEN"

    def checked(k):
        return " checked" if bool(g.get(k, True)) else ""

    level_opts = "".join(
        f'<option value="{_esc(lv)}"{_opt(lv, g.get("min_importance", "normal"))}>{_esc(lv)}</option>' for lv in LEVELS
    )
    st_opts_blank = "".join(f'<option value="{_esc(s)}">{_esc(s)}</option>' for s in SOURCE_TYPES)

    rows = []
    for p in projects:
        name = _esc(p.get("name", ""))
        ptok = str(p.get("token", "") or "")
        cur_st = str(p.get("source_type", "none"))
        st_opts = "".join(
            f'<option value="{_esc(s)}"{_opt(s, cur_st)}>{_esc(s)}</option>' for s in SOURCE_TYPES
        )
        tok_hint = f"已设置（{len(ptok)} 位，留空保持不变）" if ptok else "可选，留空则用全局令牌"
        rows.append(f"""
      <div class="card">
        <div class="card-h"><b>{name}</b><span class="tag">{_esc(p.get("kind", ""))}</span></div>
        <label>项目名（不可改）
          <input name="name" value="{name}" readonly></label>
        <label>监听端口（留空=不监听，仅通知）
          <input name="port" value="{_esc(p.get("port", "") or "")}" inputmode="numeric">
        </label>
        <label>数据源类型
          <select name="source_type">{st_opts}</select></label>
        <label>数据源路径 / URL
          <input name="source_path" value="{_esc(p.get("source_path", ""))}"></label>
        <label>项目级令牌（可选，覆盖全局）
          <input type="password" name="token" placeholder="{_esc(tok_hint)}"></label>
        <label>命令（YAML：指令名: 说明）
          <textarea name="commands_yaml" rows="5">{_esc(_yaml_of(p.get("commands") or {}))}</textarea>
        </label>
        <label>自定义 SQL（YAML，可选：指令名: {{sql: ..., header: [...]}}）
          <textarea name="queries_yaml" rows="5">{_esc(_yaml_of(p.get("queries") or {}))}</textarea>
        </label>
        <div class="btns">
          <button class="b-save" data-act="save" data-name="{name}">保存</button>
          <button class="b-test" data-act="test" data-name="{name}">测试指令</button>
          <button class="b-del" data-act="del" data-name="{name}">删除</button>
        </div>
      </div>""")

    proj_cards = "\n".join(rows) or '<p class="empty">暂无项目，请在下方「添加项目」。</p>'

    msg_html = ""
    if message:
        cls = "ok" if ok else "err"
        msg_html = f'<div class="msg {cls}">{_esc(message)}</div>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Notify 控制面板</title>
<style>{CSS}</style>
</head>
<body>
<header>Notify · 通知与交互中枢</header>
<div class="wrap">
{msg_html}

<section>
<h2>全局设置</h2>
<form id="f-global">
<label>中转地址（公网可达）
<input name="relay_host" value="{val("relay_host")}"></label>
<label>中转端口
<input name="relay_port" value="{val("relay_port", "8181")}" inputmode="numeric"></label>
<label>共享令牌
<input type="password" name="relay_push_token" placeholder="{_esc(tok_ph("relay_push_token"))}"></label>
<label>企微 CorpID（可选）
<input name="wecom_corpid" value="{val("wecom_corpid")}"></label>
<label>企微 AgentID（可选）
<input name="wecom_agentid" value="{val("wecom_agentid")}"></label>
<label>企微 Secret（可选）
<input type="password" name="wecom_secret" placeholder="{_esc(tok_ph("wecom_secret"))}"></label>
<label><input type="checkbox" name="enable_notify"{checked("enable_notify")}> 启用通知</label>
<label><input type="checkbox" name="enable_cmd"{checked("enable_cmd")}> 启用交互指令</label>
<label>最低通知级别
<select name="min_importance">{level_opts}</select></label>
<label>语言
<input name="language" value="{val("language", "zh-CN")}"></label>
<label>时区
<input name="timezone" value="{val("timezone", "Asia/Shanghai")}"></label>
<button class="b-save" type="submit">保存全局设置</button>
<div class="hint">保存后自动重载生效，无需重启容器。</div>
</form>
</section>

<section>
<h2>项目实例（{len(projects)} 个）</h2>
<div id="projects">
{proj_cards}
</div>
</section>

<section>
<h2>添加项目</h2>
<form id="f-new">
<label>项目名
<input name="name" placeholder="例如 nas-status"></label>
<label>类型标识（kind，可自定义）
<input name="kind" placeholder="自定义或 ddns-go / allinssl / istoreos"></label>
<label>监听端口（留空=只通知不监听）
<input name="port" inputmode="numeric" placeholder="例如 8287"></label>
<label>数据源类型
<select name="source_type">{st_opts_blank}</select></label>
<label>数据源路径 / URL
<input name="source_path" placeholder="/data/xxx.db 或 http://..."></label>
<label>项目级令牌（可选，覆盖全局）
<input type="password" name="token" placeholder="可选"></label>
<label>命令（YAML：指令名: 说明）
<textarea name="commands_yaml" rows="4" placeholder="状态: 查看运行状态"></textarea></label>
<label>自定义 SQL（YAML，可选）
<textarea name="queries_yaml" rows="4" placeholder="证书:\n  sql: SELECT domains, end_day FROM cert\n  header: [域名, 剩余天数]"></textarea></label>
<button class="b-save" type="submit">添加项目</button>
</form>
</section>

<section>
<h2>工具</h2>
<div class="btns"><button class="b-test" id="b-reload">重新加载服务</button></div>
<div class="hint">改动未生效时可手动重载。</div>
</section>

<script>{JS}</script>
</body>
</html>"""
