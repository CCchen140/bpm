from __future__ import annotations


def build_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>数据图表</title>
  <style>
    :root{
      --bg:#0f1220;
      --panel:#171a2b;
      --panel2:#1d2033;
      --border:rgba(255,255,255,.10);
      --text:#e7e9f4;
      --muted:rgba(231,233,244,.72);
      --primary:#4992ff;
      --danger:#ff5a6a;
      --shadow:0 10px 30px rgba(0,0,0,.35);
      --radius:10px;
      --btn-h:34px;
      --gap:10px;
      --font: "Microsoft YaHei", system-ui, -apple-system, Segoe UI, sans-serif;
    }
    *{box-sizing:border-box}
    html,body{height:100%}
    body{
      margin:0;
      font-family:var(--font);
      background: radial-gradient(1200px 800px at 10% 0%, #1b1f39 0%, var(--bg) 60%);
      color:var(--text);
      overflow:hidden;
    }
    #app{height:100%;display:flex;flex-direction:column}
    .topbar{
      display:flex;align-items:center;justify-content:space-between;
      padding:12px 14px;border-bottom:1px solid var(--border);
      background:rgba(15,18,32,.6);backdrop-filter:blur(10px);
    }
    .brand{display:flex;align-items:center;gap:10px;min-width:0}
    .brand .title{font-size:14px;font-weight:700}
    .brand .sub{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .btn{
      height:var(--btn-h);
      padding:0 10px;
      border-radius:8px;
      border:1px solid var(--border);
      background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.02));
      color:var(--text);
      display:inline-flex;align-items:center;gap:8px;
      cursor:pointer;user-select:none;
      transition:transform .08s ease, background .2s ease, border-color .2s ease, opacity .2s ease;
    }
    .btn:hover{border-color:rgba(255,255,255,.22);background:linear-gradient(180deg, rgba(255,255,255,.09), rgba(255,255,255,.03))}
    .btn:active{transform:translateY(1px)}
    .btn.primary{border-color:rgba(73,146,255,.5);background:linear-gradient(180deg, rgba(73,146,255,.40), rgba(73,146,255,.16))}
    .btn.danger{border-color:rgba(255,90,106,.45);background:linear-gradient(180deg, rgba(255,90,106,.28), rgba(255,90,106,.12))}
    .btn[disabled]{opacity:.45;cursor:not-allowed;transform:none}
    .btn .dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
    .btn.primary .dot{background:var(--primary)}
    .btn.danger .dot{background:var(--danger)}
    .content{flex:1;min-height:0;display:flex;gap:var(--gap);padding:12px}
    .panel{
      width:360px;max-width:42vw;
      background:linear-gradient(180deg, rgba(23,26,43,.92), rgba(23,26,43,.78));
      border:1px solid var(--border);
      border-radius:var(--radius);
      box-shadow:var(--shadow);
      display:flex;flex-direction:column;min-height:0;
    }
    .panel .section{padding:12px 12px 10px;border-bottom:1px solid var(--border)}
    .panel .section:last-child{border-bottom:none}
    .row{display:flex;align-items:center;justify-content:space-between;gap:10px}
    label{font-size:12px;color:var(--muted)}
    select,input[type="text"]{
      height:34px;
      width:100%;
      border-radius:8px;
      border:1px solid var(--border);
      background:rgba(0,0,0,.18);
      color:var(--text);
      padding:0 10px;
      outline:none;
    }
    select:focus,input[type="text"]:focus{border-color:rgba(73,146,255,.6)}
    .chartWrap{
      flex:1;min-width:0;min-height:0;
      background:linear-gradient(180deg, rgba(23,26,43,.55), rgba(23,26,43,.30));
      border:1px solid var(--border);
      border-radius:var(--radius);
      box-shadow:var(--shadow);
      overflow:hidden;
      position:relative;
    }
    #chart{width:100%;height:100%}
    #gallery{display:none;height:100%;overflow:auto;padding:10px}
    .ggrid{display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));gap:10px}
    .gitem{border:1px solid var(--border);border-radius:10px;overflow:hidden;background:rgba(0,0,0,.18)}
    .gitem img{width:100%;height:120px;object-fit:cover;display:block;background:rgba(255,255,255,.03)}
    .gitem .meta{padding:8px 10px;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .overlay{
      position:absolute;inset:0;
      background:rgba(10,12,22,.45);
      display:none;align-items:center;justify-content:center;
      backdrop-filter:blur(4px);
    }
    .overlay.show{display:flex}
    .spinner{
      width:34px;height:34px;border-radius:50%;
      border:3px solid rgba(255,255,255,.15);
      border-top-color:var(--primary);
      animation:spin 1s linear infinite;
    }
    @keyframes spin{to{transform:rotate(360deg)}}

    .modal{
      position:fixed;inset:0;display:none;align-items:center;justify-content:center;
      background:rgba(0,0,0,.55);backdrop-filter:blur(6px);z-index:9999;
    }
    .modal.show{display:flex}
    .modalCard{
      width:min(880px, calc(100vw - 24px));
      max-height:calc(100vh - 24px);
      overflow:auto;
      background:linear-gradient(180deg, rgba(23,26,43,.96), rgba(23,26,43,.88));
      border:1px solid var(--border);
      border-radius:14px;
      box-shadow:var(--shadow);
      padding:14px;
    }
    .modalHead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}
    .modalHead .t{font-size:14px;font-weight:800}
    .formGrid{display:grid;grid-template-columns:repeat(2, minmax(0, 1fr));gap:10px}
    .field{display:flex;flex-direction:column;gap:6px}
    .field.full{grid-column:1 / -1}
    .modalFoot{display:flex;justify-content:flex-end;gap:10px;margin-top:12px}

    @media (max-width: 980px){
      .content{flex-direction:column}
      .panel{width:100%;max-width:none}
      .ggrid{grid-template-columns:repeat(3, minmax(0, 1fr))}
    }
    @media (max-width: 640px){
      .actions{gap:6px}
      .btn{padding:0 8px}
      .formGrid{grid-template-columns:1fr}
      .ggrid{grid-template-columns:repeat(2, minmax(0, 1fr))}
    }
  </style>
</head>
<body>
  <div id="app">
    <div class="topbar">
      <div class="brand">
        <div class="title">数据图表</div>
        <div class="sub" id="statusText">准备就绪</div>
      </div>
      <div class="actions">
        <button class="btn primary" id="btnAdd"><span class="dot"></span>添加图表</button>
        <button class="btn" id="btnRefresh"><span class="dot"></span>刷新</button>
        <button class="btn" id="btnTheme"><span class="dot"></span>主题</button>
        <button class="btn" id="btnDisplay"><span class="dot"></span>显示效果</button>
        <button class="btn" id="btnGpu"><span class="dot"></span>GPU</button>
      </div>
    </div>
    <div class="content">
      <div class="panel">
        <div class="section">
          <div class="field">
            <label>图表</label>
            <select id="chartSelect"></select>
          </div>
          <div class="field" style="margin-top:10px">
            <label>主题</label>
            <select id="themeSelect">
              <option value="follow">跟随软件主题</option>
              <option value="dark">深色</option>
              <option value="light">浅色</option>
            </select>
          </div>
          <div class="row" style="margin-top:10px">
            <label>显示图例</label>
            <input type="checkbox" id="legendCb" />
          </div>
        </div>
        <div class="section">
          <div class="row">
            <label>水印</label>
            <input type="checkbox" id="wmCb" />
          </div>
        </div>
        <div class="section">
          <div class="row">
            <button class="btn danger" id="btnRemove"><span class="dot"></span>删除当前图表</button>
          </div>
        </div>
        <div class="section">
          <div style="font-size:12px;color:var(--muted);line-height:1.5">
            数据来自本地数据库，支持实时刷新。未安装 WebEngine 时将无法显示该页面。
          </div>
        </div>
      </div>
      <div class="chartWrap">
        <div id="chart"></div>
        <div id="gallery"><div class="ggrid" id="ggrid"></div></div>
        <div class="overlay" id="overlay"><div class="spinner"></div></div>
      </div>
    </div>
  </div>

  <div class="modal" id="modal">
    <div class="modalCard">
      <div class="modalHead">
        <div class="t">添加图表</div>
        <button class="btn" id="btnCloseModal">关闭</button>
      </div>
      <div class="formGrid">
        <div class="field full">
          <label>图表名称</label>
          <input type="text" id="fName" placeholder="请输入图表名称" />
        </div>
        <div class="field">
          <label>图表类型</label>
          <select id="fType"></select>
        </div>
        <div class="field">
          <label>数据集</label>
          <select id="fDataset"></select>
        </div>

        <div class="field" data-scope="xy">
          <label>横坐标字段</label>
          <select id="fXField"></select>
        </div>
        <div class="field" data-scope="xy">
          <label>纵坐标统计</label>
          <select id="fYAgg"></select>
        </div>
        <div class="field full" data-scope="xy">
          <label>分组字段</label>
          <select id="fGroup"></select>
        </div>

        <div class="field" data-scope="pie">
          <label>分类字段</label>
          <select id="fPieCat"></select>
        </div>
        <div class="field" data-scope="pie">
          <label>数值统计</label>
          <select id="fPieAgg"></select>
        </div>

        <div class="field" data-scope="scatter">
          <label>X 字段</label>
          <select id="fSX"></select>
        </div>
        <div class="field" data-scope="scatter">
          <label>Y 字段</label>
          <select id="fSY"></select>
        </div>
        <div class="field full" data-scope="scatter">
          <label>大小字段(可选)</label>
          <select id="fSS"></select>
        </div>
      </div>
      <div class="modalFoot">
        <button class="btn" id="btnCancel">取消</button>
        <button class="btn primary" id="btnSubmit">创建</button>
      </div>
    </div>
  </div>

  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script src="data/echart/echarts.min.js"></script>
  <script>
    const $ = (id) => document.getElementById(id);
    const overlay = $("overlay");
    const statusText = $("statusText");
    const modal = $("modal");

    function setLoading(v){
      if(v){ overlay.classList.add("show"); }
      else { overlay.classList.remove("show"); }
    }
    function setStatus(t){ statusText.textContent = t || ""; }

    function bytesToB64(buf){
      const bytes = new Uint8Array(buf);
      let bin = "";
      for(let i=0;i<bytes.length;i++){ bin += String.fromCharCode(bytes[i]); }
      return btoa(bin);
    }
    async function hmacSign(token, action, payload){
      const enc = new TextEncoder();
      const keyData = enc.encode(token);
      const key = await crypto.subtle.importKey("raw", keyData, {name:"HMAC", hash:"SHA-256"}, false, ["sign"]);
      const msg = enc.encode(String(action||"") + "\\n" + String(payload||""));
      const sig = await crypto.subtle.sign("HMAC", key, msg);
      return bytesToB64(sig);
    }

    function bridgeCall(bridge, action, payloadObj, token){
      return new Promise(async (resolve) => {
        const payload = JSON.stringify(payloadObj || {});
        const sig = await hmacSign(token, action, payload);
        bridge.request(action, payload, token, sig, function(resp){
          try{ resolve(JSON.parse(resp||"{}")); }
          catch(e){ resolve({ok:false, error:"bad_response"}); }
        });
      });
    }

    let bridge = null;
    let token = "";
    let state = null;
    let chart = null;
    let currentChartId = "";
    let watermarkOn = false;

    function openModal(){ modal.classList.add("show"); }
    function closeModal(){ modal.classList.remove("show"); }

    function pickTypeScope(t){
      const xy = ["bar","line","timelineLine","bar3D"];
      if(xy.includes(t)) return "xy";
      if(t === "pie") return "pie";
      if(t === "scatter") return "scatter";
      return "none";
    }
    function syncModalFields(){
      const t = $("fType").value || "";
      const scope = pickTypeScope(t);
      document.querySelectorAll("[data-scope]").forEach(el => {
        el.style.display = (el.getAttribute("data-scope") === scope) ? "" : "none";
      });
    }

    function fillSelect(sel, items, withEmpty){
      sel.innerHTML = "";
      if(withEmpty){
        const o = document.createElement("option");
        o.value = "";
        o.textContent = "不分组";
        sel.appendChild(o);
      }
      (items||[]).forEach(it => {
        const o = document.createElement("option");
        o.value = it.id;
        o.textContent = it.title;
        sel.appendChild(o);
      });
    }

    function refreshChartSelect(){
      const sel = $("chartSelect");
      sel.innerHTML = "";
      const charts = (state && state.charts) ? state.charts : [];
      charts.forEach(c => {
        const o = document.createElement("option");
        o.value = c.chart_id;
        o.textContent = c.name + " · " + c.type_title;
        sel.appendChild(o);
      });
      if(charts.length){
        if(!currentChartId || !charts.some(c => c.chart_id === currentChartId)){
          currentChartId = charts[0].chart_id;
        }
        sel.value = currentChartId;
      }else{
        currentChartId = "";
      }
    }

    function makeWatermarkGraphic(){
      const items = [];
      const c = "rgba(255,255,255,0.06)";
      for(let y=-100;y<1200;y+=85){
        for(let x=-100;x<1800;x+=170){
          items.push({type:"text", left:x, top:y, rotation:-Math.PI/6, z:100, silent:true, style:{text:"Bird", font:"bold 22px sans-serif", fill:c}});
        }
      }
      return items;
    }

    function baseOption(){
      const showTitle = !!(state && state.display_options && state.display_options.show_title);
      const showLegend = !!(state && state.display_options && state.display_options.show_legend);
      const showGrid = !!(state && state.display_options && state.display_options.show_grid);
      const enableAnimation = !!(state && state.display_options && state.display_options.enable_animation);
      const fontSize = (state && state.display_options && state.display_options.font_size) ? Number(state.display_options.font_size) : 12;
      return {
        darkMode: true,
        textStyle: {color:"#e7e9f4", fontSize: fontSize},
        animation: enableAnimation,
        title: showTitle ? {left:"center"} : undefined,
        legend: showLegend ? {top: 40} : undefined,
        grid: showGrid ? {left:60,right:40,top:80,bottom:50} : undefined
      };
    }

    function renderEmpty(msg){
      $("gallery").style.display = "none";
      $("chart").style.display = "";
      if(!chart){ chart = echarts.init($("chart")); }
      chart.clear();
      chart.setOption({
        title:{text: msg || "暂无数据", left:"center", top:"middle", textStyle:{color:"rgba(231,233,244,.75)", fontSize:16}}
      });
    }

    function renderGallery(items){
      $("chart").style.display = "none";
      $("gallery").style.display = "";
      const g = $("ggrid");
      g.innerHTML = "";
      (items||[]).forEach(it => {
        const div = document.createElement("div");
        div.className = "gitem";
        const img = document.createElement("img");
        img.loading = "lazy";
        img.src = "file:///" + String(it.path || "").replace(/\\\\/g, "/");
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = (it.time || "") + "  " + (it.path || "");
        div.appendChild(img);
        div.appendChild(meta);
        g.appendChild(div);
      });
    }

    function renderEchartsOption(title, option){
      $("gallery").style.display = "none";
      $("chart").style.display = "";
      if(!chart){ chart = echarts.init($("chart")); }
      chart.clear();
      const opt = Object.assign({}, option || {});
      if(opt.title && typeof opt.title === "object"){ opt.title.text = title || opt.title.text; }
      else if(title){ opt.title = {text:title, left:"center"}; }
      if(watermarkOn){
        opt.graphic = makeWatermarkGraphic();
      }else{
        opt.graphic = [];
      }
      chart.setOption(opt, true);
    }

    function toTreeSeries(data){
      return [{type:"tree", data:[data], top: 10, left: 10, bottom: 10, right: 10, symbolSize: 6, roam: true, initialTreeDepth: 3, label:{position:"left"}, leaves:{label:{position:"right"}}}];
    }

    async function renderCurrent(){
      const charts = (state && state.charts) ? state.charts : [];
      const c = charts.find(x => x.chart_id === currentChartId);
      if(!c){
        renderEmpty("未添加任何图表");
        return;
      }
      setLoading(true);
      setStatus("加载数据中…");
      const resp = await bridgeCall(bridge, "get_chart_payload", {chart_id: c.chart_id, config: c}, token);
      setLoading(false);
      if(!resp.ok){
        renderEmpty("数据加载失败");
        setStatus("数据加载失败");
        return;
      }
      const payload = resp.data || {};
      const kind = payload.kind || "empty";
      if(kind === "empty"){
        renderEmpty(payload.message || "暂无数据");
        setStatus("暂无数据");
        return;
      }
      if(kind === "gallery"){
        renderGallery(payload.items || []);
        setStatus("就绪");
        return;
      }
      if(kind === "xy"){
        const opt = baseOption();
        const ct = payload.chart_type || c.type;
        const xs = payload.x || [];
        const series = (payload.series||[]).map(s => {
          return {name:s.name || "数值", type:(ct === "line" || ct === "timelineLine") ? "line" : "bar", smooth: !!(payload.meta && payload.meta.smooth), data: s.data || []};
        });
        const option = Object.assign(opt, {
          tooltip:{trigger:"axis"},
          xAxis:{type:"category", data: xs},
          yAxis:{type:"value"},
          series: series
        });
        renderEchartsOption(c.name, option);
        setStatus("就绪");
        return;
      }
      if(kind === "pie"){
        const opt = baseOption();
        const option = Object.assign(opt, {
          tooltip:{trigger:"item"},
          series:[{type:"pie", radius:["30%","65%"], data:(payload.items||[])}]
        });
        renderEchartsOption(c.name, option);
        setStatus("就绪");
        return;
      }
      if(kind === "scatter"){
        const opt = baseOption();
        const pts = payload.points || [];
        const option = Object.assign(opt, {
          tooltip:{trigger:"item"},
          xAxis:{type:"value"},
          yAxis:{type:"value"},
          series:[{type:"scatter", data: pts.map(p => [p[0], p[1]]), symbolSize: (v) => Math.max(4, Math.min(16, (v && v.length>2 ? v[2] : 0) / 10 + 4))}]
        });
        renderEchartsOption(c.name, option);
        setStatus("就绪");
        return;
      }
      if(kind === "tree"){
        const opt = baseOption();
        const option = Object.assign(opt, {tooltip:{trigger:"item"}, series: toTreeSeries(payload.data)});
        renderEchartsOption(c.name, option);
        setStatus("就绪");
        return;
      }
      if(kind === "graph"){
        const opt = baseOption();
        const option = Object.assign(opt, {
          tooltip:{},
          legend:[{data:(payload.categories||[]).map(x=>x.name)}],
          series:[{
            type:"graph",
            layout:"force",
            data:(payload.nodes||[]),
            links:(payload.links||[]),
            categories:(payload.categories||[]),
            roam:true,
            label:{show:true},
            force:{repulsion: 120, edgeLength: 70}
          }]
        });
        renderEchartsOption(c.name, option);
        setStatus("就绪");
        return;
      }
      if(kind === "geo_points"){
        const opt = baseOption();
        const pts = payload.points || [];
        const option = Object.assign(opt, {
          tooltip:{trigger:"item"},
          xAxis:{type:"value", name:"经度"},
          yAxis:{type:"value", name:"纬度"},
          series:[{type:"scatter", data: pts.map(p => [p[0], p[1], p[2]]), symbolSize: (v)=>Math.max(3, Math.min(18, (v[2]||1))) }]
        });
        renderEchartsOption(c.name, option);
        setStatus("就绪");
        return;
      }
      if(kind === "gauge"){
        const opt = baseOption();
        const ms = payload.metrics || [];
        const option = Object.assign(opt, {
          tooltip:{},
          series: ms.map((m, idx) => {
            return {
              type:"gauge",
              startAngle: 210,
              endAngle: -30,
              radius: (ms.length<=1) ? "80%" : (idx===0 ? "65%" : "45%"),
              center: ms.length<=1 ? ["50%","60%"] : ["50%", idx===0 ? "55%" : "70%"],
              pointer:{show:true},
              detail:{valueAnimation:true, formatter:"{value}"},
              title:{offsetCenter:[0,"85%"], fontSize:12},
              data:[{value: Number(m.value||0), name: m.name||""}]
            };
          })
        });
        renderEchartsOption(c.name, option);
        setStatus("就绪");
        return;
      }
      if(kind === "radar"){
        const opt = baseOption();
        const option = Object.assign(opt, {
          tooltip:{},
          radar:{indicator:(payload.indicators||[])},
          series:[{type:"radar", data:[{value:(payload.value||[]), name:"指标"}]}]
        });
        renderEchartsOption(c.name, option);
        setStatus("就绪");
        return;
      }
      if(kind === "calendar"){
        const opt = baseOption();
        const d = payload.data || [];
        const years = d.map(x => String(x[0]||"").slice(0,4)).filter(Boolean);
        const year = years.length ? years[0] : new Date().getFullYear();
        const option = Object.assign(opt, {
          tooltip:{},
          visualMap:{min:0, max: Math.max(1, ...d.map(x=>x[1]||0)), orient:"horizontal", left:"center", bottom:10, textStyle:{color:"#e7e9f4"}},
          calendar:{top:60, left:40, right:40, cellSize:["auto", 16], range:String(year)},
          series:[{type:"heatmap", coordinateSystem:"calendar", data:d}]
        });
        renderEchartsOption(c.name, option);
        setStatus("就绪");
        return;
      }

      renderEmpty("暂不支持该图表渲染");
      setStatus("暂不支持");
    }

    async function bootstrap(){
      setLoading(true);
      setStatus("初始化中…");
      const resp = await bridgeCall(bridge, "bootstrap", {}, token);
      setLoading(false);
      if(!resp.ok){
        setStatus("初始化失败");
        return;
      }
      state = resp.data || {};
      if(state.db_ready === false){
        try{
          $("btnAdd").disabled = true;
          $("btnRefresh").disabled = true;
          $("btnRemove").disabled = true;
        }catch(e){}
        renderEmpty("数据库不可用");
        setStatus("数据库不可用");
        return;
      }else{
        try{
          $("btnAdd").disabled = false;
          $("btnRefresh").disabled = false;
          $("btnRemove").disabled = false;
        }catch(e){}
      }
      try{
        $("themeSelect").value = String(state.theme || "follow");
      }catch(e){}
      try{
        $("legendCb").checked = !(state.display_options && state.display_options.show_legend === false);
      }catch(e){}
      fillSelect($("fType"), state.chart_types || []);
      fillSelect($("fDataset"), state.datasets || []);
      fillSelect($("fXField"), state.fields || []);
      fillSelect($("fYAgg"), state.aggs || []);
      fillSelect($("fGroup"), state.fields || [], true);
      fillSelect($("fPieCat"), state.fields || []);
      fillSelect($("fPieAgg"), state.aggs || []);
      fillSelect($("fSX"), state.fields || []);
      fillSelect($("fSY"), state.fields || []);
      fillSelect($("fSS"), state.fields || [], true);
      refreshChartSelect();
      await renderCurrent();
    }

    function ensureBridge(){
      return new Promise((resolve) => {
        new QWebChannel(qt.webChannelTransport, function(channel){
          bridge = channel.objects.bridge;
          bridge.getToken(function(t){
            token = String(t || "");
            try{
              if(bridge.push && bridge.push.connect){
                bridge.push.connect(async function(eventName, payloadJson){
                  const ev = String(eventName||"");
                  if(ev === "data_changed" || ev === "state_changed"){
                    await bootstrap();
                  }
                });
              }
            }catch(e){}
            resolve();
          });
        });
      });
    }

    function wireEvents(){
      $("themeSelect").addEventListener("change", async (e) => {
        const theme = e.target.value || "follow";
        setLoading(true);
        const resp = await bridgeCall(bridge, "set_theme", {theme}, token);
        setLoading(false);
        if(resp.ok){
          state.theme = theme;
          setStatus("主题已保存");
        }
      });
      $("legendCb").addEventListener("change", async (e) => {
        const cur = state && state.display_options ? state.display_options : {};
        const next = Object.assign({}, cur, {show_legend: !!e.target.checked});
        setLoading(true);
        const resp = await bridgeCall(bridge, "set_display_options", {options: next}, token);
        setLoading(false);
        if(resp.ok){
          state.display_options = next;
          await renderCurrent();
          setStatus("显示效果已保存");
        }
      });
      $("wmCb").addEventListener("change", async (e) => {
        watermarkOn = !!e.target.checked;
        await renderCurrent();
      });
      $("chartSelect").addEventListener("change", async (e) => {
        currentChartId = e.target.value || "";
        await renderCurrent();
      });
      $("btnRefresh").addEventListener("click", async () => { await renderCurrent(); });
      $("btnAdd").addEventListener("click", () => { openModal(); syncModalFields(); });
      $("btnCloseModal").addEventListener("click", () => closeModal());
      $("btnCancel").addEventListener("click", () => closeModal());
      $("fType").addEventListener("change", () => syncModalFields());
      $("btnSubmit").addEventListener("click", async () => {
        const name = ($("fName").value || "").trim() || "未命名图表";
        const type = $("fType").value || "bar";
        const dataset = $("fDataset").value || "library";
        const scope = pickTypeScope(type);
        let options = {};
        if(scope === "xy"){
          options = {x_field:$("fXField").value||"", y_agg:$("fYAgg").value||"count", group_field:$("fGroup").value||""};
        }else if(scope === "pie"){
          options = {category_field:$("fPieCat").value||"", value_agg:$("fPieAgg").value||"count"};
        }else if(scope === "scatter"){
          options = {x_field:$("fSX").value||"", y_field:$("fSY").value||"", size_field:$("fSS").value||""};
        }
        setLoading(true);
        const resp = await bridgeCall(bridge, "add_chart", {name, type, dataset, options}, token);
        setLoading(false);
        if(resp.ok){
          const c = resp.data;
          state.charts = state.charts || [];
          state.charts.unshift(c);
          currentChartId = c.chart_id;
          refreshChartSelect();
          closeModal();
          await renderCurrent();
        }
      });
      $("btnRemove").addEventListener("click", async () => {
        if(!currentChartId) return;
        setLoading(true);
        const resp = await bridgeCall(bridge, "remove_chart", {chart_id: currentChartId}, token);
        setLoading(false);
        if(resp.ok){
          state.charts = (state.charts||[]).filter(c => c.chart_id !== currentChartId);
          currentChartId = "";
          refreshChartSelect();
          await renderCurrent();
        }
      });
      $("btnGpu").addEventListener("click", async () => {
        const enabled = !(state && state.gpu_rendering_enabled);
        setLoading(true);
        const resp = await bridgeCall(bridge, "set_gpu", {enabled}, token);
        setLoading(false);
        if(resp.ok){
          state.gpu_rendering_enabled = enabled;
          setStatus(enabled ? "GPU 已开启" : "GPU 已关闭");
        }
      });
      $("btnTheme").addEventListener("click", async () => {
        const next = (state && state.theme === "dark") ? "light" : "dark";
        setLoading(true);
        const resp = await bridgeCall(bridge, "set_theme", {theme: next}, token);
        setLoading(false);
        if(resp.ok){
          state.theme = next;
          setStatus("主题已保存");
        }
      });
      $("btnDisplay").addEventListener("click", async () => {
        const cur = state && state.display_options ? state.display_options : {};
        const next = Object.assign({}, cur, {show_legend: !cur.show_legend});
        setLoading(true);
        const resp = await bridgeCall(bridge, "set_display_options", {options: next}, token);
        setLoading(false);
        if(resp.ok){
          state.display_options = next;
          await renderCurrent();
          setStatus("显示效果已保存");
        }
      });

      window.addEventListener("resize", () => {
        try{ if(chart) chart.resize(); }catch(e){}
      });
    }

    (async function(){
      try{
        await ensureBridge();
        wireEvents();
        await bootstrap();
        setStatus("就绪");
      }catch(e){
        setStatus("初始化失败");
      }
    })();
  </script>
</body>
</html>
"""
