/**
 * FX Auto-Bot Dashboard — script.js
 * Handles all API polling, rendering, and UI interactions.
 */

// Initialize Theme Immediately (prevent flash)
(function() {
    const theme = localStorage.getItem("theme") || "dark";
    if (theme === "light") {
        document.body.classList.add("light-theme", "light-theme-active");
    }
})();

const API_BASE = "/api";
const POLL_INTERVAL = 10000; // 10 seconds

// ── HTTP Helpers ──────────────────────────────────────────────────────────────

async function fetchAPI(endpoint) {
    try {
        const res = await fetch(`${API_BASE}${endpoint}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (err) {
        console.warn(`fetchAPI ${endpoint}:`, err.message);
        return null;
    }
}

async function postAPI(endpoint, data) {
    try {
        const res = await fetch(`${API_BASE}${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (err) {
        console.warn(`postAPI ${endpoint}:`, err.message);
        return null;
    }
}

// ── Status & Account ──────────────────────────────────────────────────────────

function updateStatus(status) {
    const pulse = document.getElementById("status-pulse");
    const text  = document.getElementById("status-text");
    const toggle = document.getElementById("auto-trade-toggle");
    if (!status) {
        pulse.className = "pulse error";
        text.innerText = "Offline";
        return;
    }
    if (status.emergency_stop) {
        pulse.className = "pulse error";
        text.innerText = "STOPPED";
        text.style.color = "var(--danger)";
        toggle.checked = false;
    } else {
        pulse.className = "pulse active";
        text.innerText = "Bot Active";
        text.style.color = "var(--text-main)";
        toggle.checked = true;
    }
}

async function toggleAutoTrade() {
    const toggle = document.getElementById("auto-trade-toggle");
    const res = await postAPI("/trading/toggle", { enabled: toggle.checked });
    if (res) updateStatus(res);
}

function updateKPIs(stats) {
    if (!stats) return;
    const pnlEl = document.getElementById("kpi-pnl");
    const pnl = stats.pnl_usd || 0;
    pnlEl.innerText = pnl >= 0 ? `+$${pnl.toFixed(2)}` : `-$${Math.abs(pnl).toFixed(2)}`;
    pnlEl.className = `value pnl ${pnl < 0 ? "negative" : ""}`;
    document.getElementById("kpi-winrate").innerText = `${stats.win_rate || 0}%`;
    document.getElementById("kpi-open").innerText = stats.open_trades || 0;
    document.getElementById("open-badge").innerText = stats.open_trades || 0;
}

function updateAccount(acc) {
    if (!acc || acc.error) return;
    const fmt = (v) => `$${(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    document.getElementById("acc-balance").innerText = fmt(acc.balance);
    document.getElementById("acc-equity").innerText  = fmt(acc.equity);
    document.getElementById("acc-margin").innerText  = fmt(acc.margin_free);
}

// ── Active Pairs ──────────────────────────────────────────────────────────────

let currentSymbols = [];

function renderSymbols(symbols) {
    currentSymbols = symbols;
    const container = document.getElementById("pairs-list");
    container.innerHTML = symbols.map(s =>
        `<div class="pair-tag" onclick="removeSymbol('${s}')" title="Click to remove">
            ${s} <span>&times;</span>
        </div>`
    ).join("");
}

async function addSymbol() {
    const input = document.getElementById("new-pair-input");
    const sym = input.value.trim().toUpperCase();
    if (!sym) return;
    if (currentSymbols.includes(sym)) {
        input.value = "";
        return;
    }
    const res = await postAPI("/settings/symbols", { symbols: [...currentSymbols, sym] });
    if (res && res.success) { renderSymbols(res.symbols); input.value = ""; }
}

async function removeSymbol(sym) {
    const updated = currentSymbols.filter(s => s !== sym);
    const res = await postAPI("/settings/symbols", { symbols: updated });
    if (res && res.success) renderSymbols(res.symbols);
}

document.getElementById("add-pair-btn").addEventListener("click", addSymbol);
document.getElementById("new-pair-input").addEventListener("keypress", e => { if (e.key === "Enter") addSymbol(); });

// ── Trade Tables ──────────────────────────────────────────────────────────────

function renderOpenTrades(trades) {
    const tbody = document.querySelector("#open-trades-table tbody");
    const empty = document.getElementById("open-empty");
    if (!trades || trades.length === 0) {
        tbody.innerHTML = "";
        empty.style.display = "block";
        return;
    }
    empty.style.display = "none";
    tbody.innerHTML = trades.map(t => {
        const dirClass = t.direction === "BUY" ? "dir-buy" : "dir-sell";
        return `<tr>
            <td><b>${t.symbol}</b></td>
            <td><span class="badge-dir ${dirClass}">${t.direction}</span></td>
            <td>${t.lot_size}</td>
            <td>${t.open_price?.toFixed(5) || "-"}</td>
            <td>${t.sl_price?.toFixed(5) || "-"}</td>
            <td>${t.tp_price?.toFixed(5) || "-"}</td>
            <td>${t.score?.toFixed(1) || "-"}</td>
            <td><button class="btn-danger-sm" onclick="closeTrade(${t.ticket})">Close</button></td>
        </tr>`;
    }).join("");
}

async function closeTrade(ticket) {
    if (!confirm(`Are you sure you want to close position #${ticket}?`)) return;
    const res = await postAPI("/trades/close", { ticket: ticket });
    if (res && res.success) {
        alert("Close request sent successfully!");
        refreshDashboard();
    } else {
        alert("Error: " + (res?.error || "Failed to close trade."));
    }
}

function renderHistoryTrades(history) {
    const tbody = document.querySelector("#history-trades-table tbody");
    const empty = document.getElementById("history-empty");
    if (!history || history.length === 0) {
        tbody.innerHTML = "";
        empty.style.display = "block";
        return;
    }
    empty.style.display = "none";
    tbody.innerHTML = history.map(t => {
        const pnl = t.pnl_usd || 0;
        const pnlColor = pnl >= 0 ? "var(--success)" : "var(--danger)";
        const dirClass = t.direction === "BUY" ? "dir-buy" : "dir-sell";
        return `<tr>
            <td><b>${t.symbol}</b></td>
            <td><span class="badge-dir ${dirClass}">${t.direction}</span></td>
            <td>${t.lot_size}</td>
            <td style="color:${pnlColor};font-weight:600">${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}</td>
            <td>${t.close_reason || "-"}</td>
        </tr>`;
    }).join("");
}

// ── Scanner Activity Panel ───────────────────────────────────────────────────

function renderScannerActivity(signals) {
    const tbody = document.querySelector("#scanner-activity-table tbody");
    const empty = document.getElementById("scanner-empty");
    if (!signals || signals.length === 0) {
        tbody.innerHTML = "";
        empty.style.display = "flex";
        return;
    }
    empty.style.display = "none";
    tbody.innerHTML = signals.map(sig => {
        const timeStr = sig.created_at
            ? new Date(sig.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
            : "";
        
        let statusHtml = "";
        if (sig.direction === "NEUTRAL") {
            statusHtml = `<span class="badge-dir sent-neutral" style="background:rgba(255,255,255,0.05);color:var(--text-muted);border:1px solid rgba(255,255,255,0.1)">NEUTRAL</span> <span style="font-size:0.8rem;color:var(--text-muted);margin-left:8px;">${sig.reason_skip || "Skipped"}</span>`;
        } else {
            const dirClass = sig.direction === "BUY" ? "dir-buy" : "dir-sell";
            statusHtml = `<span class="badge-dir ${dirClass}">${sig.direction}</span> ${sig.passed ? '<span style="color:var(--success);font-size:0.82rem;margin-left:8px;font-weight:600;">&#10003; PASSED</span>' : `<span style="color:var(--danger);font-size:0.82rem;margin-left:8px;font-weight:600;">&#10007; SKIPPED: ${sig.reason_skip || "Low Score"}</span>`}`;
        }

        const scoreVal = sig.score !== undefined ? sig.score.toFixed(1) : "-";
        
        return `<tr>
            <td style="color:var(--text-muted);font-size:0.82rem;">${timeStr}</td>
            <td><b>${sig.symbol}</b></td>
            <td><span style="font-weight:700">${scoreVal}</span></td>
            <td>${sig.score_trend !== undefined ? sig.score_trend.toFixed(0) : "-"}</td>
            <td>${sig.score_structure !== undefined ? sig.score_structure.toFixed(0) : "-"}</td>
            <td>${sig.score_liquidity !== undefined ? sig.score_liquidity.toFixed(0) : "-"}</td>
            <td>${sig.score_momentum !== undefined ? sig.score_momentum.toFixed(0) : "-"}</td>
            <td>${sig.score_session !== undefined ? sig.score_session.toFixed(0) : "-"}</td>
            <td>${statusHtml}</td>
        </tr>`;
    }).join("");

    // Update last-refreshed indicator
    const indicator = document.getElementById("scanner-last-updated");
    if (indicator) {
        indicator.innerText = `Updated: ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    }
}

async function refreshScannerActivity() {
    const btn = document.getElementById("btn-refresh-scanner");
    if (btn) btn.disabled = true;
    try {
        const signals = await fetchAPI("/signals");
        renderScannerActivity(signals || []);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function clearScannerActivity() {
    if (!confirm("Are you sure you want to clear all scanner activity logs?")) return;
    const btn = document.getElementById("btn-clear-scanner");
    if (btn) btn.disabled = true;
    try {
        const res = await postAPI("/signals/clear", {});
        if (res && res.success) {
            renderScannerActivity([]);
        } else {
            alert("Failed to clear scanner activity.");
        }
    } finally {
        if (btn) btn.disabled = false;
    }
}


// ── AI Panels ─────────────────────────────────────────────────────────────────

function sentimentClass(s) {
    if (s === "BULLISH") return "sent-bullish";
    if (s === "BEARISH") return "sent-bearish";
    return "sent-neutral";
}

function renderAISignals(signals) {
    const container = document.getElementById("ai-signals-container");
    const empty = document.getElementById("ai-signals-empty");
    if (!signals || signals.length === 0) {
        if (empty) empty.style.display = "block";
        container.querySelectorAll(".ai-card").forEach(el => el.remove());
        return;
    }
    if (empty) empty.style.display = "none";
    
    // Clear old cards
    container.querySelectorAll(".ai-card").forEach(el => el.remove());
    
    signals.forEach(sig => {
        const adj = sig.ai_score_adjustment || 0;
        const adjStr = adj >= 0
            ? `<span style="color:var(--success)">+${adj.toFixed(1)}</span>`
            : `<span style="color:var(--danger)">${adj.toFixed(1)}</span>`;
            
        let summaryText = sig.ai_summary || "";
        const isError = summaryText.includes("AI error:") || summaryText.includes("limit") || summaryText.includes("quota") || summaryText.includes("unavailable");
        
        const card = document.createElement("div");
        card.className = isError ? "ai-card error-state" : "ai-card";
        
        if (isError) {
            card.innerHTML = `
                <div class="ai-card-header">
                    <span class="ai-card-symbol" style="color:var(--danger)">System Warning</span>
                    <span class="ai-sentiment-badge sent-bearish">ERROR</span>
                </div>
                <div class="ai-summary-text" style="color:var(--danger); font-size:0.8rem; display:flex; align-items:flex-start; gap:6px;">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="flex-shrink:0; margin-top:2px;"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <span>${summaryText.replace("AI error: ", "")}</span>
                </div>
            `;
        } else {
            card.innerHTML = `
                <div class="ai-card-header">
                    <span class="ai-card-symbol">${sig.symbol}</span>
                    <span class="badge-dir ${sig.direction === "BUY" ? "dir-buy" : "dir-sell"}">${sig.direction}</span>
                    <span class="ai-sentiment-badge ${sentimentClass(sig.ai_sentiment)}">${sig.ai_sentiment || "N/A"}</span>
                </div>
                <div class="ai-score-row">
                    <span>Score: <b>${(sig.score || 0).toFixed(1)}</b></span>
                    <span>&bull;</span>
                    <span>AI adj: <b>${adjStr}</b></span>
                    <span>&bull;</span>
                    ${sig.passed
                        ? '<span style="color:var(--success)">&#10003; PASSED</span>'
                        : '<span style="color:var(--danger)">&#10007; SKIPPED</span>'}
                </div>
                <div class="ai-summary-text">${summaryText}</div>
            `;
        }
        container.appendChild(card);
    });
}

function renderAIPostmortems(history) {
    const container = document.getElementById("ai-postmortems-container");
    const empty = document.getElementById("ai-postmortems-empty");
    const aiTrades = (history || []).filter(t => t.ai_analysis);
    if (aiTrades.length === 0) {
        if (empty) empty.style.display = "block";
        return;
    }
    if (empty) empty.style.display = "none";
    container.innerHTML = aiTrades.map(t => {
        const pnl = t.pnl_usd || 0;
        const pnlColor = pnl >= 0 ? "var(--success)" : "var(--danger)";
        return `<div class="ai-postmortem-card">
            <div class="ai-card-header">
                <span class="ai-card-symbol">${t.symbol} ${t.direction}</span>
                <span style="color:${pnlColor};font-weight:700">${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}</span>
                <span style="font-size:0.75rem;color:var(--text-muted)">${t.close_reason}</span>
            </div>
            <div class="ai-summary-text">${t.ai_analysis}</div>
        </div>`;
    }).join("");
}

// ── MT5 News ─────────────────────────────────────────────────────────────────

function renderNews(news) {
    const container = document.getElementById("news-container");
    const empty = document.getElementById("news-empty");
    if (!news || news.length === 0) {
        if (empty) { empty.style.display = "block"; empty.innerText = "No news available from MT5. Ensure MT5 is running."; }
        return;
    }
    if (empty) empty.style.display = "none";
    container.innerHTML = news.map(item => {
        const timeStr = item.time
            ? new Date(item.time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
            : "";
        return `<div class="news-item">
            <div class="news-meta">
                <span class="news-time">${timeStr}</span>
                ${item.category ? `<span class="news-cat">${item.category}</span>` : ""}
            </div>
            <div class="news-subject">${item.subject || "No subject"}</div>
        </div>`;
    }).join("");
}

// ── Forex Calendar ────────────────────────────────────────────────────────────

// ── Forex Calendar Filtering ──────────────────────────────────────────────────
let allCalendarEvents = [];

function filterCalendar() {
    const impactFilter = document.getElementById("cal-impact-filter").value; // ALL, HIGH, MEDIUM
    const currencyFilter = document.getElementById("cal-currency-filter").value; // ALL, USD, EUR, etc.
    
    let filtered = allCalendarEvents;
    
    if (impactFilter !== "ALL") {
        filtered = filtered.filter(e => e.impact?.toUpperCase() === impactFilter);
    }
    
    if (currencyFilter !== "ALL") {
        filtered = filtered.filter(e => e.currency?.toUpperCase() === currencyFilter);
    }
    
    renderCalendarList(filtered);
}

function renderCalendarList(events) {
    const container = document.getElementById("calendar-container");
    const empty = document.getElementById("calendar-empty");
    if (!events || events.length === 0) {
        if (empty) {
            empty.style.display = "block";
            empty.innerHTML = `
                <svg class="empty-icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                <p class="empty-title">No Matching Events</p>
                <span class="empty-hint">Try adjusting your filters.</span>
            `;
        }
        container.querySelectorAll(".calendar-event").forEach(el => el.remove());
        return;
    }
    if (empty) empty.style.display = "none";
    
    // Clear old items but keep empty container
    container.querySelectorAll(".calendar-event").forEach(el => el.remove());
    
    events.forEach(e => {
        const impactClass = e.impact?.toLowerCase() === "high" ? "impact-high" : "impact-medium";
        const timeStr = e.time ? e.time.split("T")[1]?.slice(0, 5) || e.time : "";
        const div = document.createElement("div");
        div.className = "calendar-event";
        div.innerHTML = `
            <div class="cal-left">
                <span class="cal-time">${timeStr}</span>
                <span class="cal-currency">${e.currency}</span>
            </div>
            <div class="cal-center">
                <span class="cal-impact ${impactClass}"></span>
                <span class="cal-title">${e.event}</span>
            </div>
            <div class="cal-right">
                ${e.forecast ? `<span class="cal-stat">F: ${e.forecast}</span>` : ""}
                ${e.previous ? `<span class="cal-stat muted">P: ${e.previous}</span>` : ""}
            </div>
        `;
        container.appendChild(div);
    });
}

// ── AI Settings Modal ─────────────────────────────────────────────────────────

const PROVIDER_MODELS = {
    gemini:     ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"],
    openai:     ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
    anthropic:  ["claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022"],
    openrouter: ["meta-llama/llama-3.3-70b-instruct", "meta-llama/llama-3.1-8b-instruct", "meta-llama/llama-3.3-70b-instruct:free", "meta-llama/llama-3.2-3b-instruct:free"],
};

const PROVIDER_KEY_HINTS = {
    gemini:     'Get free key: <a href="https://aistudio.google.com/app/apikey" target="_blank">aistudio.google.com</a>',
    openai:     'Get key: <a href="https://platform.openai.com/api-keys" target="_blank">platform.openai.com</a>',
    anthropic:  'Get key: <a href="https://console.anthropic.com/" target="_blank">console.anthropic.com</a>',
    openrouter: 'Get free key: <a href="https://openrouter.ai/keys" target="_blank">openrouter.ai</a> (has free models!)',
};

function updateModelOptions() {
    const provider = document.getElementById("ai-provider-select").value;
    const modelSel = document.getElementById("ai-model-select");
    modelSel.innerHTML = (PROVIDER_MODELS[provider] || []).map(m =>
        `<option value="${m}">${m}</option>`
    ).join("");
    document.getElementById("ai-key-hint").innerHTML = PROVIDER_KEY_HINTS[provider] || "";
}

async function openAIModal() {
    const data = await fetchAPI("/settings/ai");
    if (data) {
        const provSel = document.getElementById("ai-provider-select");
        provSel.value = data.provider || "gemini";
        updateModelOptions();
        document.getElementById("ai-model-select").value = data.model || "";
        document.getElementById("ai-budget-input").value = data.monthly_budget || 5.0;
        document.getElementById("ai-api-key-input").value = "";
        document.getElementById("ai-api-key-input").placeholder = data.api_key_set
            ? `Key set (${data.api_key_masked}) — paste to replace`
            : "Paste your API key here...";

        const badge = document.getElementById("key-status-badge");
        badge.textContent = data.api_key_set ? "Configured" : "Not Set";
        badge.className = `key-badge ${data.api_key_set ? "key-set" : "key-not-set"}`;

        const spend = data.spend_mtd || 0;
        const budget = data.monthly_budget || 5.0;
        const pct = Math.min(100, (spend / budget) * 100);
        document.getElementById("ai-spend-text").innerText = `$${spend.toFixed(4)} / $${budget.toFixed(2)}`;
        document.getElementById("ai-spend-bar").style.width = `${pct}%`;
        document.getElementById("ai-spend-bar").style.background = pct > 80 ? "var(--danger)" : "var(--accent)";
    }
    document.getElementById("ai-modal-overlay").classList.add("active");
}

function closeAIModal() {
    document.getElementById("ai-modal-overlay").classList.remove("active");
    const resultDiv = document.getElementById("ai-test-result");
    if (resultDiv) {
        resultDiv.style.display = "none";
        resultDiv.innerText = "";
    }
}

async function saveAISettings() {
    const payload = {
        provider: document.getElementById("ai-provider-select").value,
        model:    document.getElementById("ai-model-select").value,
        monthly_budget: parseFloat(document.getElementById("ai-budget-input").value) || 5.0,
    };
    const key = document.getElementById("ai-api-key-input").value.trim();
    if (key) payload.api_key = key;

    const res = await postAPI("/settings/ai", payload);
    if (res && res.success) {
        alert("AI settings saved! Restart the bot for changes to take effect.");
        closeAIModal();
        refreshAIStatus();
    }
}

async function testAISettings() {
    const btn = document.getElementById("btn-test-ai");
    const resultDiv = document.getElementById("ai-test-result");
    if (!btn || !resultDiv) return;

    btn.disabled = true;
    const originalText = btn.innerText;
    btn.innerText = "Testing...";

    resultDiv.style.display = "block";
    resultDiv.style.background = "rgba(255, 255, 255, 0.05)";
    resultDiv.style.color = "var(--text-muted)";
    resultDiv.innerText = "Sending test request to AI provider...";

    const payload = {
        provider: document.getElementById("ai-provider-select").value,
        model:    document.getElementById("ai-model-select").value,
        api_key:  document.getElementById("ai-api-key-input").value.trim()
    };

    try {
        const res = await postAPI("/settings/ai/test", payload);
        if (res && res.success) {
            resultDiv.style.background = "rgba(46, 213, 115, 0.1)";
            resultDiv.style.color = "#2ed573";
            resultDiv.style.border = "1px solid rgba(46, 213, 115, 0.2)";
            resultDiv.innerText = `Success! AI responded: "${res.response}"`;
        } else {
            resultDiv.style.background = "rgba(255, 71, 87, 0.1)";
            resultDiv.style.color = "#ff4757";
            resultDiv.style.border = "1px solid rgba(255, 71, 87, 0.2)";
            resultDiv.innerText = `Error: ${res?.error || "Unknown error occurred"}`;
        }
    } catch (err) {
        resultDiv.style.background = "rgba(255, 71, 87, 0.1)";
        resultDiv.style.color = "#ff4757";
        resultDiv.style.border = "1px solid rgba(255, 71, 87, 0.2)";
        resultDiv.innerText = `Request Failed: ${err.message}`;
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

async function resetAISpend() {
    if (!confirm("Reset this month's AI spend counter to $0.00?")) return;
    await postAPI("/settings/ai/reset-spend", {});
    openAIModal();
}

async function refreshAIStatus() {
    const data = await fetchAPI("/settings/ai");
    const dot = document.getElementById("ai-dot");
    const badge = document.getElementById("ai-provider-badge");
    if (data) {
        const providerLabels = { gemini: "Gemini", openai: "GPT", anthropic: "Claude", openrouter: "OpenRouter" };
        badge.textContent = providerLabels[data.provider] || data.provider;
        dot.className = `ai-status-dot ${data.ai_enabled ? "ai-on" : "ai-off"}`;
    }
}

// ── Main Refresh Loop ─────────────────────────────────────────────────────────

async function refreshDashboard() {
    const [status, stats, openTrades, history, accData, aiSignals, signals] = await Promise.all([
        fetchAPI("/status"),
        fetchAPI("/stats/today"),
        fetchAPI("/trades/open"),
        fetchAPI("/trades/history"),
        fetchAPI("/account"),
        fetchAPI("/ai/recent-signals"),
        fetchAPI("/signals"),
    ]);

    updateStatus(status);
    updateKPIs(stats);
    updateAccount(accData);
    renderOpenTrades(openTrades);
    renderHistoryTrades(history);
    renderAISignals(aiSignals || []);
    renderAIPostmortems(history || []);
    renderScannerActivity(signals || []);
}

async function refreshSlowData() {
    const [symbolsData, news, calendar] = await Promise.all([
        fetchAPI("/settings/symbols"),
        fetchAPI("/news"),
        fetchAPI("/calendar"),
    ]);

    if (symbolsData?.symbols) {
        renderSymbols(symbolsData.symbols);
    }
    renderNews(news || []);
    if (calendar) {
        allCalendarEvents = calendar;
        filterCalendar();
    }
}

// Initial load + periodic refresh
refreshDashboard();
refreshSlowData();
refreshAIStatus();
setInterval(refreshDashboard, POLL_INTERVAL);
setInterval(refreshSlowData, 120000); // Check news/calendar every 2 minutes
setInterval(refreshAIStatus, 60000); // Check AI status every minute

// ── Theme Switcher & Manual Scan Helpers ─────────────────────────────────────

function toggleTheme() {
    const isLight = document.body.classList.toggle("light-theme");
    document.body.classList.toggle("light-theme-active", isLight);
    localStorage.setItem("theme", isLight ? "light" : "dark");
}

async function triggerManualScan() {
    const btn = document.getElementById("btn-run-scan");
    if (!btn) return;
    
    const originalText = btn.innerText;
    btn.disabled = true;
    btn.innerText = "Scanning...";
    
    try {
        const res = await postAPI("/scanner/scan", {});
        if (res && res.success) {
            await refreshDashboard();
        } else {
            alert("Scanner error: " + (res?.error || "Unknown scanner failure"));
        }
    } catch (err) {
        alert("Request failed: " + err.message);
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

