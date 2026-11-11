"""FastAPI 入口。

两个跟国内网络有关的处理：
  1. /docs 的 Swagger 静态资源默认走 jsdelivr，国内拉不下来会白屏 → 换成国内 CDN
  2. 额外提供一个零依赖的首页 /，方便演示和截图（不加载任何外部资源）
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

from app.api.routes import router
from app.config import get_settings
from app.services import db, llm

log = logging.getLogger("app")

SWAGGER_JS = "https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.17.14/swagger-ui-bundle.js"
SWAGGER_CSS = "https://cdn.bootcdn.net/ajax/libs/swagger-ui/5.17.14/swagger-ui.css"

INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>campus-kb-agent</title>
<style>
 body{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;max-width:760px;margin:60px auto;padding:0 20px;color:#1f2328}
 h1{font-size:22px;margin-bottom:4px}
 p.sub{color:#656d76;margin-top:0}
 textarea{width:100%;height:80px;padding:10px;font-size:15px;border:1px solid #d0d7de;border-radius:6px;box-sizing:border-box;font-family:inherit}
 button{margin-top:10px;padding:8px 18px;font-size:15px;border:0;border-radius:6px;background:#1f6feb;color:#fff;cursor:pointer}
 button:disabled{opacity:.6;cursor:default}
 #out{margin-top:20px;white-space:pre-wrap;line-height:1.7;font-size:15px}
 #meta{margin-top:10px;color:#656d76;font-size:13px}
</style>
</head>
<body>
<h1>campus-kb-agent</h1>
<p class="sub">课程资料问答 · 输入问题，直接得到答案</p>
<textarea id="q" placeholder="例如：第三章讲了什么？"></textarea>
<button id="go" onclick="ask()">提问</button>
<div id="out"></div>
<div id="meta"></div>
<div id="src"></div>
<script>
async function ask(){
  var q = document.getElementById('q').value.trim();
  if(!q) return;
  var btn = document.getElementById('go');
  btn.disabled = true;
  document.getElementById('out').textContent = '思考中…';
  document.getElementById('meta').textContent = '';
  document.getElementById('src').innerHTML = '';
  try{
    var r = await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({question: q})});
    var d = await r.json();
    if(!r.ok){
      document.getElementById('out').textContent = '失败：' + (d.detail || r.status);
    } else {
      document.getElementById('out').textContent = d.answer;
      document.getElementById('meta').textContent =
        '耗时 ' + d.latency_ms + ' ms · token ' + d.token_in + '/' + d.token_out + ' · 记录 #' + d.query_id
        + (d.status === 'degraded' ? ' · 模型不可用，已降级为原文摘录' : '');
      renderSources(d.sources || []);
    }
  } catch(e){
    document.getElementById('out').textContent = '网络错误：' + e;
  } finally {
    btn.disabled = false;
  }
}

function renderSources(list){
  var box = document.getElementById('src');
  if(!list || !list.length){ box.innerHTML = ''; return; }
  var html = '<div style="margin-top:18px;font-size:13px;color:#656d76">出处</div>';
  list.forEach(function(s){
    var page = s.page_no ? (' · 第 ' + s.page_no + ' 页') : '';
    html += '<div style="margin-top:8px;padding-left:10px;border-left:3px solid #d0d7de">'
         +  '<div style="font-size:13px;color:#1f2328">[' + s.index + '] 《' + s.title + '》' + page
         +  ' <span style="color:#656d76">相似度 ' + Number(s.score).toFixed(3) + '</span></div>'
         +  '<div style="font-size:13px;color:#656d76;margin-top:2px">' + s.snippet + '…</div>'
         +  '</div>';
  });
  box.innerHTML = html;
}
</script>
</body>
</html>"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-5s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    db.init_pool()
    llm.configure_breaker(
        settings.breaker_failure_threshold,
        settings.breaker_recovery_seconds,
    )
    log.info("服务启动完成")
    yield
    db.close_pool()
    log.info("服务已关闭")


app = FastAPI(
    title="campus-kb-agent",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
app.include_router(router)


@app.get("/docs", include_in_schema=False)
def swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url=SWAGGER_JS,
        swagger_css_url=SWAGGER_CSS,
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)
