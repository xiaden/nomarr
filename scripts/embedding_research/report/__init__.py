"""Embedding research report generator — schema v2."""

from __future__ import annotations

import datetime
import json
import time
from typing import Any

from plotly.offline import get_plotlyjs

from ._corpus import disc_score_warning, section_corpus
from ._efficiency import section_efficiency
from ._heads import section_head_analysis
from ._provenance import section_provenance
from ._retrieval import query_analyze_metrics, section_analysis
from ._summary import section_summary
from ._winners_report import section_winners

_REPORT_SCHEMA_VERSION = 2
_REPORT_TITLE = "Embedding Research Report"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _step(label: str, fn) -> tuple[Any, float]:
    """Time and call *fn*, returning (result, elapsed_seconds)."""
    t0 = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - t0
    print(f"  [{elapsed:5.1f}s] {label}")
    return result, elapsed


# ---------------------------------------------------------------------------
# HTML viewer shell (schema v2 client-side renderer)
# ---------------------------------------------------------------------------


def _viewer_shell() -> str:
    plotlyjs = get_plotlyjs()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Embedding Research Report</title>
<script>{plotlyjs}</script>
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f0f18;color:#e0e0e8;font-family:"Inter","Segoe UI",system-ui,sans-serif;font-size:14px;line-height:1.5}}
#nav{{position:sticky;top:0;background:#1a1b26;border-bottom:1px solid #2d2f46;padding:0 24px;display:flex;gap:8px;flex-wrap:wrap;z-index:100}}
#nav a{{color:#7aa2f7;text-decoration:none;font-size:13px;padding:8px 4px;white-space:nowrap}}
#nav a:hover{{color:#a9c4ff}}
#main{{max-width:1100px;margin:0 auto;padding:24px 20px 80px}}
#empty-state{{display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;gap:16px;text-align:center}}
#drop-zone{{border:2px dashed #3d3f5a;border-radius:12px;padding:40px 60px;cursor:pointer;transition:border-color .2s}}
#drop-zone:hover,#drop-zone.dragover{{border-color:#7aa2f7}}
#drop-zone p{{color:#8888aa;font-size:14px;margin-top:8px}}
#drop-zone strong{{color:#c0c0e0;font-size:16px}}
#file-input{{display:none}}
#status{{font-size:13px}}
#status.ok{{color:#4ade80}}
#status.err{{color:#f87171}}
#run-ts{{font-size:12px;color:#666;margin-top:4px}}
.hidden{{display:none!important}}
#warnings-area{{margin-bottom:16px}}
.warning-banner{{border-radius:6px;padding:14px 18px;margin-bottom:10px;position:relative}}
.warning-banner .dismiss{{position:absolute;top:10px;right:14px;background:none;border:none;font-size:16px;cursor:pointer;opacity:.7}}
.warning-banner .dismiss:hover{{opacity:1}}
section{{margin-bottom:48px}}
h2{{font-size:20px;font-weight:600;color:#c0caf5;border-bottom:1px solid #2d2f46;padding-bottom:8px;margin-bottom:16px}}
h3{{font-size:15px;font-weight:600;color:#9aa5ce;margin:20px 0 10px}}
h4{{font-size:13px;color:#c0c0e0;margin:12px 0 6px}}
.card{{background:#1a1b26;border:1px solid #2d2f46;border-radius:8px;padding:14px 18px;margin-bottom:14px}}
.muted{{color:#8888aa;font-size:13px}}
.empty{{color:#8888aa;font-style:italic;padding:24px 0;text-align:center}}
.stat-row{{display:flex;flex-wrap:wrap;gap:16px;margin-bottom:16px}}
.stat{{background:#1a1b26;border:1px solid #2d2f46;border-radius:8px;padding:10px 18px;display:flex;flex-direction:column;align-items:center;min-width:100px}}
.stat-val{{font-size:22px;font-weight:700;color:#7aa2f7}}
.stat-lbl{{font-size:11px;color:#666;text-transform:uppercase;letter-spacing:.04em;margin-top:2px}}
.chart-wrapper{{width:100%;max-width:960px;margin-bottom:1.2rem}}
.subsection{{border-left:2px solid #2d2f46;padding-left:16px;margin-bottom:20px}}
table{{border-collapse:collapse;font-size:12px;width:100%;margin-bottom:12px}}
th{{background:#1e1f2e;color:#7aa2f7;text-align:left;padding:6px 10px;border-bottom:1px solid #2d2f46;white-space:nowrap}}
td{{padding:5px 10px;border-bottom:1px solid #1e1f2e;white-space:nowrap}}
tr:hover td{{background:#1a1b26}}
details{{margin-bottom:8px}}
summary{{cursor:pointer;color:#9aa5ce;font-size:13px;padding:6px 0;user-select:none}}
summary:hover{{color:#c0caf5}}
.details-body{{padding:12px 0 4px 16px}}
.headline-card{{border-radius:8px;padding:14px 18px;margin-bottom:14px}}
</style>
</head>
<body>
<nav id="nav"><span id="nav-links" style="display:flex;gap:8px;flex-wrap:wrap"></span></nav>
<main id="main">
  <div id="warnings-area"></div>
  <div id="empty-state">
    <div id="drop-zone" onclick="document.getElementById('file-input').click()">
      <strong>Drop report.json here</strong>
      <p>or click to open a file</p>
    </div>
    <input type="file" id="file-input" accept=".json">
    <p id="status" class="muted">No report loaded yet.</p>
    <p id="run-ts"></p>
  </div>
  <div id="report-body"></div>
</main>
<script>
"use strict";
function esc(s){{return String(s??"\u2014").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;")}}
function setStatus(msg,cls){{var el=document.getElementById("status");el.textContent=msg;el.className=cls||"muted"}}
function renderWarning(w){{
  var COLORS={{error:"#f87171",warning:"#fbbf24",info:"#7ec8e3"}};
  var color=COLORS[w.level]||"#aaa";
  var div=document.createElement("div");
  div.className="warning-banner";
  div.style.cssText="background:"+color+"18;border:1px solid "+color+";";
  div.innerHTML='<button class="dismiss" style="color:'+color+'" onclick="this.parentElement.remove()">\u00d7<\\/button>'+
    '<strong style="color:'+color+'">'+esc(w.message)+'<\\/strong>'+
    (w.detail?'<p class="muted" style="margin-top:6px">'+esc(w.detail)+'<\\/p>':"");
  return div;
}}
function renderChart(chart){{
  var wrapper=document.createElement("div");
  wrapper.className="chart-wrapper";
  var div=document.createElement("div");
  var uid="c"+Math.random().toString(36).slice(2,9);
  div.id=uid;
  wrapper.appendChild(div);
  requestAnimationFrame(function(){{
    try{{
      var fig=chart.figure||{{}};
      Plotly.newPlot(div,fig.data||[],fig.layout||{{}},{{responsive:true,displayModeBar:false}});
    }}catch(e){{div.textContent="Chart error: "+e.message}}
  }});
  return wrapper;
}}
function renderTable(tbl){{
  if(!tbl||tbl.empty||!tbl.columns||!tbl.columns.length){{
    var p=document.createElement("p");p.className="empty";p.textContent="No data.";return p;
  }}
  var headers=tbl.columns.map(function(c){{return"<th>"+esc(c)+"<\\/th>"}}).join("");
  var body=tbl.rows.map(function(row){{
    return"<tr>"+row.map(function(cell){{return"<td>"+esc(cell)+"<\\/td>"}}).join("")+"<\\/tr>";
  }}).join("");
  var tableEl=document.createElement("div");
  tableEl.innerHTML="<table><thead><tr>"+headers+"<\\/tr><\\/thead><tbody>"+body+"<\\/tbody><\\/table>";
  if(!tbl.collapsible)return tableEl;
  var details=document.createElement("details");
  if(tbl.open)details.open=true;
  var summary=document.createElement("summary");
  summary.textContent=tbl.summary_text||tbl.title||"Table";
  var body2=document.createElement("div");
  body2.className="details-body";
  body2.appendChild(tableEl);
  details.appendChild(summary);details.appendChild(body2);
  return details;
}}
function renderPanel(panel){{
  var details=document.createElement("details");
  if(panel.open)details.open=true;
  var summary=document.createElement("summary");
  summary.textContent=panel.title||"Details";
  details.appendChild(summary);
  var body=document.createElement("div");
  body.className="details-body";
  if(panel.text){{var p=document.createElement("p");p.className="muted";p.textContent=panel.text;body.appendChild(p);}}
  (panel.charts||[]).forEach(function(c){{body.appendChild(renderChart(c))}});
  (panel.tables||[]).forEach(function(t){{body.appendChild(renderTable(t))}});
  (panel.subsections||[]).forEach(function(s){{body.appendChild(renderSubsection(s))}});
  details.appendChild(body);
  return details;
}}
function fillContent(el,sub){{
  if(sub.description){{
    var card=document.createElement("div");card.className="card";
    var p=document.createElement("p");p.className="muted";p.textContent=sub.description;
    card.appendChild(p);el.appendChild(card);
  }}
  (sub.warnings||[]).forEach(function(w){{el.appendChild(renderWarning(w))}});
  if(sub.stats&&sub.stats.length){{
    var row=document.createElement("div");row.className="stat-row";
    row.innerHTML=sub.stats.map(function(s){{
      return'<div class="stat"><span class="stat-val">'+esc(s.value)+'<\\/span><span class="stat-lbl">'+esc(s.label)+'<\\/span><\\/div>';
    }}).join("");
    el.appendChild(row);
  }}
  (sub.charts||[]).forEach(function(c){{el.appendChild(renderChart(c))}});
  (sub.tables||[]).forEach(function(t){{el.appendChild(renderTable(t))}});
  (sub.panels||[]).forEach(function(p){{el.appendChild(renderPanel(p))}});
  (sub.subsections||[]).forEach(function(s){{el.appendChild(renderSubsection(s))}});
}}
function renderSubsection(sub){{
  var div=document.createElement("div");div.className="subsection";
  if(sub.id)div.id=sub.id;
  if(sub.title){{var h3=document.createElement("h3");h3.textContent=sub.title;div.appendChild(h3);}}
  fillContent(div,sub);
  return div;
}}
function renderSection(section){{
  var el=document.createElement("section");
  if(section.id)el.id=section.id;
  var h2=document.createElement("h2");h2.textContent=section.title;el.appendChild(h2);
  if(section.empty_message){{
    var p=document.createElement("p");p.className="empty";p.textContent=section.empty_message;el.appendChild(p);return el;
  }}
  if(section.headline){{
    var hl=section.headline;
    var card=document.createElement("div");card.className="headline-card";
    card.style.cssText="background:"+hl.color+"12;border:1px solid "+hl.color+"55;";
    card.innerHTML='<p style="font-size:15px"><span style="color:'+esc(hl.color)+';font-size:18px">'+esc(hl.icon)+'<\\/span> &nbsp;<span style="color:'+esc(hl.color)+'">'+esc(hl.text)+'<\\/span><\\/p>'+
      (section.description?'<p class="muted" style="margin-top:6px">'+esc(section.description)+'<\\/p>':"");
    el.appendChild(card);
    var noDesc=section;noDesc=Object.assign({{}},section,{{description:""}});
    fillContent(el,noDesc);
  }}else{{
    fillContent(el,section);
  }}
  return el;
}}
function renderPayload(payload,sourceName){{
  if(!payload||payload.schema_version!==2){{
    setStatus("Error: expected schema_version 2, got "+(payload&&payload.schema_version),"err");return;
  }}
  document.getElementById("empty-state").classList.add("hidden");
  document.getElementById("report-body").innerHTML="";
  document.getElementById("warnings-area").innerHTML="";
  (payload.warnings||[]).forEach(function(w){{document.getElementById("warnings-area").appendChild(renderWarning(w))}});
  document.getElementById("nav-links").innerHTML=(payload.sections||[]).map(function(s){{return'<a href="#'+s.id+'">'+esc(s.title)+'<\\/a>'}}).join("");
  document.title=payload.title||"Embedding Research Report";
  document.getElementById("run-ts").textContent="Generated "+(payload.run_ts||"");
  var reportBody=document.getElementById("report-body");
  (payload.sections||[]).forEach(function(s){{reportBody.appendChild(renderSection(s))}});
  setStatus("Loaded "+sourceName,"ok");
}}
function loadFile(file){{
  if(!file)return;
  setStatus("Loading "+file.name+"\u2026");
  var reader=new FileReader();
  reader.onload=function(e){{
    try{{renderPayload(JSON.parse(e.target.result),file.name)}}
    catch(err){{setStatus("Parse error: "+err.message,"err")}}
  }};
  reader.onerror=function(){{setStatus("Read error","err")}};
  reader.readAsText(file);
}}
var dz=document.getElementById("drop-zone");
dz.addEventListener("dragover",function(e){{e.preventDefault();dz.classList.add("dragover")}});
dz.addEventListener("dragleave",function(){{dz.classList.remove("dragover")}});
dz.addEventListener("drop",function(e){{e.preventDefault();dz.classList.remove("dragover");loadFile(e.dataTransfer.files[0])}});
document.getElementById("file-input").addEventListener("change",function(e){{loadFile(e.target.files[0])}});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------


def _payload(
    sections: list[dict],
    warnings: list[dict],
) -> dict:
    return {
        "schema_version": _REPORT_SCHEMA_VERSION,
        "title": _REPORT_TITLE,
        "run_ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "warnings": warnings,
        "sections": sections,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(con, out_path=None, *, run_id: str | None = None) -> dict:
    """Generate the embedding research report and write HTML + JSON files.

    Emits EXACTLY seven schema-v2 sections, in order: ``summary``, ``corpus``,
    ``analysis``, ``winners``, ``head-analysis``, ``provenance``, ``efficiency``.

    Parameters
    ----------
    con:
        Open DuckDB connection with active catalog analysis + head provenance results.
    out_path:
        Required directory where ``report.html`` and ``report.json`` will be written.
        Raises ``ValueError`` if not provided.
    run_id:
        Optional physical run-scope selector.  When given, only that run's catalog analysis
        rows feed the analysis/winners/summary sections and only that run's provenance is
        reported.  When ``None`` (the default) the active completed scope is used: every
        completed catalog analysis and head-provenance record present is rendered.  No
        inference is ever performed at report time — the report is rendered verbatim from
        completed phases.

    Returns:
        The assembled payload dict (also written to ``report.json`` / ``report.html``).
    """
    import pathlib

    if out_path is None:
        raise ValueError("out_path is required; pass the report output directory")

    out_path = pathlib.Path(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    print("Generating report…")

    # Data loaders
    df, _ = _step("query_analyze_metrics", lambda: query_analyze_metrics(con, run_id=run_id))

    # Global warnings
    warnings, _ = _step("disc_score_warning", lambda: disc_score_warning(con))

    # Section builders (exact order contract).
    sections_raw: list[tuple[str, Any]] = [
        ("summary", lambda: section_summary(df)),
        ("corpus", lambda: section_corpus(con)),
        ("analysis", lambda: section_analysis(df)),
        ("winners", lambda: section_winners(df)),
        ("head-analysis", lambda: section_head_analysis(con)),
        ("provenance", lambda: section_provenance(con, run_id=run_id)),
        ("efficiency", lambda: section_efficiency(con)),
    ]

    sections: list[dict] = []
    for label, fn in sections_raw:
        result, _ = _step(label, fn)
        sections.append(result)

    # Assemble payload
    payload = _payload(sections, warnings)
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    # Write outputs
    json_path = out_path / "report.json"
    json_path.write_text(payload_json, encoding="utf-8")
    print(f"  Wrote {json_path} ({len(payload_json) // 1024} KB)")

    html_path = out_path / "report.html"
    html_path.write_text(_viewer_shell(), encoding="utf-8")
    print(f"  Wrote {html_path}")

    print("Report done.")
    return payload
