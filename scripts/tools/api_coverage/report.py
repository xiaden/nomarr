"""Generate HTML coverage reports."""

from datetime import datetime
from pathlib import Path

from .models import EndpointUsage

project_root = Path(__file__).parent.parent.parent.parent


def generate_html_report(
    endpoint_usages: list[EndpointUsage], output_file: Path, filter_mode: str | None = None
) -> None:
    """Generate interactive HTML report with collapsible groups."""
    # Apply filters
    if filter_mode == "used":
        endpoint_usages = [e for e in endpoint_usages if e.used]
    elif filter_mode == "unused":
        endpoint_usages = [e for e in endpoint_usages if not e.used]

    total = len(endpoint_usages)
    used_count = sum(1 for e in endpoint_usages if e.used)
    unused_count = total - used_count
    coverage_pct = (used_count / total * 100) if total > 0 else 0

    # Group routes
    web_routes = [e for e in endpoint_usages if e.path.startswith("/api/web")]
    v1_routes = [e for e in endpoint_usages if e.path.startswith("/api/v1")]
    other_routes = [e for e in endpoint_usages if not e.path.startswith(("/api/web", "/api/v1"))]

    # Start HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>API Endpoint Coverage Report</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; padding: 20px; }}
        .container {{ max-width: 1400px; margin: 0 auto; background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); padding: 30px; }}
        h1 {{ color: #1a1a1a; margin-bottom: 10px; }}
        .timestamp {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .stat-card {{ background: #f9f9f9; padding: 20px; border-radius: 6px; border-left: 4px solid #ddd; }}
        .stat-card.used {{ border-left-color: #4caf50; }}
        .stat-card.unused {{ border-left-color: #ff9800; }}
        .stat-label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
        .stat-value {{ font-size: 32px; font-weight: 600; color: #1a1a1a; }}
        .progress-bar {{ width: 100%; height: 8px; background: #e0e0e0; border-radius: 4px; overflow: hidden; margin: 20px 0; }}
        .progress-fill {{ height: 100%; background: linear-gradient(90deg, #4caf50, #8bc34a); transition: width 0.3s; }}
        .controls {{ margin: 20px 0; padding: 15px; background: #f9f9f9; border-radius: 6px; display: flex; align-items: center; gap: 15px; }}
        .controls label {{ font-size: 14px; font-weight: 500; color: #666; }}
        .controls select {{ padding: 8px 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; cursor: pointer; background: white; }}
        .group {{ margin: 20px 0; }}
        .group-header {{ background: #f0f0f0; padding: 12px 15px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 10px; user-select: none; transition: background 0.2s; }}
        .group-header:hover {{ background: #e8e8e8; }}
        .group-header .toggle {{ font-size: 18px; font-weight: bold; color: #666; min-width: 20px; }}
        .group-title {{ font-size: 18px; font-weight: 600; color: #1a1a1a; flex: 1; }}
        .group-count {{ font-size: 14px; color: #666; background: white; padding: 4px 10px; border-radius: 12px; }}
        .group-content {{ padding: 15px 0; display: none; }}
        .group-content.expanded {{ display: block; }}
        .endpoint {{ margin: 10px 0; padding: 15px; background: #fafafa; border-radius: 6px; border-left: 4px solid #ddd; }}
        .endpoint.used {{ border-left-color: #4caf50; }}
        .endpoint.unused {{ border-left-color: #ff9800; }}
        .endpoint-header {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
        .method {{ padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600; text-transform: uppercase; }}
        .method.GET {{ background: #e3f2fd; color: #1976d2; }}
        .method.POST {{ background: #f3e5f5; color: #7b1fa2; }}
        .method.PUT {{ background: #fff3e0; color: #f57c00; }}
        .method.PATCH {{ background: #fce4ec; color: #c2185b; }}
        .method.DELETE {{ background: #ffebee; color: #d32f2f; }}
        .path {{ font-family: "Consolas", "Monaco", monospace; font-size: 14px; color: #1a1a1a; font-weight: 500; flex: 1; }}
        .status {{ padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 500; }}
        .status.used {{ background: #e8f5e9; color: #2e7d32; }}
        .status.unused {{ background: #fff3e0; color: #e65100; }}
        .endpoint-docs {{ margin-top: 10px; padding: 10px; background: white; border-radius: 4px; font-size: 13px; color: #555; }}
        .endpoint-summary {{ font-weight: 600; color: #1a1a1a; margin-bottom: 5px; }}
        .endpoint-description {{ color: #666; line-height: 1.5; }}
        .backend-location {{ margin-top: 10px; padding: 8px; background: #f0f7ff; border-radius: 4px; font-size: 13px; }}
        .location-label {{ font-weight: 600; color: #1976d2; margin-right: 8px; }}
        .usage-list {{ margin-top: 12px; padding-top: 12px; border-top: 1px solid #e0e0e0; }}
        .usage-item {{ margin: 4px 0; }}
        .file-link {{ color: #1976d2; text-decoration: none; font-size: 13px; font-family: "Consolas", "Monaco", monospace; }}
        .file-link:hover {{ text-decoration: underline; }}
        .filter-info {{ background: #e3f2fd; padding: 10px 15px; border-radius: 6px; color: #1976d2; margin-bottom: 20px; font-size: 14px; }}
        .view-mode {{ display: none; }}
        .view-mode.active {{ display: block; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>API Endpoint Coverage Report</h1>
        <div class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
        
        {"<div class='filter-info'>Filtered: " + filter_mode + " endpoints only</div>" if filter_mode else ""}
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-label">Total Endpoints</div>
                <div class="stat-value">{total}</div>
            </div>
            <div class="stat-card used">
                <div class="stat-label">Used</div>
                <div class="stat-value">{used_count}</div>
            </div>
            <div class="stat-card unused">
                <div class="stat-label">Unused</div>
                <div class="stat-value">{unused_count}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Coverage</div>
                <div class="stat-value">{coverage_pct:.1f}%</div>
            </div>
        </div>
        
        <div class="progress-bar">
            <div class="progress-fill" style="width: {coverage_pct}%"></div>
        </div>
        
        <div class="controls">
            <label for="groupBy">Group by:</label>
            <select id="groupBy" onchange="switchView(this.value)">
                <option value="route">Route Prefix</option>
                <option value="usage">Usage Status</option>
                <option value="method">Request Method</option>
            </select>
        </div>
"""

    # Helper to render endpoint
    def render_endpoint(endpoint: EndpointUsage) -> str:
        docs_html = ""
        if endpoint.summary or endpoint.description:
            docs_html = '<div class="endpoint-docs">'
            if endpoint.summary:
                docs_html += f'<div class="endpoint-summary">{endpoint.summary}</div>'
            if endpoint.description:
                docs_html += f'<div class="endpoint-description">{endpoint.description}</div>'
            docs_html += "</div>"

        # Backend location
        backend_html = ""
        if endpoint.backend_file and endpoint.backend_line:
            backend_html = f"""
                <div class="backend-location">
                    <span class="location-label">Backend:</span>
                    <a href="vscode://file/{project_root}/{endpoint.backend_file}:{endpoint.backend_line}" class="file-link">
                        {endpoint.backend_file}:{endpoint.backend_line}
                    </a>
                </div>"""

        usage_html = ""
        if endpoint.frontend_files:
            usage_html = '<div class="usage-list">'
            unique_usages = sorted(set(endpoint.frontend_files))
            for file_path, line_num in unique_usages:
                usage_html += f"""
                    <div class="usage-item">
                        <a href="vscode://file/{project_root}/{file_path}:{line_num}" class="file-link">
                            {file_path}:{line_num}
                        </a>
                    </div>"""
            usage_html += "</div>"

        return f"""
            <div class="endpoint {endpoint.status_class}">
                <div class="endpoint-header">
                    <span class="method {endpoint.method}">{endpoint.method}</span>
                    <span class="path">{endpoint.path}</span>
                    <span class="status {endpoint.status_class}">{endpoint.status_text}</span>
                </div>
                {docs_html}
                {backend_html}
                {usage_html}
            </div>"""

    # View 1: By route prefix
    html += '<div id="view-route" class="view-mode active">\n'
    for section_name, section_routes in [
        ("Web UI API (/api/web)", web_routes),
        ("Integration API (/api/v1)", v1_routes),
        ("Other Routes", other_routes),
    ]:
        if not section_routes:
            continue
        html += f"""
        <div class="group">
            <div class="group-header" onclick="toggleGroup(this)">
                <span class="toggle">▶</span>
                <span class="group-title">{section_name}</span>
                <span class="group-count">{len(section_routes)} endpoints</span>
            </div>
            <div class="group-content">
"""
        for endpoint in section_routes:
            html += render_endpoint(endpoint)
        html += "</div></div>\n"
    html += "</div>\n"

    # View 2: By usage status
    html += '<div id="view-usage" class="view-mode">\n'
    used_endpoints = [e for e in endpoint_usages if e.used]
    unused_endpoints = [e for e in endpoint_usages if not e.used]
    for section_name, section_routes in [
        ("Used Endpoints", used_endpoints),
        ("Unused Endpoints", unused_endpoints),
    ]:
        if not section_routes:
            continue
        html += f"""
        <div class="group">
            <div class="group-header" onclick="toggleGroup(this)">
                <span class="toggle">▶</span>
                <span class="group-title">{section_name}</span>
                <span class="group-count">{len(section_routes)} endpoints</span>
            </div>
            <div class="group-content">
"""
        for endpoint in section_routes:
            html += render_endpoint(endpoint)
        html += "</div></div>\n"
    html += "</div>\n"

    # View 3: By method
    html += '<div id="view-method" class="view-mode">\n'
    methods_map: dict[str, list[EndpointUsage]] = {}
    for endpoint in endpoint_usages:
        if endpoint.method not in methods_map:
            methods_map[endpoint.method] = []
        methods_map[endpoint.method].append(endpoint)
    for method in ["GET", "POST", "PUT", "PATCH", "DELETE"]:
        if method not in methods_map:
            continue
        section_routes = methods_map[method]
        html += f"""
        <div class="group">
            <div class="group-header" onclick="toggleGroup(this)">
                <span class="toggle">▶</span>
                <span class="group-title">{method} Requests</span>
                <span class="group-count">{len(section_routes)} endpoints</span>
            </div>
            <div class="group-content">
"""
        for endpoint in section_routes:
            html += render_endpoint(endpoint)
        html += "</div></div>\n"
    html += "</div>\n"

    # JavaScript
    html += """
    <script>
        function switchView(viewType) {
            document.querySelectorAll('.view-mode').forEach(view => {
                view.classList.remove('active');
            });
            document.getElementById('view-' + viewType).classList.add('active');
            document.querySelectorAll('.group-content').forEach(content => {
                content.classList.remove('expanded');
            });
            document.querySelectorAll('.toggle').forEach(toggle => {
                toggle.textContent = '▶';
            });
        }
        
        function toggleGroup(header) {
            const content = header.nextElementSibling;
            const toggle = header.querySelector('.toggle');
            
            if (content.classList.contains('expanded')) {
                content.classList.remove('expanded');
                toggle.textContent = '▶';
            } else {
                content.classList.add('expanded');
                toggle.textContent = '▼';
            }
        }
        
        document.addEventListener('DOMContentLoaded', () => {
            const firstGroup = document.querySelector('.view-mode.active .group-header');
            if (firstGroup) {
                toggleGroup(firstGroup);
            }
        });
    </script>
    </div>
</body>
</html>
"""

    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")
    print(f"Report generated: {output_file}")
    print(f"  Total endpoints: {total}")
    print(f"  Used: {used_count} ({coverage_pct:.1f}%)")
    print(f"  Unused: {unused_count}")
