/* Agent Performance Dashboard — reads JSON data and renders everything client-side. */

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTokens(n) {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
}

function formatMs(ms) {
    if (ms >= 60_000) return (ms / 60_000).toFixed(1) + 'm';
    if (ms >= 1_000) return (ms / 1_000).toFixed(1) + 's';
    return Math.round(ms) + 'ms';
}

function formatTs(ts) {
    if (!ts || ts <= 0) return '—';
    try {
        const d = new Date(ts);
        return d.toISOString().slice(0, 16).replace('T', ' ');
    } catch { return '—'; }
}

function pct(v) { return (v * 100).toFixed(0) + '%'; }

function esc(s) {
    const el = document.createElement('span');
    el.textContent = s;
    return el.innerHTML;
}

// ---------------------------------------------------------------------------
// Role classification & colors
// ---------------------------------------------------------------------------

const ROLE_COLORS = {
    manager: '#e74c3c',
    executor: '#2ecc71',
    planner: '#3498db',
    advisory: '#9b59b6',
    qa: '#f39c12',
    general: '#95a5a6',
};

const TOOL_CAT_COLORS = {
    management: '#e74c3c',
    editing: '#2ecc71',
    exploration: '#58a6ff',
    qa: '#f39c12',
    logging: '#9b59b6',
    research: '#3498db',
    other: '#8b949e',
};

function getAgentRole(name) {
    const n = name.toLowerCase();
    if (n.includes('manager') || n.includes('director')) return 'manager';
    if (n.includes('executor') || n.includes('fixer')) return 'executor';
    if (n.includes('planner')) return 'planner';
    if (['researcher','librarian','architect','ideator','estimator','improver','complexity','pattern','debugger','explore'].some(x => n.includes(x))) return 'advisory';
    if (['qa','test','docs','review'].some(x => n.includes(x))) return 'qa';
    return 'general';
}

function roleColor(name) { return ROLE_COLORS[getAgentRole(name)] || ROLE_COLORS.general; }

// ---------------------------------------------------------------------------
// Health badges
// ---------------------------------------------------------------------------

function healthBadge(value, good, warn, inverse = false) {
    let color;
    if (inverse) {
        color = value >= good ? '#2ecc71' : value >= warn ? '#f39c12' : '#e74c3c';
    } else {
        color = value <= good ? '#2ecc71' : value <= warn ? '#f39c12' : '#e74c3c';
    }
    return `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px"></span>`;
}

function failBadge(rate) { return healthBadge(rate, 0.05, 0.15); }

function preDispatchBadge(value, agentName) {
    if (value == null) return '';
    const role = getAgentRole(agentName);
    // Role-based thresholds: managers should dispatch fast, QA does heavy analysis first, general agents vary
    const thresholds = {
        manager:  [3, 8],
        qa:       [15, 40],
        general:  [20, 50],
    };
    const [good, warn] = thresholds[role] || [5, 15];
    return healthBadge(value, good, warn);
}

// ---------------------------------------------------------------------------
// Render: KPIs
// ---------------------------------------------------------------------------

function renderKPIs(summary) {
    document.getElementById('kpi-sessions').textContent = summary.total_sessions;
    document.getElementById('kpi-agents').textContent = summary.unique_agents;
    document.getElementById('kpi-tokens').textContent = formatTokens(summary.total_tokens);
    document.getElementById('kpi-tools').textContent = summary.total_tool_calls.toLocaleString();
    document.getElementById('kpi-failures').textContent = summary.total_failures.toLocaleString();
    document.getElementById('kpi-failrate').textContent = (summary.failure_rate * 100).toFixed(1) + '%';
    document.getElementById('subtitle').textContent =
        `Generated ${summary.generated_at || '—'} — ${summary.total_sessions} sessions analyzed`;
}

// ---------------------------------------------------------------------------
// Render: Charts
// ---------------------------------------------------------------------------

let charts = [];

function destroyCharts() {
    charts.forEach(c => c.destroy());
    charts = [];
}

function renderCharts(data) {
    Chart.defaults.color = '#8b949e';
    Chart.defaults.borderColor = '#30363d';

    const agentNames = Object.keys(data.agent_aggregates);
    const tokenData = agentNames.map(n => data.agent_aggregates[n].total_tokens);
    const invCounts = agentNames.map(n => data.agent_aggregates[n].count);
    const colors = agentNames.map(n => roleColor(n));

    // Tokens by agent
    charts.push(new Chart(document.getElementById('tokensByAgent'), {
        type: 'bar',
        data: {
            labels: agentNames,
            datasets: [{ label: 'Total Tokens', data: tokenData, backgroundColor: colors, borderRadius: 4 }]
        },
        options: {
            responsive: true,
            plugins: { title: { display: true, text: 'Total Tokens by Agent', color: '#e6edf3' }, legend: { display: false } },
            scales: { x: { ticks: { maxRotation: 45 } }, y: { beginAtZero: true } }
        }
    }));

    // Token timeline
    const sessions = data.sessions.slice().sort((a, b) => a.timestamp - b.timestamp);
    charts.push(new Chart(document.getElementById('tokenTimeline'), {
        type: 'line',
        data: {
            labels: sessions.map(s => formatTs(s.timestamp)),
            datasets: [{
                label: 'Session Tokens (tree)',
                data: sessions.map(s => s.root ? s.root.tree_tokens : 0),
                borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.1)',
                fill: true, tension: 0.3, pointRadius: 3,
            }]
        },
        options: {
            responsive: true,
            plugins: { title: { display: true, text: 'Token Usage Over Time', color: '#e6edf3' } },
            scales: { y: { beginAtZero: true } }
        }
    }));

    // Invocations doughnut
    charts.push(new Chart(document.getElementById('invocationsByAgent'), {
        type: 'doughnut',
        data: { labels: agentNames, datasets: [{ data: invCounts, backgroundColor: colors }] },
        options: {
            responsive: true,
            plugins: {
                title: { display: true, text: 'Invocations by Agent', color: '#e6edf3' },
                legend: { position: 'right', labels: { boxWidth: 12 } }
            }
        }
    }));

    // Radar — all agents selectable, top 6 selected by default
    buildRadarSelector(data, agentNames);
    renderRadarChart(data, agentNames.slice(0, 6));
}

// ---------------------------------------------------------------------------
// Radar chart — selectable agents
// ---------------------------------------------------------------------------

let radarChart = null;

function buildRadarSelector(data, allAgentNames) {
    const container = document.getElementById('radar-agent-selector');
    container.innerHTML = '';
    const top6 = new Set(allAgentNames.slice(0, 6));
    for (const name of allAgentNames) {
        const label = document.createElement('label');
        label.style.cssText = 'display:inline-flex;align-items:center;gap:3px;font-size:0.75em;padding:2px 6px;border-radius:4px;cursor:pointer;background:rgba(255,255,255,0.05);color:' + roleColor(name);
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.value = name;
        cb.checked = top6.has(name);
        cb.addEventListener('change', () => {
            const selected = Array.from(container.querySelectorAll('input:checked')).map(i => i.value);
            renderRadarChart(data, selected);
        });
        label.appendChild(cb);
        label.appendChild(document.createTextNode(name));
        container.appendChild(label);
    }
}

// ---------------------------------------------------------------------------
// Compute top tools per agent per category from session invocation data
// ---------------------------------------------------------------------------

let _topToolsCache = null;

// Build tool→category lookup from the JSON's tool_aggregates (Python is the authority)
function buildToolCategoryLookup(toolAggs) {
    const lookup = {};
    for (const ta of toolAggs) {
        lookup[ta.name] = ta.category;
    }
    return lookup;
}

function computeTopToolsByAgent(data) {
    if (_topToolsCache) return _topToolsCache;
    const catLookup = buildToolCategoryLookup(data.tool_aggregates);
    // agent -> category -> { toolName: count }
    const agentCatTools = {};

    function walkInvocation(inv) {
        const agent = inv.agent_name;
        if (!agentCatTools[agent]) agentCatTools[agent] = {};
        for (const tc of (inv.tool_calls || [])) {
            const cat = catLookup[tc.name];
            if (!cat || cat === 'excluded') continue;
            if (!agentCatTools[agent][cat]) agentCatTools[agent][cat] = {};
            agentCatTools[agent][cat][tc.name] = (agentCatTools[agent][cat][tc.name] || 0) + 1;
        }
        for (const child of (inv.children || [])) walkInvocation(child);
    }

    for (const session of (data.sessions || [])) {
        if (session.root) walkInvocation(session.root);
    }

    // Convert to sorted top-3 arrays
    const result = {};
    for (const [agent, cats] of Object.entries(agentCatTools)) {
        result[agent] = {};
        for (const [cat, tools] of Object.entries(cats)) {
            result[agent][cat] = Object.entries(tools)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 3)
                .map(([name, count]) => ({ name: shortenToolName(name), count }));
        }
    }
    _topToolsCache = result;
    return result;
}

const RADAR_CAT_KEYS = ['management', 'editing', 'exploration', 'qa', 'logging', 'research'];

function renderRadarChart(data, selectedNames) {
    if (radarChart) { radarChart.destroy(); charts = charts.filter(c => c !== radarChart); }
    const categories = ['total_management_calls', 'total_editing_calls', 'total_exploration_calls', 'total_qa_calls', 'total_logging_calls', 'total_research_calls'];
    const categoryLabels = ['Mgmt', 'Edit', 'Explore', 'QA', 'Log', 'Research'];
    const topTools = computeTopToolsByAgent(data);
    // Each agent: compute real %, normalize to own max, then sqrt scale
    const datasets = selectedNames.map(name => {
        const agg = data.agent_aggregates[name] || {};
        const counts = categories.map(cat => agg[cat] || 0);
        const agentTotal = counts.reduce((a, b) => a + b, 0);
        const pcts = counts.map(c => agentTotal ? c / agentTotal * 100 : 0);
        const maxPct = Math.max(...pcts, 1); // avoid /0
        // Normalize to max → sqrt → scale to 100
        const display = pcts.map(p => Math.round(Math.sqrt(p / maxPct) * 1000) / 10);
        return {
            label: name,
            data: display,
            _realPcts: pcts, // stash for tooltip
            _topTools: topTools[name] || {}, // per-category top tools
            borderColor: roleColor(name),
            backgroundColor: roleColor(name) + '22',
            pointRadius: 3,
        };
    });
    radarChart = new Chart(document.getElementById('usageRadar'), {
        type: 'radar',
        data: { labels: categoryLabels, datasets },
        options: {
            responsive: true,
            plugins: {
                title: { display: true, text: 'Agent Stat Block — sqrt-scaled, normalized to peak category', color: '#e6edf3' },
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const real = ctx.dataset._realPcts[ctx.dataIndex];
                            const catKey = RADAR_CAT_KEYS[ctx.dataIndex];
                            const tools = ctx.dataset._topTools[catKey] || [];
                            const lines = [`${ctx.dataset.label}: ${real.toFixed(1)}%`];
                            for (const t of tools) {
                                lines.push(`  ${t.name}: ${t.count}`);
                            }
                            return lines;
                        }
                    }
                }
            },
            scales: { r: { beginAtZero: true, max: 100, ticks: { display: false }, grid: { color: '#30363d' }, pointLabels: { color: '#8b949e' } } }
        }
    });
    charts.push(radarChart);
}

// ---------------------------------------------------------------------------
// Generic sortable table support
// ---------------------------------------------------------------------------

function setupSortableTable(tableId, dataArray, sortKeyExtractor, renderFn) {
    const table = document.getElementById(tableId);
    if (!table) return;
    const state = { key: null, dir: 'desc', data: dataArray };

    table.querySelectorAll('th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const key = th.dataset.sortKey;
            if (state.key === key) {
                state.dir = state.dir === 'desc' ? 'asc' : 'desc';
            } else {
                state.key = key;
                state.dir = 'desc';
            }
            // Update header indicators
            table.querySelectorAll('th.sortable').forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
            th.classList.add(state.dir === 'desc' ? 'sort-desc' : 'sort-asc');
            // Sort and re-render
            const sorted = [...state.data].sort((a, b) => {
                const av = sortKeyExtractor(a, key);
                const bv = sortKeyExtractor(b, key);
                if (av == null && bv == null) return 0;
                if (av == null) return 1;
                if (bv == null) return -1;
                const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv;
                return state.dir === 'desc' ? -cmp : cmp;
            });
            renderFn(sorted);
        });
    });
}

// ---------------------------------------------------------------------------
// Render: Agent efficiency table
// ---------------------------------------------------------------------------

function renderAgentTable(agentAggs) {
    // Convert object to array of [name, agg] for sortable rendering
    const entries = Array.isArray(agentAggs) ? agentAggs : Object.entries(agentAggs).map(([name, agg]) => ({ name, ...agg }));
    renderAgentRows(entries);
}

function renderAgentRows(rows) {
    const tbody = document.getElementById('agent-tbody');
    tbody.innerHTML = '';
    for (const row of rows) {
        const name = row.name;
        const role = getAgentRole(name);
        const cbd = row.avg_calls_before_dispatch;
        const cbdStr = cbd != null ? cbd.toFixed(1) : '—';
        const cbdBadge = preDispatchBadge(cbd, name);
        const fBadge = failBadge(row.avg_failure_rate);
        const models = (row.models_used || []).join(', ') || '—';
        tbody.innerHTML += `<tr>
            <td><span style="color:${ROLE_COLORS[role]};font-weight:600">${esc(name)}</span>
                <span class="role-tag role-${role}">${role}</span></td>
            <td class="num">${row.count}</td>
            <td class="num">${formatTokens(row.total_tokens)}</td>
            <td class="num">${formatTokens(row.avg_tokens)}</td>
            <td class="num">${row.avg_tool_calls.toFixed(1)}</td>
            <td class="num">${pct(row.avg_management_ratio)}</td>
            <td class="num">${pct(row.avg_editing_ratio)}</td>
            <td class="num">${pct(row.avg_exploration_ratio)}</td>
            <td class="num">${pct(row.avg_qa_ratio)}</td>
            <td class="num">${pct(row.avg_logging_ratio)}</td>
            <td class="num">${pct(row.avg_research_ratio)}</td>
            <td class="num">${fBadge}${pct(row.avg_failure_rate)}</td>
            <td class="num">${cbdBadge}${cbdStr}</td>
            <td class="num">${row.avg_turns.toFixed(1)}</td>
            <td class="num" style="font-size:0.8em">${esc(models)}</td>
        </tr>`;
    }
}

// ---------------------------------------------------------------------------
// Render: Tool health table
// ---------------------------------------------------------------------------

function shortenToolName(name) {
    for (const prefix of ['mcp_nomarr_dev_', 'mcp_oraios_serena_', 'mcp_context7_', 'mcp_gitkraken_']) {
        if (name.startsWith(prefix)) return name.slice(prefix.length);
    }
    return name;
}

function repeatBadge(rate) { return healthBadge(rate, 0.1, 0.25); }

function renderToolTable(toolAggs) {
    const rows = Array.isArray(toolAggs) ? toolAggs : toolAggs.filter(t => t.total_calls >= 1);
    renderToolRows(rows);
}

function renderToolRows(rows) {
    const tbody = document.getElementById('tool-tbody');
    tbody.innerHTML = '';
    for (const ta of rows) {
        const catColor = TOOL_CAT_COLORS[ta.category] || TOOL_CAT_COLORS.other;
        const fBadge = failBadge(ta.failure_rate);
        const rBadge = repeatBadge(ta.repeat_rate || 0);
        const agents = ta.agents.slice(0, 5).join(', ') + (ta.agents.length > 5 ? ` +${ta.agents.length - 5}` : '');
        tbody.innerHTML += `<tr>
            <td><span style="color:${catColor}">${esc(shortenToolName(ta.name))}</span></td>
            <td class="num"><span class="role-tag" style="background:rgba(255,255,255,0.05);color:${catColor}">${ta.category}</span></td>
            <td class="num">${ta.total_calls}</td>
            <td class="num">${fBadge}${ta.failures}</td>
            <td class="num">${fBadge}${(ta.failure_rate * 100).toFixed(1)}%</td>
            <td class="num">${rBadge}${ta.repeats || 0}</td>
            <td class="num">${rBadge}${((ta.repeat_rate || 0) * 100).toFixed(1)}%</td>
            <td class="num">${formatMs(ta.avg_duration_ms)}</td>
            <td class="num">${ta.agent_count}</td>
            <td style="font-size:0.75em;color:var(--text-dim)">${esc(agents)}</td>
        </tr>`;
    }
}

// ---------------------------------------------------------------------------
// Render: Session cards with recursive agent tree
// ---------------------------------------------------------------------------

let promptCounter = 0;

function invocationRowHtml(inv, depth = 0) {
    const role = getAgentRole(inv.agent_name);
    const indent = '&nbsp;'.repeat(depth * 4);
    const prefix = depth > 0 ? '└─ ' : '';
    const cbd = inv.calls_before_first_dispatch;
    const cbdStr = cbd != null ? String(cbd) : '—';
    const cbdBadge = preDispatchBadge(cbd, inv.agent_name);
    const fBadge = failBadge(inv.failure_rate);

    // Spawn prompt toggle
    let promptHtml = '';
    if (inv.spawn_prompt) {
        const pid = 'prompt-' + (promptCounter++);
        promptHtml = `<span class="prompt-toggle" onclick="event.stopPropagation();document.getElementById('${pid}').classList.toggle('visible')">📋 prompt</span>
            <div id="${pid}" class="prompt-content">${esc(inv.spawn_prompt)}</div>`;
    }

    let html = `<tr class="invocation-row" data-agent="${esc(inv.agent_name)}" data-role="${role}">
        <td style="white-space:nowrap">${indent}${prefix}<span style="color:${ROLE_COLORS[role]};font-weight:600">${esc(inv.agent_name)}</span>${promptHtml}</td>
        <td class="num">${inv.turn_count}</td>
        <td class="num">${formatTokens(inv.total_input_tokens)}</td>
        <td class="num">${formatTokens(inv.total_output_tokens)}</td>
        <td class="num"><strong>${formatTokens(inv.total_tokens)}</strong></td>
        <td class="num">${inv.tool_call_count}</td>
        <td class="num">${pct(inv.management_ratio)}</td>
        <td class="num">${pct(inv.editing_ratio)}</td>
        <td class="num">${pct(inv.exploration_ratio)}</td>
        <td class="num">${pct(inv.qa_ratio)}</td>
        <td class="num">${pct(inv.logging_ratio)}</td>
        <td class="num">${pct(inv.research_ratio)}</td>
        <td class="num">${fBadge}${inv.failure_count}/${inv.tool_call_count}</td>
        <td class="num">${cbdBadge}${cbdStr}</td>
        <td class="num">${formatMs(inv.wall_time_ms)}</td>
    </tr>\n`;

    const children = (inv.children || []).slice().sort((a, b) => a.timestamp - b.timestamp);
    for (const child of children) {
        html += invocationRowHtml(child, depth + 1);
    }
    return html;
}

function renderSessionCards(sessions) {
    const container = document.getElementById('session-container');
    container.innerHTML = '';
    promptCounter = 0;

    for (const session of sessions) {
        if (!session.root) continue;
        const root = session.root;
        const card = document.createElement('div');
        card.className = 'session-card';
        card.dataset.rootRole = getAgentRole(root.agent_name);

        card.innerHTML = `
        <div class="session-header" onclick="this.parentElement.classList.toggle('expanded')">
            <span class="session-time">${formatTs(session.timestamp)}</span>
            <span class="session-agent" style="color:${roleColor(root.agent_name)}">${esc(root.agent_name)}</span>
            <span class="session-stat">🔤 ${formatTokens(root.tree_tokens)} tokens</span>
            <span class="session-stat">🔧 ${root.tool_call_count} tools</span>
            <span class="session-stat">👶 ${(root.children || []).length} subagents</span>
            <span class="session-stat">🔄 ${root.turn_count} turns</span>
            <span class="expand-icon">▶</span>
        </div>
        <div class="session-detail">
            <table class="detail-table">
                <thead>
                    <tr>
                        <th>Agent</th><th>Turns</th><th>In</th><th>Out</th><th>Total</th>
                        <th>Tools</th><th>Mgmt%</th><th>Edit%</th><th>Explore%</th><th>QA%</th><th>Log%</th><th>Research%</th>
                        <th>Fail</th><th>Pre-dispatch</th><th>Wall</th>
                    </tr>
                </thead>
                <tbody>${invocationRowHtml(root)}</tbody>
            </table>
        </div>`;

        container.appendChild(card);
    }
}

// ---------------------------------------------------------------------------
// Session filtering
// ---------------------------------------------------------------------------

function filterSessions(role, btn) {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.session-card').forEach(card => {
        if (role === 'all') {
            card.style.display = '';
        } else {
            card.style.display = card.dataset.rootRole === role ? '' : 'none';
        }
    });
}

// ---------------------------------------------------------------------------
// Main: load data and render
// ---------------------------------------------------------------------------

function renderDashboard(data) {
    destroyCharts();
    document.getElementById('loading').style.display = 'none';
    document.getElementById('dashboard').style.display = 'block';

    // Inject generated_at into summary for KPI display
    data.summary.generated_at = data.generated_at;
    renderKPIs(data.summary);
    renderCharts(data);

    // Agent table — convert to flat array for sorting
    const agentRows = Object.entries(data.agent_aggregates).map(([name, agg]) => ({ name, ...agg }));
    renderAgentTable(agentRows);
    setupSortableTable('agent-table', agentRows, (row, key) => row[key], renderAgentRows);

    // Tool table
    const toolRows = data.tool_aggregates.filter(t => t.total_calls >= 1);
    renderToolTable(toolRows);
    setupSortableTable('tool-table', toolRows, (row, key) => row[key], renderToolRows);

    renderSessionCards(data.sessions);
}

function loadFromFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const data = JSON.parse(e.target.result);
            renderDashboard(data);
        } catch (err) {
            alert('Failed to parse JSON: ' + err.message);
        }
    };
    reader.readAsText(file);
}

document.addEventListener('DOMContentLoaded', () => {
    const uploadArea = document.getElementById('upload-area');
    const fileInput = document.getElementById('file-input');

    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length) loadFromFile(e.target.files[0]);
    });

    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('drag-over');
    });
    uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('drag-over'));
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('drag-over');
        if (e.dataTransfer.files.length) loadFromFile(e.dataTransfer.files[0]);
    });

    // Auto-load agent_dashboard.json if it exists alongside the HTML (same directory)
    fetch('agent_dashboard.json')
        .then(r => { if (!r.ok) throw new Error('not found'); return r.json(); })
        .then(data => renderDashboard(data))
        .catch(() => {
            // No auto-load file found — user must upload
            document.getElementById('auto-load-status').textContent =
                'No agent_dashboard.json found. Upload a file or place the JSON alongside this HTML.';
        });
});
