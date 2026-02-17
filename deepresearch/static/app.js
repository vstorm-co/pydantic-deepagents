// DeepResearch Frontend with WebSocket Streaming

// WebSocket connection
let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

// Session management - only restore from URL params (fork links), not localStorage
let sessionId = new URLSearchParams(window.location.search).get('session_id') || null;

// State
let currentTab = 'sessions';
let configData = null;
let toolStats = { call_count: 0, tools_used: {}, total_duration_ms: 0 };

// Excalidraw state
let excalidrawCanvasShown = false;
let excalidrawCanvasUrl = null;

// Background agents counter
let backgroundAgentCount = 0;
const backgroundAgentTasks = new Set(); // track task IDs

// DOM Elements
const messagesContainer = document.getElementById('messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const filesList = document.getElementById('files-list');

// Smart auto-scroll: only scrolls if user is near the bottom
function autoScroll() {
    const threshold = 150;
    const atBottom = messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight < threshold;
    if (atBottom) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

// Force scroll: always scrolls to bottom (used for new user messages, initial load)
function forceScroll() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// Replay flag — suppresses animations and auto-scroll during replay
let isReplay = false;

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    setupResizer();
    connectWebSocket();
    refreshFiles();
    loadExcalidrawConfig();
    loadSessionsList();
    if (sessionId) {
        loadSession(sessionId);
    }
});

// Load Excalidraw canvas URL from config at startup
async function loadExcalidrawConfig() {
    try {
        const response = await fetch('/config');
        if (response.ok) {
            const raw = await response.json();
            const cfg = raw.features || raw;
            if (cfg.excalidraw_canvas_url) {
                excalidrawCanvasUrl = cfg.excalidraw_canvas_url;
            }
        }
    } catch { /* config not available yet */ }
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        updateConnectionStatus(true);
        // Send session join immediately so backend can set up canvas isolation
        if (sessionId) {
            ws.send(JSON.stringify({ session_id: sessionId }));
        }
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);

        if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            reconnectAttempts++;
            setTimeout(connectWebSocket, 2000 * reconnectAttempts);
        }
    };

    ws.onerror = (error) => {
        console.error('WebSocket error:', error);
    };

    ws.onmessage = handleWebSocketMessage;
}

async function loadSession(sid) {
    if (!sid) return;
    try {
        // Try JSONL event replay first (full fidelity)
        const resp = await fetch(`/sessions/${encodeURIComponent(sid)}/events`);
        if (resp.ok) {
            const data = await resp.json();
            if (data.events && data.events.length > 0) {
                await replayEvents(data.events);
                return;
            }
        }
        // Fallback to old history endpoint
        const histResp = await fetch(`/history?session_id=${encodeURIComponent(sid)}`);
        if (!histResp.ok) return;
        const histData = await histResp.json();
        if (histData.messages && histData.messages.length > 0) {
            replayHistoryMessages(histData.messages);
        }
    } catch (e) {
        console.error('Failed to load session:', e);
    }
}

async function replayEvents(events) {
    isReplay = true;

    // Clear messages but keep welcome banner hidden
    messagesContainer.innerHTML = '';

    // Filter to important events for replay (skip noisy deltas)
    const replayableTypes = new Set([
        'session_created', 'user_message', 'start', 'tool_call_start', 'tool_start',
        'tool_output', 'text_delta', 'thinking_delta', 'response', 'todos_update',
        'done', 'cancelled', 'error', 'approval_required', 'ask_user_question',
        'checkpoint_saved', 'checkpoint_rewind', 'background_task_completed',
        'report_updated',
    ]);

    for (const event of events) {
        if (!replayableTypes.has(event.type)) continue;

        // For user messages, render as user bubble
        if (event.type === 'user_message') {
            if (event.content) addMessage(event.content, 'user');
            continue;
        }

        // Replay through the normal handler
        handleWebSocketMessage({ data: JSON.stringify(event) });
    }

    isReplay = false;
    updateOutlinePanel();
    // Scroll to bottom after replay
    forceScroll();
}

function replayHistoryMessages(messages) {
    // Fallback: old-style history replay
    isReplay = true;
    messagesContainer.innerHTML = '';

    let historyMsgEl = null;
    let lastToolEl = null;

    for (const msg of messages) {
        if (msg.role === 'user') {
            addMessage(msg.content, 'user');
            historyMsgEl = null;
            lastToolEl = null;
        } else if (msg.role === 'assistant') {
            if (historyMsgEl) {
                const contentEl = historyMsgEl.querySelector('.message-content');
                if (contentEl && msg.content) contentEl.innerHTML = formatMessage(msg.content);
            } else {
                addMessage(msg.content, 'assistant');
            }
            historyMsgEl = null;
            lastToolEl = null;
        } else if (msg.role === 'tool_call') {
            if (!historyMsgEl) historyMsgEl = createMessageContainer('assistant');
            const toolsEl = historyMsgEl.querySelector('.message-tools');
            if (!toolsEl) continue;

            // Hidden tools: skip rendering (shown in dedicated UI components)
            if (HIDDEN_TOOLS.has(msg.tool_name)) {
                lastToolEl = null;
                continue;
            }

            const toolEl = document.createElement('div');
            toolEl.dataset.toolName = msg.tool_name;

            // Render specialized cards for known tool types
            if (_isTeamCall(msg.tool_name)) {
                toolEl.className = 'tool-call team-card';
                toolEl.innerHTML = _renderTeamCard(msg.tool_name, msg.args, 'done');
            } else if (_isSubagentCall(msg.tool_name, msg.args)) {
                toolEl.className = 'tool-call subagent-delegation';
                toolEl.innerHTML = _renderSubagentCard(_isSubagentCall(msg.tool_name, msg.args), 'done');
            } else if (_isAgentFactoryCall(msg.tool_name, msg.args)) {
                toolEl.className = 'tool-call subagent-delegation';
                toolEl.innerHTML = _renderFactoryCard(_isAgentFactoryCall(msg.tool_name, msg.args), 'done');
            } else if (_isSearchCall(msg.tool_name)) {
                toolEl.className = 'tool-call search-tool-card';
                toolEl.innerHTML = _renderSearchCard(msg.tool_name, msg.args, 'done');
            } else if (_isExcalidrawCall(msg.tool_name)) {
                toolEl.className = 'tool-call excalidraw-compact';
                toolEl.innerHTML = _renderExcalidrawCard(msg.tool_name, 'done');
            } else {
                const collapsed = _isCollapsibleTool(msg.tool_name);
                const iconClass = _getToolIcon(msg.tool_name);
                const catColor = _getToolCategoryColor(msg.tool_name);
                toolEl.className = 'tool-call' + (collapsed ? ' collapsible collapsed' : '');
                toolEl.dataset.toolName = msg.tool_name;
                toolEl.innerHTML = `
                    <div class="tool-header"${collapsed ? ' onclick="this.parentElement.classList.toggle(\'collapsed\')" style="cursor:pointer"' : ''}>
                        <span class="tool-icon-badge" style="background:${catColor}22;color:${catColor}"><i class="${iconClass}"></i></span>
                        <span class="tool-name" style="color:${catColor}">${escapeHtml(msg.tool_name)}</span>
                        <span class="tool-status done"></span>
                        ${collapsed ? '<i class="ri-arrow-down-s-line collapse-chevron"></i>' : ''}
                    </div>
                    <div class="tool-output"></div>
                `;
            }
            // Group consecutive collapsible tools of the same type
            if (_isCollapsibleTool(msg.tool_name)) {
                const lastChild = toolsEl.lastElementChild;
                const tn = msg.tool_name;
                if (lastChild && lastChild.classList.contains('tool-group') && lastChild.dataset.toolName === tn) {
                    const itemsEl = lastChild.querySelector('.tool-group-items');
                    itemsEl.appendChild(toolEl);
                    lastChild.querySelector('.tool-group-count').textContent = `×${itemsEl.children.length}`;
                    lastToolEl = toolEl;
                    continue;
                } else if (lastChild && lastChild.classList.contains('tool-call') && lastChild.dataset.toolName === tn && _isCollapsibleTool(tn)) {
                    const iconClass2 = _getToolIcon(tn);
                    const catColor2 = _getToolCategoryColor(tn);
                    const groupEl = document.createElement('div');
                    groupEl.className = 'tool-group collapsed';
                    groupEl.dataset.toolName = tn;
                    groupEl.innerHTML = `
                        <div class="tool-group-header" onclick="this.parentElement.classList.toggle('collapsed')">
                            <span class="tool-icon-badge" style="background:${catColor2}22;color:${catColor2}"><i class="${iconClass2}"></i></span>
                            <span class="tool-name" style="color:${catColor2}">${escapeHtml(tn)}</span>
                            <span class="tool-group-count">×2</span>
                            <i class="ri-arrow-down-s-line collapse-chevron"></i>
                        </div>
                        <div class="tool-group-items"></div>
                    `;
                    const itemsEl = groupEl.querySelector('.tool-group-items');
                    toolsEl.replaceChild(groupEl, lastChild);
                    itemsEl.appendChild(lastChild);
                    itemsEl.appendChild(toolEl);
                    lastToolEl = toolEl;
                    continue;
                }
            }
            toolsEl.appendChild(toolEl);
            lastToolEl = toolEl;
        } else if (msg.role === 'tool_return') {
            if (!lastToolEl) continue;
            const outputEl = lastToolEl.querySelector('.tool-output');
            if (outputEl && msg.output) {
                const output = msg.output;
                outputEl.innerHTML = `<div class="tool-output-wrap"><pre>${escapeHtml(output.length > 500 ? output.substring(0, 500) + '...' : output)}</pre></div>`;
            }
            lastToolEl = null;
        }
    }

    isReplay = false;
    updateOutlinePanel();
    forceScroll();
}

function updateConnectionStatus(connected) {
    sendBtn.disabled = !connected;
}

// Current message state for streaming
let currentMessageEl = null;
let currentToolsEl = null;
let streamedText = '';
let isAgentRunning = false;
let rawStreamedText = '';

function handleWebSocketMessage(event) {
    const data = JSON.parse(event.data);

    switch (data.type) {
        case 'session_created':
            sessionId = data.session_id;
            localStorage.setItem('sessionId', sessionId);
            console.log('New session created:', sessionId);
            if (!isReplay) loadSessionsList();
            break;

        case 'canvas_ready':
            console.log('Canvas ready for session:', data.session_id);
            // Reload iframe if excalidraw panel is visible
            _reloadExcalidrawIframe();
            break;

        case 'start':
            currentMessageEl = createMessageContainer('assistant');
            currentToolsEl = null;
            streamedText = '';
            rawStreamedText = '';
            excalidrawCanvasShown = false;
            resetTasksPanel();
            setAgentRunning(true);
            // Show typing indicator
            if (!isReplay && currentMessageEl) {
                const contentEl = currentMessageEl.querySelector('.message-content');
                if (contentEl) {
                    contentEl.innerHTML = '<span class="typing-indicator"><span class="dot"></span><span class="dot"></span><span class="dot"></span></span>';
                }
            }
            break;

        case 'status':
            updateStatus(data.content);
            break;

        case 'tool_call_start':
            startToolCallStreaming(data.tool_name, data.tool_call_id);
            break;

        case 'tool_args_delta':
            appendToolArgsDelta(data.tool_name, data.args_delta);
            break;

        case 'tool_start':
            addToolEvent(data.tool_name, data.args);
            break;

        case 'tool_output':
            updateToolOutput(data.tool_name, data.output);
            break;

        case 'text_delta':
            appendTextChunk(data.content);
            break;

        case 'thinking_delta':
            appendThinkingChunk(data.content);
            break;

        case 'response':
            if (currentMessageEl) {
                const contentEl = currentMessageEl.querySelector('.message-content');
                if (contentEl) {
                    contentEl.innerHTML = formatMessage(data.content);
                }
            }
            break;

        case 'todos_update':
            handleTodosUpdate(data.todos);
            break;

        case 'cancelled':
            if (currentMessageEl) {
                const contentEl = currentMessageEl.querySelector('.message-content');
                if (contentEl && !contentEl.textContent.trim()) {
                    contentEl.innerHTML = '<span class="cancelled-label"><i class="ri-stop-circle-line"></i> Stopped</span>';
                }
                // Remove any pending ask-user or approval dialogs
                currentMessageEl.querySelectorAll('.ask-user-container, .approval-dialog').forEach(el => el.remove());
            }
            break;

        case 'done':
            finishMessage();
            refreshFiles();
            if (!isReplay) loadSessionsList();
            break;

        case 'error':
            showError(data.content);
            break;

        case 'approval_required':
            showApprovalDialog(data.requests);
            break;

        case 'middleware_event':
            handleMiddlewareEvent(data);
            break;

        case 'hook_event':
            handleHookEvent(data);
            break;

        case 'ask_user_question':
            handleAskUserQuestion(data);
            break;

        case 'checkpoint_saved':
            handleCheckpointSaved(data);
            break;

        case 'checkpoint_rewind':
            handleCheckpointRewind(data);
            break;

        case 'background_task_completed':
            showBackgroundTaskToast(data);
            break;

        case 'report_updated':
            handleReportUpdated(data);
            break;
    }
}

function createMessageContainer(type) {
    const id = 'msg-' + Date.now();
    const messageEl = document.createElement('div');
    messageEl.className = `message ${type}`;
    messageEl.id = id;

    const labelMap = {
        'user': {text: 'You', icon: 'icon-user', i: 'ri-user-smile-line'},
        'assistant': {text: 'DeepResearch', icon: 'icon-ai', i: 'ri-search-eye-line'},
        'system': {text: 'System', icon: 'icon-system', i: 'ri-error-warning-fill'}
    };

    const info = labelMap[type] || labelMap['system'];

    const showHeaderCopy = (type === 'user');
    messageEl.innerHTML = `
        <div class="message-header ${info.icon}">
            <i class="${info.i}"></i> <span>${info.text}</span>
            ${showHeaderCopy ? '<button class="msg-copy-btn" onclick="copyMessage(this)" title="Copy"><i class="ri-file-copy-line"></i></button>' : ''}
        </div>
        <div class="message-tools"></div>
        <div class="message-content"></div>
        ${type === 'assistant' ? '<div class="message-actions"></div>' : ''}
    `;

    if (isReplay) messageEl.style.animation = 'none';
    messagesContainer.appendChild(messageEl);
    if (!isReplay) forceScroll();
    if (!isReplay) updateOutlinePanel();

    return messageEl;
}

function copyMessage(btn) {
    const messageEl = btn.closest('.message');
    if (!messageEl) return;
    const contentEl = messageEl.querySelector('.message-content');
    if (!contentEl) return;
    const text = contentEl.innerText || contentEl.textContent;
    _copyWithFeedback(btn, text);
}

function copyToolOutput(btn) {
    const pre = btn.closest('.tool-output-wrap')?.querySelector('pre');
    if (!pre) return;
    _copyWithFeedback(btn, pre.textContent);
}

function _copyWithFeedback(btn, text) {
    navigator.clipboard.writeText(text).then(() => {
        const orig = btn.innerHTML;
        btn.innerHTML = '<i class="ri-check-line"></i>';
        btn.classList.add('copied');
        setTimeout(() => {
            btn.innerHTML = orig;
            btn.classList.remove('copied');
        }, 1500);
    });
}

function updateStatus(status) {
    if (!currentMessageEl) return;

    let statusEl = currentMessageEl.querySelector('.message-status-line');
    if (!statusEl) {
        statusEl = document.createElement('div');
        statusEl.className = 'message-status-line';
        statusEl.style.cssText = "font-size: 11px; color: #666; font-family: monospace; margin-top: 4px; padding-left: 1rem;";
        currentMessageEl.appendChild(statusEl);
    }
    statusEl.innerHTML = `<i class="ri-loader-4-line"></i> ${escapeHtml(status)}`;
}

// Streaming tool args accumulator
let streamingToolArgs = '';

function startToolCallStreaming(toolName, toolCallId) {
    if (!currentMessageEl) return;

    const toolsEl = currentMessageEl.querySelector('.message-tools');
    if (!toolsEl) return;

    streamingToolArgs = '';

    // Hidden tools: skip rendering (shown in dedicated UI components)
    if (HIDDEN_TOOLS.has(toolName)) {
        currentToolsEl = null;
        return;
    }

    // Excalidraw tools: show live canvas + compact card (no streaming args)
    if (_isExcalidrawCall(toolName)) {
        showExcalidrawCanvas();
        const toolEl = document.createElement('div');
        toolEl.className = 'tool-call excalidraw-compact';
        toolEl.dataset.toolCallId = toolCallId || '';
        toolEl.innerHTML = _renderExcalidrawCard(toolName, 'running');
        toolsEl.appendChild(toolEl);
        currentToolsEl = toolEl;
        autoScroll();
        return;
    }

    // Search tools: compact colored card (args arrive later via addToolEvent)
    if (_isSearchCall(toolName)) {
        const toolEl = document.createElement('div');
        toolEl.className = 'tool-call search-tool-card';
        toolEl.dataset.toolCallId = toolCallId || '';
        toolEl.dataset.toolName = toolName;
        toolEl.innerHTML = _renderSearchCard(toolName, null, 'running');
        toolsEl.appendChild(toolEl);
        currentToolsEl = toolEl;
        autoScroll();
        return;
    }

    const collapsed = _isCollapsibleTool(toolName);
    const iconClass = _getToolIcon(toolName);
    const catColor = _getToolCategoryColor(toolName);
    const toolEl = document.createElement('div');
    toolEl.className = 'tool-call streaming' + (collapsed ? ' collapsible collapsed' : '');
    toolEl.dataset.toolCallId = toolCallId || '';
    toolEl.dataset.toolName = toolName;

    toolEl.innerHTML = `
        <div class="tool-header"${collapsed ? ' onclick="this.parentElement.classList.toggle(\'collapsed\')" style="cursor:pointer"' : ''}>
            <span class="tool-icon-badge" style="background:${catColor}22;color:${catColor}"><i class="${iconClass}"></i></span>
            <span class="tool-name" style="color:${catColor}">${escapeHtml(toolName)}</span>
            <span class="tool-status streaming">STREAMING</span>
            ${collapsed ? '<i class="ri-arrow-down-s-line collapse-chevron"></i>' : ''}
        </div>
        <div class="tool-args streaming-args"><code></code></div>
        <div class="tool-output"></div>
    `;

    // Group consecutive collapsible tools of the same type
    if (collapsed) {
        const lastChild = toolsEl.lastElementChild;
        if (lastChild) {
            const isSameGroup = lastChild.classList.contains('tool-group') && lastChild.dataset.toolName === toolName;
            const isSameTool = lastChild.classList.contains('tool-call') && lastChild.dataset.toolName === toolName && _isCollapsibleTool(toolName);

            if (isSameGroup) {
                // Add to existing group
                const itemsEl = lastChild.querySelector('.tool-group-items');
                itemsEl.appendChild(toolEl);
                const countEl = lastChild.querySelector('.tool-group-count');
                countEl.textContent = `×${itemsEl.children.length}`;
                currentToolsEl = toolEl;
                autoScroll();
                return;
            } else if (isSameTool) {
                // Wrap previous single tool + this one into a new group
                const groupEl = document.createElement('div');
                groupEl.className = 'tool-group collapsed';
                groupEl.dataset.toolName = toolName;
                groupEl.innerHTML = `
                    <div class="tool-group-header" onclick="this.parentElement.classList.toggle('collapsed')">
                        <span class="tool-icon-badge" style="background:${catColor}22;color:${catColor}"><i class="${iconClass}"></i></span>
                        <span class="tool-name" style="color:${catColor}">${escapeHtml(toolName)}</span>
                        <span class="tool-group-count">×2</span>
                        <i class="ri-arrow-down-s-line collapse-chevron"></i>
                    </div>
                    <div class="tool-group-items"></div>
                `;
                const itemsEl = groupEl.querySelector('.tool-group-items');
                toolsEl.replaceChild(groupEl, lastChild);
                itemsEl.appendChild(lastChild);
                itemsEl.appendChild(toolEl);
                currentToolsEl = toolEl;
                autoScroll();
                return;
            }
        }
    }

    toolsEl.appendChild(toolEl);
    currentToolsEl = toolEl;
    autoScroll();
}

function appendToolArgsDelta(toolName, argsDelta) {
    if (!currentToolsEl) return;

    streamingToolArgs += argsDelta;

    const argsEl = currentToolsEl.querySelector('.tool-args code');
    if (argsEl) {
        argsEl.textContent = streamingToolArgs;
        autoScroll();
    }
}

// ---------------------------------------------------------------------------
// Subagent & Agent Factory Detection
// ---------------------------------------------------------------------------

function _isExcalidrawCall(toolName) {
    return toolName && toolName.startsWith('excalidraw_');
}

// ---------------------------------------------------------------------------
// Web Search Tool Detection & Labels
// ---------------------------------------------------------------------------

// Prefix-based detection — tool_prefix doubles the name (tavily_tavily_search, brave_brave_web_search, etc.)
const SEARCH_PROVIDERS = [
    { prefix: 'tavily_',     label: 'Tavily',     icon: 'ri-sparkling-2-fill',  color: '#0ea5e9' },
    { prefix: 'brave_',      label: 'Brave',      icon: 'ri-shield-flash-line', color: '#f97316' },
    { prefix: 'jina_',       label: 'Jina',       icon: 'ri-links-line',        color: '#8b5cf6' },
    { prefix: 'firecrawl_',  label: 'Firecrawl',  icon: 'ri-fire-line',         color: '#ef4444' },
    { prefix: 'playwright_', label: 'Playwright', icon: 'ri-chrome-line',       color: '#2dd4bf' },
];

function _getSearchProvider(toolName) {
    if (!toolName) return null;
    for (const p of SEARCH_PROVIDERS) {
        if (toolName.startsWith(p.prefix)) return p;
    }
    return null;
}

function _isSearchCall(toolName) {
    return _getSearchProvider(toolName) !== null;
}

function _searchLabel(toolName) {
    const p = _getSearchProvider(toolName);
    if (!p) return toolName;
    // Strip prefix and prettify: "tavily_tavily_search" → "Search", "jina_jina_read_url" → "Read URL"
    let action = toolName.slice(p.prefix.length);
    // Strip doubled provider name (tavily_search → search, brave_web_search → web_search)
    if (action.startsWith(p.label.toLowerCase() + '_')) {
        action = action.slice(p.label.length + 1);
    }
    return p.label + ' ' + action.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function _extractSearchQuery(toolName, args) {
    const parsed = typeof args === 'string' ? (() => { try { return JSON.parse(args); } catch { return null; } })() : args;
    if (!parsed || typeof parsed !== 'object') return '';
    // Tavily: query field; Jina readurl: url field; Jina search: query; Brave: query
    return parsed.query || parsed.url || parsed.search_query || '';
}

function _renderSearchCard(toolName, args, status) {
    const provider = _getSearchProvider(toolName) || { label: 'Search', icon: 'ri-search-line', color: 'var(--accent-primary)' };
    const info = { label: _searchLabel(toolName), icon: provider.icon, color: provider.color };
    const query = _extractSearchQuery(toolName, args);
    const isRunning = status === 'running';
    const statusHtml = isRunning
        ? '<span class="search-status running"><i class="ri-loader-4-line"></i> Searching...</span>'
        : '<span class="search-status done"></span>';
    return `
        <div class="search-card-header" style="--search-color: ${info.color}" onclick="this.parentElement.classList.toggle('expanded')">
            <span class="search-provider"><i class="${info.icon}"></i> ${escapeHtml(info.label)}</span>
            ${query ? `<span class="search-query">"${escapeHtml(query.length > 80 ? query.substring(0, 80) + '…' : query)}"</span>` : ''}
            ${statusHtml}
            <i class="ri-arrow-down-s-line search-expand-icon"></i>
        </div>
        <div class="tool-output"></div>
    `;
}

// Tools that should be auto-collapsed (utility/background tools)
const COLLAPSED_TOOLS = new Set(['load_skill', 'list_skills', 'read_file', 'glob', 'grep', 'remember']);

// Tools completely hidden from chat (shown in dedicated UI components instead)
const HIDDEN_TOOLS = new Set(['read_todos', 'write_todos', 'add_todo', 'update_todo_status', 'remove_todo', 'wait_tasks']);

// Per-tool icons and category colors
const TOOL_ICONS = {
    'read_file': 'ri-file-text-line', 'write_file': 'ri-file-edit-line',
    'edit_file': 'ri-edit-line', 'execute': 'ri-terminal-line',
    'glob': 'ri-search-line', 'grep': 'ri-search-2-line',
    'ls': 'ri-folder-open-line', 'read_todos': 'ri-checkbox-circle-line',
    'write_todos': 'ri-checkbox-circle-line', 'list_skills': 'ri-book-open-line',
    'load_skill': 'ri-book-open-line', 'task': 'ri-robot-line',
    'check_task': 'ri-robot-line', 'list_active_tasks': 'ri-robot-line',
    'soft_cancel_task': 'ri-close-circle-line', 'hard_cancel_task': 'ri-close-circle-line',
    'create_agent': 'ri-user-add-line', 'remove_agent': 'ri-user-minus-line',
    'list_agents': 'ri-team-line', 'get_agent_info': 'ri-user-search-line',
    'list_checkpoints': 'ri-history-line', 'rewind': 'ri-arrow-go-back-line',
    'fork': 'ri-git-branch-line',
    'spawn_team': 'ri-team-line', 'assign_task': 'ri-user-follow-line',
    'check_teammates': 'ri-group-line', 'dissolve_team': 'ri-user-unfollow-line',
    'remember': 'ri-brain-line',
    'add_todo': 'ri-add-circle-line', 'update_todo_status': 'ri-checkbox-circle-line',
    'remove_todo': 'ri-delete-bin-line',
    'save_checkpoint': 'ri-save-line', 'rewind_to': 'ri-arrow-go-back-line',
    'ask_user': 'ri-question-line', 'save_plan': 'ri-draft-line',
    'answer_subagent': 'ri-chat-3-line',
};
const TOOL_CATEGORIES = {
    'file': { color: '#3b82f6', tools: ['read_file', 'write_file', 'edit_file', 'glob', 'grep', 'ls'] },
    'execute': { color: '#f59e0b', tools: ['execute'] },
    'planning': { color: '#8b5cf6', tools: ['read_todos', 'write_todos', 'add_todo', 'update_todo_status', 'remove_todo', 'list_skills', 'load_skill', 'ask_user', 'save_plan'] },
    'agents': { color: '#06b6d4', tools: ['task', 'check_task', 'list_active_tasks', 'soft_cancel_task', 'hard_cancel_task', 'create_agent', 'remove_agent', 'list_agents', 'get_agent_info', 'answer_subagent'] },
    'teams': { color: '#a855f7', tools: ['spawn_team', 'assign_task', 'check_teammates', 'dissolve_team'] },
    'memory': { color: '#f472b6', tools: ['remember'] },
    'system': { color: '#6b7280', tools: ['list_checkpoints', 'save_checkpoint', 'rewind_to', 'rewind', 'fork'] },
};

function _getToolIcon(toolName) {
    return TOOL_ICONS[toolName] || 'ri-settings-5-line';
}

function _getToolCategoryColor(toolName) {
    for (const cat of Object.values(TOOL_CATEGORIES)) {
        if (cat.tools.includes(toolName)) return cat.color;
    }
    return '#6b7280';
}

function _isCollapsibleTool(toolName) {
    return COLLAPSED_TOOLS.has(toolName);
}

// Friendly Excalidraw tool labels (yctimlin/mcp_excalidraw tools)
const EXCALIDRAW_LABELS = {
    'excalidraw_create_element': 'Create Element',
    'excalidraw_batch_create_elements': 'Create Elements',
    'excalidraw_update_element': 'Update Element',
    'excalidraw_delete_element': 'Delete Element',
    'excalidraw_create_from_mermaid': 'From Mermaid',
    'excalidraw_describe_scene': 'Inspect Scene',
    'excalidraw_get_canvas_screenshot': 'Screenshot',
    'excalidraw_align_elements': 'Align',
    'excalidraw_distribute_elements': 'Distribute',
    'excalidraw_group_elements': 'Group',
    'excalidraw_ungroup_elements': 'Ungroup',
    'excalidraw_export_scene': 'Export Scene',
    'excalidraw_export_to_excalidraw_url': 'Share Link',
    'excalidraw_export_to_image': 'Export Image',
    'excalidraw_import_scene': 'Import Scene',
    'excalidraw_clear_canvas': 'Clear Canvas',
    'excalidraw_read_diagram_guide': 'Read Guide',
    'excalidraw_set_viewport': 'Set Viewport',
    'excalidraw_query_elements': 'Query Elements',
    'excalidraw_get_element': 'Get Element',
    'excalidraw_get_resource': 'Get Resource',
    'excalidraw_lock_elements': 'Lock',
    'excalidraw_unlock_elements': 'Unlock',
    'excalidraw_snapshot_scene': 'Snapshot',
    'excalidraw_restore_snapshot': 'Restore',
    'excalidraw_duplicate_elements': 'Duplicate',
};

function _isSubagentCall(toolName, args) {
    if (toolName !== 'task' && toolName !== 'delegate_task') return null;
    const parsed = typeof args === 'string' ? (() => { try { return JSON.parse(args); } catch { return args; } })() : args;
    if (parsed && typeof parsed === 'object' && parsed.subagent_type) return parsed;
    return null;
}

function _isAgentFactoryCall(toolName, args) {
    if (toolName !== 'create_agent' && toolName !== 'remove_agent' &&
        toolName !== 'list_agents' && toolName !== 'get_agent_info') return null;
    const parsed = typeof args === 'string' ? (() => { try { return JSON.parse(args); } catch { return args; } })() : args;
    return { tool: toolName, args: parsed || {} };
}

const AGENT_ICONS = {
    'joke-generator': 'ri-emotion-laugh-line',
    'code-reviewer': 'ri-code-s-slash-line',
    'general-purpose': 'ri-robot-2-line',
    'planner': 'ri-draft-line',
};
const AGENT_COLORS = {
    'joke-generator': '#f59e0b',
    'code-reviewer': '#8b5cf6',
    'general-purpose': '#06b6d4',
    'planner': '#3b82f6',
};

function _renderSubagentCard(agentInfo, status) {
    const name = agentInfo.subagent_type || 'subagent';
    const icon = AGENT_ICONS[name] || 'ri-user-shared-line';
    const color = AGENT_COLORS[name] || 'var(--accent-primary)';
    const desc = agentInfo.description || '';
    const statusHtml = status === 'running'
        ? '<span class="subagent-status running"><i class="ri-loader-4-line"></i> Working...</span>'
        : '<span class="subagent-status done"></span>';

    return `
        <div class="subagent-header" style="--agent-color: ${color}">
            <div class="subagent-avatar"><i class="${icon}"></i></div>
            <div class="subagent-info">
                <span class="subagent-name">${escapeHtml(name)}</span>
                ${statusHtml}
            </div>
        </div>
        ${desc ? `<div class="subagent-task"><i class="ri-arrow-right-s-line"></i> ${escapeHtml(desc)}</div>` : ''}
        <div class="tool-output"></div>
    `;
}

function _renderFactoryCard(factoryInfo, status) {
    const toolIcons = {
        'create_agent': 'ri-add-circle-line',
        'remove_agent': 'ri-delete-bin-line',
        'list_agents':  'ri-list-check',
        'get_agent_info': 'ri-information-line',
    };
    const toolLabels = {
        'create_agent': 'Creating Agent',
        'remove_agent': 'Removing Agent',
        'list_agents':  'Listing Agents',
        'get_agent_info': 'Agent Info',
    };
    const tool = factoryInfo.tool;
    const args = factoryInfo.args || {};
    const icon = toolIcons[tool] || 'ri-robot-2-line';
    const label = toolLabels[tool] || tool;
    const agentName = args.name || '';
    const desc = args.description || '';
    const statusHtml = status === 'running'
        ? '<span class="subagent-status running"><i class="ri-loader-4-line"></i> Working...</span>'
        : '<span class="subagent-status done"></span>';

    return `
        <div class="subagent-header" style="--agent-color: #10b981">
            <div class="subagent-avatar"><i class="${icon}"></i></div>
            <div class="subagent-info">
                <span class="subagent-name">${escapeHtml(label)}${agentName ? ': ' + escapeHtml(agentName) : ''}</span>
                ${statusHtml}
            </div>
        </div>
        ${desc ? `<div class="subagent-task"><i class="ri-arrow-right-s-line"></i> ${escapeHtml(desc)}</div>` : ''}
        <div class="tool-output"></div>
    `;
}

// ---------------------------------------------------------------------------
// Team Agent Cards
// ---------------------------------------------------------------------------

const TEAM_TOOLS = new Set(['spawn_team', 'assign_task', 'check_teammates', 'dissolve_team']);

function _isTeamCall(toolName) {
    return TEAM_TOOLS.has(toolName);
}

const MEMBER_COLORS = ['#a855f7', '#ec4899', '#06b6d4', '#f59e0b', '#10b981', '#3b82f6'];

function _renderTeamCard(toolName, args, status) {
    const parsed = typeof args === 'string' ? (() => { try { return JSON.parse(args); } catch { return args; } })() : (args || {});
    const statusHtml = status === 'running'
        ? '<span class="subagent-status running"><i class="ri-loader-4-line"></i> Working...</span>'
        : '<span class="subagent-status done"></span>';

    if (toolName === 'spawn_team') {
        const teamName = parsed.team_name || 'team';
        const members = parsed.members || [];
        const membersHtml = members.map((m, i) => {
            const c = MEMBER_COLORS[i % MEMBER_COLORS.length];
            const name = typeof m === 'string' ? m : (m.name || 'Member');
            const role = typeof m === 'object' ? (m.role || '') : '';
            return `<div class="team-member" style="--member-color: ${c}">
                <div class="team-member-avatar" style="background:${c}22;color:${c}"><i class="ri-user-3-line"></i></div>
                <div class="team-member-info">
                    <span class="team-member-name">${escapeHtml(name)}</span>
                    ${role ? `<span class="team-member-role">${escapeHtml(role)}</span>` : ''}
                </div>
            </div>`;
        }).join('');

        return `
            <div class="subagent-header" style="--agent-color: #a855f7">
                <div class="subagent-avatar" style="background:rgba(168,85,247,0.15);color:#a855f7"><i class="ri-team-line"></i></div>
                <div class="subagent-info">
                    <span class="subagent-name">Spawning Team: ${escapeHtml(teamName)}</span>
                    ${statusHtml}
                </div>
            </div>
            ${members.length ? `<div class="team-members">${membersHtml}</div>` : ''}
            <div class="tool-output"></div>
        `;
    }

    if (toolName === 'assign_task') {
        const memberName = parsed.member_name || 'member';
        const taskDesc = parsed.task_description || '';
        return `
            <div class="subagent-header" style="--agent-color: #a855f7">
                <div class="subagent-avatar" style="background:rgba(168,85,247,0.15);color:#a855f7"><i class="ri-user-follow-line"></i></div>
                <div class="subagent-info">
                    <span class="subagent-name">${escapeHtml(memberName)}</span>
                    ${statusHtml}
                </div>
            </div>
            ${taskDesc ? `<div class="subagent-task"><i class="ri-arrow-right-s-line"></i> ${escapeHtml(taskDesc.length > 200 ? taskDesc.substring(0, 200) + '…' : taskDesc)}</div>` : ''}
            <div class="tool-output"></div>
        `;
    }

    if (toolName === 'check_teammates') {
        return `
            <div class="subagent-header" style="--agent-color: #a855f7">
                <div class="subagent-avatar" style="background:rgba(168,85,247,0.15);color:#a855f7"><i class="ri-group-line"></i></div>
                <div class="subagent-info">
                    <span class="subagent-name">Checking Teammates</span>
                    ${statusHtml}
                </div>
            </div>
            <div class="tool-output"></div>
        `;
    }

    if (toolName === 'dissolve_team') {
        return `
            <div class="subagent-header" style="--agent-color: #a855f7">
                <div class="subagent-avatar" style="background:rgba(168,85,247,0.15);color:#a855f7"><i class="ri-user-unfollow-line"></i></div>
                <div class="subagent-info">
                    <span class="subagent-name">Dissolving Team</span>
                    ${statusHtml}
                </div>
            </div>
            <div class="tool-output"></div>
        `;
    }

    // Fallback
    return `
        <div class="subagent-header" style="--agent-color: #a855f7">
            <div class="subagent-avatar" style="background:rgba(168,85,247,0.15);color:#a855f7"><i class="ri-team-line"></i></div>
            <div class="subagent-info">
                <span class="subagent-name">${escapeHtml(toolName)}</span>
                ${statusHtml}
            </div>
        </div>
        <div class="tool-output"></div>
    `;
}

// ---------------------------------------------------------------------------
// Excalidraw Live Canvas
// ---------------------------------------------------------------------------

function _renderExcalidrawCard(toolName, status) {
    const label = EXCALIDRAW_LABELS[toolName] || toolName.replace('excalidraw_', '');
    const statusHtml = status === 'running'
        ? '<span class="tool-status running"><i class="ri-loader-4-line"></i></span>'
        : '<span class="tool-status done"></span>';
    return `
        <div class="tool-header excalidraw-tool">
            <span class="tool-name"><i class="ri-artboard-line"></i> ${escapeHtml(label)}</span>
            ${statusHtml}
        </div>
        <div class="tool-output"></div>
    `;
}

function showExcalidrawCanvas() {
    excalidrawCanvasShown = true;
    if (!excalidrawCanvasUrl) return;

    // Reuse existing canvas element if present
    let canvas = document.getElementById('excalidraw-inline');
    if (!canvas) {
        canvas = document.createElement('div');
        canvas.id = 'excalidraw-inline';
        canvas.className = 'excalidraw-inline';
        canvas.innerHTML = `
            <div class="excalidraw-inline-header" onclick="toggleExcalidrawInline()">
                <span class="excalidraw-inline-title"><i class="ri-artboard-line"></i> Canvas</span>
                <button class="excalidraw-inline-toggle"><i class="ri-arrow-up-s-line"></i></button>
            </div>
            <iframe id="excalidraw-iframe" class="excalidraw-inline-iframe" src="about:blank"></iframe>
        `;
        // Place inside the current message, after .message-content (part of the response)
        if (currentMessageEl) {
            const content = currentMessageEl.querySelector('.message-content');
            if (content) {
                content.after(canvas);
            } else {
                currentMessageEl.appendChild(canvas);
            }
        } else {
            messagesContainer.appendChild(canvas);
        }
    }

    const iframe = document.getElementById('excalidraw-iframe');
    if (iframe && (!iframe.src || iframe.src === 'about:blank' || iframe.src === window.location.href)) {
        iframe.src = excalidrawCanvasUrl;
    }

    canvas.classList.remove('collapsed');
    autoScroll();
}

function _reloadExcalidrawIframe() {
    const iframe = document.getElementById('excalidraw-iframe');
    if (!iframe || !excalidrawCanvasUrl) return;
    iframe.src = 'about:blank';
    const canvas = document.getElementById('excalidraw-inline');
    if (canvas && !canvas.classList.contains('collapsed')) {
        setTimeout(() => { iframe.src = excalidrawCanvasUrl; }, 100);
    }
}

function closeExcalidrawPanel() {
    const canvas = document.getElementById('excalidraw-inline');
    if (canvas) canvas.classList.add('collapsed');
}

function _hideExcalidrawContainer() {
    const canvas = document.getElementById('excalidraw-inline');
    if (canvas) canvas.remove();
    const iframe = document.getElementById('excalidraw-iframe');
    if (iframe) iframe.src = 'about:blank';
}

function toggleExcalidrawInline() {
    const canvas = document.getElementById('excalidraw-inline');
    if (!canvas) return;
    canvas.classList.toggle('collapsed');
}

function toggleExcalidrawPanel() {
    const canvas = document.getElementById('excalidraw-inline');
    if (!canvas) {
        showExcalidrawCanvas();
    } else {
        toggleExcalidrawInline();
    }
}

// ---------------------------------------------------------------------------
// Tool Events (with subagent/factory card rendering)
// ---------------------------------------------------------------------------

function addToolEvent(toolName, args) {
    if (!currentMessageEl) return;

    const toolsEl = currentMessageEl.querySelector('.message-tools');
    if (!toolsEl) return;

    // Hidden tools: skip rendering (shown in dedicated UI components)
    if (HIDDEN_TOOLS.has(toolName)) {
        currentToolsEl = null;
        return;
    }

    // Excalidraw tools: compact card + show inline canvas
    if (_isExcalidrawCall(toolName)) {
        showExcalidrawCanvas();

        // Update existing compact card if streaming, or create new one
        const existingCompact = toolsEl.querySelector('.tool-call.excalidraw-compact');
        if (existingCompact && existingCompact === currentToolsEl) {
            existingCompact.innerHTML = _renderExcalidrawCard(toolName, 'running');
            return;
        }

        const toolEl = document.createElement('div');
        toolEl.className = 'tool-call excalidraw-compact';
        toolEl.innerHTML = _renderExcalidrawCard(toolName, 'running');
        toolsEl.appendChild(toolEl);
        currentToolsEl = toolEl;
        autoScroll();
        return;
    }

    // Search tools: compact colored card with query
    if (_isSearchCall(toolName)) {
        // Update existing streaming search card, or create new one
        const existingSearch = currentToolsEl && currentToolsEl.classList.contains('search-tool-card') ? currentToolsEl : null;
        if (existingSearch) {
            existingSearch.innerHTML = _renderSearchCard(toolName, args, 'running');
            return;
        }
        const toolEl = document.createElement('div');
        toolEl.className = 'tool-call search-tool-card';
        toolEl.dataset.toolName = toolName;
        toolEl.innerHTML = _renderSearchCard(toolName, args, 'running');
        toolsEl.appendChild(toolEl);
        currentToolsEl = toolEl;
        autoScroll();
        return;
    }

    // Detect team tools, subagent delegation, or agent factory call
    const isTeam = _isTeamCall(toolName);
    const agentInfo = !isTeam ? _isSubagentCall(toolName, args) : null;
    const factoryInfo = !isTeam && !agentInfo ? _isAgentFactoryCall(toolName, args) : null;

    const existingStreamingTool = toolsEl.querySelector('.tool-call.streaming');
    if (existingStreamingTool) {
        existingStreamingTool.classList.remove('streaming');

        if (isTeam) {
            existingStreamingTool.className = 'tool-call team-card';
            existingStreamingTool.innerHTML = _renderTeamCard(toolName, args, 'running');
        } else if (agentInfo) {
            existingStreamingTool.className = 'tool-call subagent-delegation';
            existingStreamingTool.innerHTML = _renderSubagentCard(agentInfo, 'running');
        } else if (factoryInfo) {
            existingStreamingTool.className = 'tool-call subagent-delegation';
            existingStreamingTool.innerHTML = _renderFactoryCard(factoryInfo, 'running');
        } else {
            const statusEl = existingStreamingTool.querySelector('.tool-status');
            if (statusEl) {
                statusEl.className = 'tool-status running';
                statusEl.textContent = 'running';
            }
            const argsEl = existingStreamingTool.querySelector('.tool-args');
            if (argsEl) {
                argsEl.className = 'tool-args';
                argsEl.innerHTML = formatToolArgs(args);
            }
        }
        currentToolsEl = existingStreamingTool;
        return;
    }

    const toolEl = document.createElement('div');

    if (isTeam) {
        toolEl.className = 'tool-call team-card';
        toolEl.innerHTML = _renderTeamCard(toolName, args, 'running');
    } else if (agentInfo) {
        toolEl.className = 'tool-call subagent-delegation';
        toolEl.innerHTML = _renderSubagentCard(agentInfo, 'running');
    } else if (factoryInfo) {
        toolEl.className = 'tool-call subagent-delegation';
        toolEl.innerHTML = _renderFactoryCard(factoryInfo, 'running');
    } else {
        const collapsed = _isCollapsibleTool(toolName);
        const iconClass = _getToolIcon(toolName);
        const catColor = _getToolCategoryColor(toolName);
        toolEl.className = 'tool-call running' + (collapsed ? ' collapsible collapsed' : '');
        toolEl.innerHTML = `
            <div class="tool-header"${collapsed ? ' onclick="this.parentElement.classList.toggle(\'collapsed\')" style="cursor:pointer"' : ''}>
                <span class="tool-icon-badge" style="background:${catColor}22;color:${catColor}"><i class="${iconClass}"></i></span>
                <span class="tool-name" style="color:${catColor}">${escapeHtml(toolName)}</span>
                <span class="tool-status running">RUNNING...</span>
                ${collapsed ? '<i class="ri-arrow-down-s-line collapse-chevron"></i>' : ''}
            </div>
            <div class="tool-args">${formatToolArgs(args)}</div>
            <div class="tool-output"></div>
        `;
    }

    toolsEl.appendChild(toolEl);
    currentToolsEl = toolEl;
    autoScroll();
}

function formatToolArgs(args) {
    if (typeof args === 'string') {
        try {
            args = JSON.parse(args);
        } catch {
            return `<code>${escapeHtml(args)}</code>`;
        }
    }

    if (typeof args === 'object') {
        const parts = [];
        for (const [key, value] of Object.entries(args)) {
            const displayValue = typeof value === 'string' && value.length > 100
                ? value.substring(0, 100) + '...'
                : JSON.stringify(value);
            parts.push(`<span class="arg-key">${escapeHtml(key)}:</span> <span class="arg-value">${escapeHtml(displayValue)}</span>`);
        }
        return parts.join('<br>');
    }

    return '';
}

function updateToolOutput(toolName, output) {
    if (!currentToolsEl) return;

    const isTeam = currentToolsEl.classList.contains('team-card');
    const isSubagent = currentToolsEl.classList.contains('subagent-delegation');
    const isExcalidraw = currentToolsEl.classList.contains('excalidraw-compact');
    const isSearch = currentToolsEl.classList.contains('search-tool-card');
    const outputEl = currentToolsEl.querySelector('.tool-output');

    if (isTeam) {
        const statusEl = currentToolsEl.querySelector('.subagent-status');
        if (statusEl) {
            statusEl.className = 'subagent-status done';
            statusEl.innerHTML = '';
        }
        if (outputEl && output) {
            outputEl.innerHTML = `<div class="subagent-result">${formatMessage(output)}</div>`;
        }
    } else if (isSearch) {
        // Update status to done
        const statusEl = currentToolsEl.querySelector('.search-status');
        if (statusEl) {
            statusEl.className = 'search-status done';
            statusEl.innerHTML = '';
        }
        // Show output collapsed — user clicks header to expand
        if (outputEl && output) {
            const preview = output.length > 300 ? output.substring(0, 300) + '…' : output;
            outputEl.innerHTML = `<div class="search-results-wrap"><pre>${escapeHtml(preview)}</pre>${output.length > 300 ? `<button class="search-show-more" onclick="this.parentElement.querySelector('pre').textContent = this.parentElement.dataset.full; this.remove();">Show full results</button>` : ''}</div>`;
            if (output.length > 300) {
                outputEl.querySelector('.search-results-wrap').dataset.full = output;
            }
        }
    } else if (isExcalidraw) {
        // Update status — diagram renders live in the inline canvas
        const statusEl = currentToolsEl.querySelector('.tool-status');
        if (statusEl) {
            statusEl.className = 'tool-status done';
            statusEl.innerHTML = '';
        }
    } else if (isSubagent) {
        const statusEl = currentToolsEl.querySelector('.subagent-status');
        if (statusEl) {
            statusEl.className = 'subagent-status done';
            statusEl.innerHTML = '';
        }
        if (outputEl) {
            outputEl.innerHTML = `<div class="subagent-result">${formatMessage(output)}</div>`;
        }
    } else {
        if (outputEl) {
            outputEl.innerHTML = `<div class="tool-output-wrap"><pre>${escapeHtml(output)}</pre><button class="tool-copy-btn" onclick="copyToolOutput(this)" title="Copy output"><i class="ri-file-copy-line"></i></button></div>`;
        }
        const statusEl = currentToolsEl.querySelector('.tool-status');
        if (statusEl) {
            statusEl.className = 'tool-status done';
            statusEl.innerHTML = '';
        }
        // Remove running class (stops shimmer animation)
        currentToolsEl.classList.remove('running');
    }

    // Refresh file list when file-modifying tools complete
    const fileTools = ['write_file', 'edit_file', 'execute'];
    if (fileTools.includes(toolName)) {
        refreshFiles();
    }

    // Track background agent tasks (assign_task and async task dispatch)
    if ((toolName === 'assign_task' || toolName === 'task') && output) {
        // Match both "Task assigned to 'X' (ID: abc123)" and "Task ID: abc123"
        const idMatch = output.match(/\(ID:\s*([a-f0-9-]+)\)/) || output.match(/Task ID:\s*([a-f0-9-]+)/);
        if (idMatch) {
            backgroundAgentTasks.add(idMatch[1]);
            backgroundAgentCount = backgroundAgentTasks.size;
            updateBackgroundBadge();
        }
    }
}

function appendTextChunk(chunk) {
    if (!currentMessageEl) return;

    streamedText += chunk;
    rawStreamedText += chunk;

    const contentEl = currentMessageEl.querySelector('.message-content');
    if (contentEl) {
        // Remove typing indicator if present
        const typing = contentEl.querySelector('.typing-indicator');
        if (typing) typing.remove();

        contentEl.innerHTML = formatMessage(streamedText);
        // Add streaming cursor during live streaming
        if (!isReplay) {
            contentEl.classList.add('streaming-cursor');
        }
        autoScroll();
    }
}

function appendThinkingChunk(chunk) {
    if (!currentMessageEl) return;

    let thinkingEl = currentMessageEl.querySelector('.message-thinking');
    if (!thinkingEl) {
        thinkingEl = document.createElement('div');
        thinkingEl.className = 'message-thinking';
        thinkingEl.innerHTML = '<span class="thinking-label" onclick="this.parentElement.classList.toggle(\'collapsed\')"><i class="ri-brain-line"></i> Thinking <i class="ri-arrow-down-s-line" style="margin-left:auto;font-size:14px;"></i></span><div class="thinking-content"></div>';
        const contentEl = currentMessageEl.querySelector('.message-content');
        currentMessageEl.insertBefore(thinkingEl, contentEl);
    }

    const thinkingContent = thinkingEl.querySelector('.thinking-content');
    if (thinkingContent) {
        thinkingContent.textContent += chunk;
        autoScroll();
    }
}

function finishMessage() {
    if (currentMessageEl) {
        const statusEl = currentMessageEl.querySelector('.message-status');
        if (statusEl) statusEl.remove();

        const statusLine = currentMessageEl.querySelector('.message-status-line');
        if (statusLine) statusLine.remove();

        const toolStatuses = currentMessageEl.querySelectorAll('.tool-status.running');
        toolStatuses.forEach(el => {
            el.className = 'tool-status done';
            el.innerHTML = '<i class="ri-check-line"></i>';
        });

        // Clear running subagent/team statuses
        currentMessageEl.querySelectorAll('.subagent-status.running').forEach(el => {
            el.className = 'subagent-status done';
            el.innerHTML = '';
        });

        // Remove running class from tool cards
        currentMessageEl.querySelectorAll('.tool-call.running').forEach(el => el.classList.remove('running'));

        // Remove streaming cursor
        const contentEl = currentMessageEl.querySelector('.message-content');
        if (contentEl) contentEl.classList.remove('streaming-cursor');

        // Remove typing indicator
        const typing = currentMessageEl.querySelector('.typing-indicator');
        if (typing) typing.remove();

        // Ensure action bar has at least copy if no checkpoint added it
        const actionsEl = currentMessageEl.querySelector('.message-actions');
        if (actionsEl && !actionsEl.hasChildNodes()) {
            const copyBtn = document.createElement('button');
            copyBtn.className = 'msg-action-btn';
            copyBtn.title = 'Copy response';
            copyBtn.innerHTML = '<i class="ri-file-copy-line"></i> Copy';
            copyBtn.onclick = () => copyMessage(copyBtn);
            actionsEl.appendChild(copyBtn);
        }
    }

    currentMessageEl = null;
    currentToolsEl = null;
    setAgentRunning(false);
    updateOutlinePanel();
}

function _renderMessageActions(actionsEl, checkpointId, checkpointLabel) {
    actionsEl.innerHTML = '';

    const copyBtn = document.createElement('button');
    copyBtn.className = 'msg-action-btn';
    copyBtn.title = 'Copy response';
    copyBtn.innerHTML = '<i class="ri-file-copy-line"></i> Copy';
    copyBtn.onclick = () => copyMessage(copyBtn);

    const rewindBtn = document.createElement('button');
    rewindBtn.className = 'msg-action-btn';
    rewindBtn.title = 'Rewind to this point';
    rewindBtn.innerHTML = '<i class="ri-arrow-go-back-line"></i> Rewind';
    rewindBtn.onclick = () => rewindToCheckpoint(checkpointId, checkpointLabel);

    const forkBtn = document.createElement('button');
    forkBtn.className = 'msg-action-btn';
    forkBtn.title = 'Fork into new session';
    forkBtn.innerHTML = '<i class="ri-git-branch-line"></i> Fork';
    forkBtn.onclick = () => forkFromCheckpoint(checkpointId);

    actionsEl.append(copyBtn, rewindBtn, forkBtn);
}

function setAgentRunning(running) {
    isAgentRunning = running;
    const stopBtn = document.getElementById('stop-btn');
    if (running) {
        sendBtn.disabled = true;
        sendBtn.style.display = 'none';
        stopBtn.style.display = 'flex';
    } else {
        sendBtn.disabled = false;
        sendBtn.style.display = 'flex';
        stopBtn.style.display = 'none';
    }
}

function stopAgent() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ cancel: true }));
}

function showError(message) {
    if (currentMessageEl) {
        const contentEl = currentMessageEl.querySelector('.message-content');
        if (contentEl) {
            contentEl.innerHTML = `<span class="error"><i class="ri-error-warning-line"></i> Error: ${escapeHtml(message)}</span>`;
        }
    } else {
        addMessage(`Error: ${message}`, 'system');
    }

    finishMessage();
}

// ---------------------------------------------------------------------------
// Human-in-the-Loop Approval Dialog
// ---------------------------------------------------------------------------

let pendingApprovals = [];

function showApprovalDialog(requests) {
    pendingApprovals = requests;

    if (!currentMessageEl) {
        currentMessageEl = createMessageContainer('assistant');
    }

    const contentEl = currentMessageEl.querySelector('.message-content');
    if (!contentEl) return;

    let html = '<div class="approval-dialog">';
    html += '<h4><i class="ri-alert-line"></i> Approval Required</h4>';
    html += '<p>The following operations require your approval:</p>';

    for (const req of requests) {
        html += `
            <div class="approval-item" data-id="${req.tool_call_id}">
                <div class="approval-tool">
                    <span class="tool-icon"><i class="ri-settings-5-line"></i></span>
                    <strong>${escapeHtml(req.tool_name)}</strong>
                </div>
                <div class="approval-args">${formatToolArgs(req.args)}</div>
            </div>
        `;
    }

    html += `
        <div class="approval-buttons">
            <button class="approve-btn" onclick="handleApprovalResponse(true)">Approve All</button>
            <button class="deny-btn" onclick="handleApprovalResponse(false)">Deny All</button>
        </div>
    </div>`;

    contentEl.innerHTML = html;
    forceScroll();
}

function handleApprovalResponse(approved) {
    if (!pendingApprovals.length) return;

    const approvalResponse = {};
    for (const req of pendingApprovals) {
        approvalResponse[req.tool_call_id] = approved;
    }

    pendingApprovals = [];

    if (currentMessageEl) {
        const contentEl = currentMessageEl.querySelector('.message-content');
        if (contentEl) {
            contentEl.innerHTML = `<p>${approved ? '<i class="ri-check-line"></i> Approved' : '<i class="ri-close-line"></i> Denied'} - continuing...</p>`;
        }
    }

    ws.send(JSON.stringify({approval: approvalResponse}));
}

// Pending file attachments for next message
let pendingAttachments = [];

function setupEventListeners() {
    messageInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    messageInput.addEventListener('input', () => {
        messageInput.style.height = 'auto';
        messageInput.style.height = Math.min(messageInput.scrollHeight, 150) + 'px';
    });

    // Paste handler for images/files
    messageInput.addEventListener('paste', (e) => {
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.kind === 'file') {
                e.preventDefault();
                const file = item.getAsFile();
                if (file) addAttachment(file);
            }
        }
    });

    // Chat file input (paperclip button)
    const chatFileInput = document.getElementById('chat-file-input');
    chatFileInput.addEventListener('change', (e) => {
        for (const file of e.target.files) {
            addAttachment(file);
        }
        chatFileInput.value = '';
    });

    // Drag & drop to chat area
    const chatPanel = document.querySelector('.chat-panel');
    chatPanel.addEventListener('dragover', (e) => {
        e.preventDefault();
        chatPanel.classList.add('drag-active');
    });
    chatPanel.addEventListener('dragleave', (e) => {
        if (!chatPanel.contains(e.relatedTarget)) {
            chatPanel.classList.remove('drag-active');
        }
    });
    chatPanel.addEventListener('drop', (e) => {
        e.preventDefault();
        chatPanel.classList.remove('drag-active');
        for (const file of e.dataTransfer.files) {
            addAttachment(file);
        }
    });


    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTab = btn.dataset.tab;

            const configPanel = document.getElementById('config-panel');
            const sessionsPanel = document.getElementById('sessions-panel');
            // Hide all panels
            filesList.style.display = 'none';
            configPanel.style.display = 'none';
            if (sessionsPanel) sessionsPanel.style.display = 'none';

            if (currentTab === 'config') {
                configPanel.style.display = 'block';
                renderConfigPanel();
            } else if (currentTab === 'sessions') {
                if (sessionsPanel) sessionsPanel.style.display = 'block';
                loadSessionsList();
            } else if (currentTab === 'files') {
                filesList.style.display = 'block';
                refreshFiles();
            }
        });
    });
}

function setupResizer() {
    const resizer = document.getElementById('drag-handle');
    const root = document.documentElement;
    let isResizing = false;

    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        resizer.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;

        let newWidth = e.clientX;
        if (newWidth < 200) newWidth = 200;
        if (newWidth > 600) newWidth = 600;

        root.style.setProperty('--sidebar-width', `${newWidth}px`);
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            resizer.classList.remove('active');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
}

async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message && pendingAttachments.length === 0) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        addMessage('Not connected to server. Reconnecting...', 'system');
        connectWebSocket();
        return;
    }

    // Read attachments as base64 locally
    const attachments = [];
    if (pendingAttachments.length > 0) {
        for (const file of pendingAttachments) {
            const base64 = await readFileAsBase64(file);
            attachments.push({
                name: file.name,
                type: file.type || 'application/octet-stream',
                data: base64,
                size: file.size,
            });
        }
    }

    // Clear input immediately
    messageInput.value = '';
    messageInput.style.height = 'auto';
    pendingAttachments = [];
    renderAttachments();

    // Remove welcome banner if present
    const banner = messagesContainer.querySelector('.welcome-banner');
    if (banner) {
        const bannerMsg = banner.closest('.message');
        if (bannerMsg) bannerMsg.remove();
    }

    // Show user message with attachment chips
    addMessage(message, 'user', attachments);

    // Send everything via WebSocket in one shot
    const payload = { message: message };
    if (sessionId) payload.session_id = sessionId;
    if (attachments.length > 0) payload.attachments = attachments;
    ws.send(JSON.stringify(payload));

    setAgentRunning(true);
}

function readFileAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

function addAttachment(file) {
    if (pendingAttachments.some(f => f.name === file.name && f.size === file.size)) return;
    pendingAttachments.push(file);
    renderAttachments();
}

function removeAttachment(index) {
    pendingAttachments.splice(index, 1);
    renderAttachments();
}

function renderAttachments() {
    const container = document.getElementById('attached-files');
    if (!container) return;

    if (pendingAttachments.length === 0) {
        container.innerHTML = '';
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';
    container.innerHTML = pendingAttachments.map((file, i) => {
        const iconClass = getFileIconClass(file.name);
        const isImage = file.type.startsWith('image/');
        let preview = '';
        if (isImage) {
            const url = URL.createObjectURL(file);
            preview = `<img src="${url}" class="attachment-thumb" alt="">`;
        }
        return `
            <div class="attachment-chip">
                ${preview || `<i class="${iconClass}"></i>`}
                <span class="attachment-name">${escapeHtml(file.name)}</span>
                <span class="attachment-size">${formatBytes(file.size)}</span>
                <button class="attachment-remove" onclick="removeAttachment(${i})" title="Remove">
                    <i class="ri-close-line"></i>
                </button>
            </div>
        `;
    }).join('');
}

function sendQuickMessage(message) {
    messageInput.value = message;
    sendMessage();
}

function addMessage(content, type, attachments = []) {
    const id = 'msg-' + Date.now();
    const messageEl = document.createElement('div');
    messageEl.className = `message ${type}`;
    messageEl.id = id;

    const labelMap = {
        'user': {text: 'You', i: 'ri-user-smile-line'},
        'assistant': {text: 'DeepResearch', i: 'ri-search-eye-line'},
        'system': {text: 'System', i: 'ri-error-warning-fill'}
    };
    const info = labelMap[type];

    // Build attachment chips HTML
    let attachHtml = '';
    if (attachments.length > 0) {
        const chips = attachments.map(a => {
            const iconClass = getFileIconClass(a.name);
            const isImage = (a.type || '').startsWith('image/');
            let thumb = '';
            if (isImage && a.data) {
                thumb = `<img src="data:${a.type};base64,${a.data}" class="msg-attach-thumb" alt="">`;
            }
            return `<div class="msg-attach-chip">${thumb || `<i class="${iconClass}"></i>`}<span class="msg-attach-name">${escapeHtml(a.name)}</span><span class="msg-attach-size">${formatBytes(a.size)}</span></div>`;
        }).join('');
        attachHtml = `<div class="msg-attachments">${chips}</div>`;
    }

    messageEl.innerHTML = `
        <div class="message-header">
            <i class="${info.i}"></i> <span>${info.text}</span>
            <button class="msg-copy-btn" onclick="copyMessage(this)" title="Copy"><i class="ri-file-copy-line"></i></button>
        </div>
        ${attachHtml}
        <div class="message-content">${content ? formatMessage(content) : ''}</div>
    `;

    messagesContainer.appendChild(messageEl);
    forceScroll();
    updateOutlinePanel();

    return id;
}

function formatMessage(content) {
    if (!content) return '';

    // Pre-process: extract code blocks to protect them from other formatting
    const codeBlocks = [];
    let processed = content.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
        const idx = codeBlocks.length;
        codeBlocks.push({ lang: lang || 'none', code });
        return `%%CODEBLOCK_${idx}%%`;
    });

    // Escape HTML (but not our placeholders)
    processed = escapeHtml(processed);

    // Headers (must be at start of line)
    processed = processed.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    processed = processed.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    processed = processed.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    processed = processed.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Horizontal rule
    processed = processed.replace(/^---$/gm, '<hr>');

    // Blockquotes
    processed = processed.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');

    // Tables
    processed = processed.replace(/((?:^\|.+\|$\n?)+)/gm, (tableBlock) => {
        const rows = tableBlock.trim().split('\n');
        if (rows.length < 2) return tableBlock;

        const separator = rows[1];
        if (!/^\|[\s\-:|]+\|$/.test(separator)) return tableBlock;

        let html = '<table class="md-table"><thead><tr>';
        const headers = rows[0].split('|').filter(c => c.trim());
        for (const h of headers) {
            html += `<th>${h.trim()}</th>`;
        }
        html += '</tr></thead><tbody>';

        for (let i = 2; i < rows.length; i++) {
            const cells = rows[i].split('|').filter(c => c.trim());
            if (cells.length === 0) continue;
            html += '<tr>';
            for (const c of cells) {
                html += `<td>${c.trim()}</td>`;
            }
            html += '</tr>';
        }
        html += '</tbody></table>';
        return html;
    });

    // Unordered lists (-, *)
    processed = processed.replace(/((?:^[\s]*[-*] .+$\n?)+)/gm, (listBlock) => {
        const items = listBlock.trim().split('\n');
        let html = '<ul>';
        for (const item of items) {
            const text = item.replace(/^\s*[-*] /, '');
            html += `<li>${text}</li>`;
        }
        html += '</ul>';
        return html;
    });

    // Ordered lists (1. 2. etc)
    processed = processed.replace(/((?:^\d+\. .+$\n?)+)/gm, (listBlock) => {
        const items = listBlock.trim().split('\n');
        let html = '<ol>';
        for (const item of items) {
            const text = item.replace(/^\d+\. /, '');
            html += `<li>${text}</li>`;
        }
        html += '</ol>';
        return html;
    });

    // Inline formatting
    processed = processed.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    processed = processed.replace(/\*([^*]+)\*/g, '<em>$1</em>');
    processed = processed.replace(/~~([^~]+)~~/g, '<del>$1</del>');
    processed = processed.replace(/`([^`]+)`/g, '<code>$1</code>');

    // Links [text](url)
    processed = processed.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // Line breaks
    processed = processed.replace(/\n/g, '<br>');

    // Restore code blocks with syntax highlighting
    for (let i = 0; i < codeBlocks.length; i++) {
        const { lang, code } = codeBlocks[i];
        const escapedCode = escapeHtml(code);
        const langLabel = lang && lang !== 'none' ? `<span class="code-lang">${lang}</span>` : '';
        const copyBtn = `<button class="code-copy-btn" onclick="copyCodeBlock(this)" title="Copy"><i class="ri-file-copy-line"></i></button>`;
        processed = processed.replace(
            `%%CODEBLOCK_${i}%%`,
            `<div class="code-block-wrapper">${langLabel}${copyBtn}<pre><code class="language-${lang}">${escapedCode}</code></pre></div>`
        );
    }

    // Linkify file paths
    processed = linkifyFilePaths(processed);

    // Linkify Excalidraw URLs — render as diagram links with icon
    processed = linkifyExcalidrawUrls(processed);

    // Trigger Prism highlighting after DOM update
    setTimeout(() => {
        document.querySelectorAll('.message-content pre code[class*="language-"]').forEach(el => {
            if (window.Prism && !el.classList.contains('prism-highlighted')) {
                Prism.highlightElement(el);
                el.classList.add('prism-highlighted');
            }
        });
    }, 10);

    return processed;
}

function copyCodeBlock(btn) {
    const pre = btn.closest('.code-block-wrapper').querySelector('code');
    if (!pre) return;
    navigator.clipboard.writeText(pre.textContent).then(() => {
        const orig = btn.innerHTML;
        btn.innerHTML = '<i class="ri-check-line"></i>';
        setTimeout(() => btn.innerHTML = orig, 1000);
    });
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function handleFileSelect(e) {
    const file = e.target.files[0];
    if (file) {
        uploadFile(file);
    }
}

async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);

    let url = '/upload';
    if (sessionId) {
        url += `?session_id=${encodeURIComponent(sessionId)}`;
    }

    try {
        const response = await fetch(url, {method: 'POST', body: formData});
        const data = await response.json();

        if (response.ok) {
            if (data.session_id && !sessionId) {
                sessionId = data.session_id;
                localStorage.setItem('sessionId', sessionId);
            }
            refreshFiles();
            addMessage(`File uploaded: ${data.filename} (${formatBytes(data.size)})`, 'system');
        } else {
            addMessage(`Upload error: ${data.detail}`, 'system');
        }
    } catch (error) {
        addMessage(`Upload error: ${error.message}`, 'system');
    }
}

const expandedFolders = new Set();

async function refreshFiles() {
    if (!sessionId) return;

    try {
        const response = await fetch(`/files?session_id=${encodeURIComponent(sessionId)}`);
        if (!response.ok) return;
        const data = await response.json();

        const uploads = data.uploads || [];
        const workspace = data.workspace || [];

        if (uploads.length === 0 && workspace.length === 0) {
            filesList.innerHTML = '<p class="empty-state">No files yet</p>';
            return;
        }

        let html = '';

        if (uploads.length > 0) {
            html += '<div class="file-section-title"><i class="ri-upload-cloud-2-line"></i> Uploads</div>';
            html += uploads.map(file => {
                const name = typeof file === 'string' ? file.split('/').pop() : file;
                const fullPath = `/uploads/${name}`;
                const iconClass = getFileIconClass(name);
                return `
                    <div class="file-item clickable" onclick="openFilePreview('${escapeHtml(fullPath)}')" title="Click to preview">
                        <i class="${iconClass}"></i>
                        <span>${escapeHtml(name)}</span>
                    </div>
                `;
            }).join('');
        }

        if (workspace.length > 0) {
            html += '<div class="file-section-title"><i class="ri-folder-3-line"></i> Workspace</div>';
            const tree = buildFileTree(workspace);
            html += renderFileTree(tree, 0);
        }

        filesList.innerHTML = html;

    } catch (error) {
        filesList.innerHTML = '<p class="empty-state">Error loading files</p>';
    }
}

function buildFileTree(filePaths) {
    const root = {};

    for (const filePath of filePaths) {
        let normalizedPath = filePath;
        if (normalizedPath.startsWith('/workspace/')) {
            normalizedPath = normalizedPath.slice('/workspace/'.length);
        } else if (normalizedPath.startsWith('/')) {
            normalizedPath = normalizedPath.slice(1);
        }

        const parts = normalizedPath.split('/');
        let current = root;

        for (let i = 0; i < parts.length; i++) {
            const part = parts[i];
            if (!part) continue;

            if (i === parts.length - 1) {
                current[part] = {__isFile: true, __path: filePath};
            } else {
                if (!current[part]) {
                    current[part] = {};
                }
                current = current[part];
            }
        }
    }

    return root;
}

function renderFileTree(node, depth, parentPath = '/workspace') {
    let html = '';
    const entries = Object.entries(node).sort((a, b) => {
        const aIsFile = a[1].__isFile;
        const bIsFile = b[1].__isFile;
        if (aIsFile && !bIsFile) return 1;
        if (!aIsFile && bIsFile) return -1;
        return a[0].localeCompare(b[0]);
    });

    for (const [name, value] of entries) {
        if (name.startsWith('__')) continue;

        const currentPath = `${parentPath}/${name}`;
        const indent = depth * 12;

        if (value.__isFile) {
            const iconClass = getFileIconClass(name);
            html += `
                <div class="file-item clickable" style="padding-left: ${indent + 8}px"
                     onclick="openFilePreview('${escapeHtml(value.__path)}')" title="${escapeHtml(value.__path)}">
                    <i class="${iconClass}"></i>
                    <span>${escapeHtml(name)}</span>
                </div>
            `;
        } else {
            const isExpanded = expandedFolders.has(currentPath);
            const folderIcon = isExpanded ? 'ri-folder-open-line' : 'ri-folder-line';
            const chevronIcon = isExpanded ? 'ri-arrow-down-s-line' : 'ri-arrow-right-s-line';

            html += `
                <div class="folder-item ${isExpanded ? 'expanded' : ''}" style="padding-left: ${indent + 8}px"
                     onclick="toggleFolder('${escapeHtml(currentPath)}')">
                    <i class="folder-chevron ${chevronIcon}"></i>
                    <i class="folder-icon ${folderIcon}"></i>
                    <span>${escapeHtml(name)}</span>
                </div>
            `;

            if (isExpanded) {
                html += `<div class="folder-children">`;
                html += renderFileTree(value, depth + 1, currentPath);
                html += `</div>`;
            }
        }
    }

    return html;
}

function toggleFolder(folderPath) {
    if (expandedFolders.has(folderPath)) {
        expandedFolders.delete(folderPath);
    } else {
        expandedFolders.add(folderPath);
    }
    refreshFiles();
}

// ---------------------------------------------------------------------------
// Sticky Tasks Panel (above input)
// ---------------------------------------------------------------------------

let latestTodos = [];
let tasksCollapsed = true;
let tasksStartTime = 0;
let tasksTimerInterval = null;

function handleTodosUpdate(todos) {
    console.log('[tasks] todos_update received:', todos);
    latestTodos = todos || [];
    renderTasksPanel(latestTodos);
}

function renderTasksPanel(todos) {
    const panel    = document.getElementById('tasks-panel');
    const label    = document.getElementById('tasks-label');
    const badge    = document.getElementById('tasks-badge');
    const fill     = document.getElementById('tasks-progress-fill');
    const preview  = document.getElementById('tasks-preview');
    const list     = document.getElementById('tasks-list');
    const elapsed  = document.getElementById('tasks-elapsed');

    if (!todos || todos.length === 0) {
        panel.style.display = 'none';
        _stopTasksTimer();
        return;
    }

    panel.style.display = 'block';

    const completed  = todos.filter(t => t.status === 'completed').length;
    const total      = todos.length;
    const pct        = Math.round((completed / total) * 100);
    const allDone    = completed === total;
    const inProgress = todos.find(t => t.status === 'in_progress');

    label.textContent = allDone ? 'Tasks Complete' : 'Task Progress';
    badge.textContent = `${completed}/${total}`;
    panel.classList.toggle('all-done', allDone);

    fill.style.width = pct + '%';

    if (!allDone && tasksStartTime === 0) {
        tasksStartTime = Date.now();
        _startTasksTimer();
    }
    if (allDone) _stopTasksTimer();
    elapsed.style.display = (!allDone && tasksStartTime) ? 'flex' : 'none';

    if (tasksCollapsed && inProgress && total > 1) {
        const remaining = total - completed - 1;
        preview.innerHTML =
            `<i class="ri-loader-4-line"></i>` +
            `<span class="tasks-preview-text">${escapeHtml(inProgress.active_form || inProgress.content)}</span>` +
            (remaining > 0 ? `<span class="tasks-more">+${remaining} more</span>` : '');
        preview.style.display = 'flex';
    } else {
        preview.style.display = 'none';
    }

    if (!tasksCollapsed) {
        let html = '';
        for (const todo of todos) {
            const st = todo.status || 'pending';
            const icons = {
                completed:   'ri-checkbox-circle-fill',
                in_progress: 'ri-loader-4-line',
                pending:     'ri-checkbox-blank-circle-line',
            };
            const text = (st === 'in_progress' && todo.active_form) ? todo.active_form : todo.content;
            html += `<div class="task-row ${st}">` +
                `<span class="task-icon"><i class="${icons[st] || icons.pending}"></i></span>` +
                `<span>${escapeHtml(text)}</span></div>`;
        }
        list.innerHTML = html;
        list.style.display = 'flex';
    } else {
        list.style.display = 'none';
    }
}

function toggleTasksPanel() {
    tasksCollapsed = !tasksCollapsed;
    document.getElementById('tasks-panel').classList.toggle('expanded', !tasksCollapsed);
    renderTasksPanel(latestTodos);
}

function _startTasksTimer() {
    if (tasksTimerInterval) return;
    tasksTimerInterval = setInterval(() => {
        const secs = Math.floor((Date.now() - tasksStartTime) / 1000);
        const el = document.getElementById('tasks-elapsed-text');
        if (el) el.textContent = secs < 60 ? `${secs}s` : `${Math.floor(secs/60)}m ${secs%60}s`;
    }, 1000);
}

function _stopTasksTimer() {
    if (tasksTimerInterval) { clearInterval(tasksTimerInterval); tasksTimerInterval = null; }
    tasksStartTime = 0;
}

function resetTasksPanel() {
    latestTodos = [];
    tasksCollapsed = true;
    _stopTasksTimer();
    const panel = document.getElementById('tasks-panel');
    if (panel) { panel.style.display = 'none'; panel.classList.remove('all-done', 'expanded'); }
}


function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

let currentPreviewPath = null;
let currentPreviewContent = null;
let currentPreviewMode = 'code';

const filePreviewPanel = document.getElementById('file-preview-panel');
const previewFilename = document.getElementById('preview-filename');
const previewContainer = document.getElementById('preview-container');
const previewIcon = document.getElementById('preview-icon');
const previewModeToggle = document.getElementById('preview-mode-toggle');

const PREVIEWABLE_EXTENSIONS = ['html', 'htm', 'svg'];

async function openFilePreview(filePath) {
    if (!sessionId) return;

    try {
        const filename = filePath.split('/').pop();
        previewFilename.textContent = filename;
        const iconClass = getFileIconClass(filename);
        previewIcon.innerHTML = `<i class="${iconClass}"></i>`;

        filePreviewPanel.classList.remove('hidden');
        previewContainer.innerHTML = '<div style="padding: 20px; color: var(--text-muted);">Loading...</div>';

        const ext = filename.split('.').pop().toLowerCase();
        if (PREVIEWABLE_EXTENSIONS.includes(ext)) {
            previewModeToggle.classList.add('visible');
        } else {
            previewModeToggle.classList.remove('visible');
            currentPreviewMode = 'code';
        }

        updatePreviewModeButtons();

        if (ext === 'pdf') {
            currentPreviewPath = filePath;
            currentPreviewContent = '';
            previewContainer.innerHTML = `
                <embed class="embed-container" src="/files/binary/${encodeURIComponent(filePath)}?session_id=${encodeURIComponent(sessionId)}" type="application/pdf">
            `;
            return;
        }

        const response = await fetch(`/files/content/${encodeURIComponent(filePath)}?session_id=${encodeURIComponent(sessionId)}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to load file');
        }

        const data = await response.json();
        currentPreviewPath = filePath;
        currentPreviewContent = stripLineNumbers(data.content);

        renderPreview(filename, currentPreviewContent);

    } catch (error) {
        console.error('Error loading file:', error);
        previewContainer.innerHTML = `<div style="padding: 20px; color: var(--error);">Error loading file: ${escapeHtml(error.message)}</div>`;
    }
}

function setPreviewMode(mode) {
    currentPreviewMode = mode;
    updatePreviewModeButtons();

    if (currentPreviewPath && currentPreviewContent) {
        const filename = currentPreviewPath.split('/').pop();
        renderPreview(filename, currentPreviewContent);
    }
}

function updatePreviewModeButtons() {
    const buttons = previewModeToggle.querySelectorAll('.mode-btn');
    buttons.forEach(btn => {
        if (btn.dataset.mode === currentPreviewMode) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

function renderPreview(filename, content) {
    const ext = filename.split('.').pop().toLowerCase();

    if (currentPreviewMode === 'preview' && PREVIEWABLE_EXTENSIONS.includes(ext)) {
        renderLivePreview(content, ext);
        return;
    }

    if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'ico'].includes(ext)) {
        const imageUrl = `/files/binary/${encodeURIComponent(currentPreviewPath)}?session_id=${encodeURIComponent(sessionId)}`;
        previewContainer.innerHTML = `
            <div style="display:flex; justify-content:center; align-items:center; height:100%; padding:20px; background:#1a1a1a;">
                <img src="${imageUrl}" alt="${escapeHtml(filename)}" style="max-width:100%; max-height:100%; object-fit:contain; border-radius:4px;">
            </div>
        `;
        return;
    }

    if (ext === 'csv') {
        const tableHtml = parseCSVtoTable(content);
        previewContainer.innerHTML = `<div class="csv-container">${tableHtml}</div>`;
        return;
    }

    if (ext === 'pdf') {
        previewContainer.innerHTML = `
            <embed class="embed-container" src="/files/binary/${encodeURIComponent(currentPreviewPath)}?session_id=${sessionId}" type="application/pdf">
        `;
        return;
    }

    const languageMap = {
        'js': 'javascript', 'py': 'python', 'rs': 'rust', 'html': 'html',
        'css': 'css', 'json': 'json', 'md': 'markdown', 'sh': 'bash',
        'ts': 'typescript', 'go': 'go', 'java': 'java', 'cpp': 'cpp',
        'htm': 'html', 'svg': 'xml'
    };

    const lang = languageMap[ext] || 'none';

    const pre = document.createElement('pre');
    const code = document.createElement('code');
    code.className = `language-${lang}`;
    code.textContent = content;

    pre.appendChild(code);
    previewContainer.innerHTML = '';
    previewContainer.appendChild(pre);

    if (window.Prism) {
        Prism.highlightElement(code);
    }
}

function renderLivePreview(content, ext) {
    const iframe = document.createElement('iframe');
    iframe.className = 'live-preview-frame';
    iframe.sandbox = 'allow-scripts allow-same-origin';

    previewContainer.innerHTML = '';
    previewContainer.appendChild(iframe);

    if (ext === 'svg') {
        const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
        iframeDoc.open();
        iframeDoc.write(`
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {
                        margin: 0;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        min-height: 100vh;
                        background: #1a1a1a;
                    }
                    svg {
                        max-width: 90%;
                        max-height: 90vh;
                    }
                </style>
            </head>
            <body>${content}</body>
            </html>
        `);
        iframeDoc.close();
    } else {
        const previewUrl = `/preview/${sessionId}${currentPreviewPath}`;
        iframe.src = previewUrl;
    }
}

function stripLineNumbers(content) {
    if (!content) return content;

    return content.split('\n').map(line => {
        const match = line.match(/^\s*\d+\t(.*)$/);
        return match ? match[1] : line;
    }).join('\n');
}

function parseCSVLine(line) {
    const result = [];
    let current = '';
    let inQuotes = false;

    for (let i = 0; i < line.length; i++) {
        const char = line[i];
        const nextChar = line[i + 1];

        if (char === '"') {
            if (inQuotes && nextChar === '"') {
                current += '"';
                i++;
            } else {
                inQuotes = !inQuotes;
            }
        } else if (char === ',' && !inQuotes) {
            result.push(current.trim());
            current = '';
        } else {
            current += char;
        }
    }

    result.push(current.trim());
    return result;
}

function parseCSVtoTable(csvText) {
    const lines = csvText.trim().split(/\r?\n/);
    if (lines.length === 0) return '<p>Empty CSV</p>';

    const headers = parseCSVLine(lines[0]);
    const numCols = headers.length;

    let html = '<table class="csv-table"><thead><tr>';
    html += `<th class="row-num">#</th>`;
    headers.forEach(h => html += `<th>${escapeHtml(h)}</th>`);
    html += '</tr></thead><tbody>';

    for (let i = 1; i < lines.length; i++) {
        if (!lines[i].trim()) continue;

        const row = parseCSVLine(lines[i]);

        html += '<tr>';
        html += `<td class="row-num">${i}</td>`;
        for (let j = 0; j < numCols; j++) {
            const cell = row[j] || '';
            const displayCell = cell.length > 100 ? cell.substring(0, 100) + '...' : cell;
            html += `<td title="${escapeHtml(cell)}">${escapeHtml(displayCell)}</td>`;
        }
        html += '</tr>';
    }
    html += '</tbody></table>';

    const rowCount = lines.length - 1;
    html = `<div class="csv-info">${rowCount} rows x ${numCols} columns</div>` + html;

    return html;
}

function closeFilePreview() {
    filePreviewPanel.classList.add('hidden');
    currentPreviewPath = null;
    currentPreviewContent = null;
}

async function copyFileContent() {
    if (!currentPreviewContent) return;
    try {
        await navigator.clipboard.writeText(currentPreviewContent);
        const btn = filePreviewPanel.querySelector('.preview-btn[onclick="copyFileContent()"]');
        const originalIcon = btn.innerHTML;
        btn.innerHTML = '<i class="ri-check-line" style="color: var(--success)"></i>';
        setTimeout(() => btn.innerHTML = originalIcon, 1000);
    } catch (error) {
        console.error('Failed to copy:', error);
    }
}

function downloadPreviewFile() {
    if (!currentPreviewPath || !currentPreviewContent) return;
    const filename = currentPreviewPath.split('/').pop();
    const blob = new Blob([currentPreviewContent], {type: 'text/plain'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Report Export (MD / HTML / PDF)
// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// Background task toast notifications
// ---------------------------------------------------------------------------

function updateBackgroundBadge() {
    let badge = document.getElementById('bg-agents-badge');
    if (backgroundAgentCount <= 0) {
        if (badge) badge.style.display = 'none';
        return;
    }
    if (!badge) {
        badge = document.createElement('div');
        badge.id = 'bg-agents-badge';
        badge.className = 'bg-agents-badge';
        document.querySelector('.input-container').prepend(badge);
    }
    badge.style.display = 'flex';
    badge.innerHTML = `<i class="ri-loader-4-line spinning"></i> ${backgroundAgentCount} agent${backgroundAgentCount > 1 ? 's' : ''} working`;
}

function showBackgroundTaskToast(data) {
    // Update background agent tracking
    if (data.task_id) {
        backgroundAgentTasks.delete(data.task_id);
        backgroundAgentCount = backgroundAgentTasks.size;
        updateBackgroundBadge();
    }

    const isSuccess = data.status === 'completed';
    const isError = data.status === 'failed';
    const durationText = data.duration_seconds ? ` in ${data.duration_seconds.toFixed(1)}s` : '';
    const statusLabel = isSuccess ? 'Completed' : isError ? 'Failed' : data.status;
    const statusClass = isSuccess ? 'completed' : isError ? 'failed' : 'info';
    const statusIcon = isSuccess ? 'ri-checkbox-circle-fill' : isError ? 'ri-error-warning-fill' : 'ri-information-fill';

    // Always insert a result card into the chat
    _insertSubagentResultCard(data, statusClass, statusIcon, statusLabel, durationText);

    // Skip toast during replay (card is enough)
    if (isReplay) return;

    // Brief toast notification (just the header, no "View Result" button)
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${isSuccess ? 'success' : isError ? 'error' : 'info'}`;
    toast.innerHTML = `
        <div class="toast-icon"><i class="${statusIcon}"></i></div>
        <div class="toast-body">
            <div class="toast-title">${escapeHtml(data.subagent_name)} — ${statusLabel}${durationText}</div>
            <div class="toast-desc">${escapeHtml(data.description || '').substring(0, 80)}</div>
        </div>
        <button class="toast-close" onclick="this.closest('.toast').remove()"><i class="ri-close-line"></i></button>
    `;
    container.appendChild(toast);

    // Auto-dismiss after 5s (result is already in chat)
    setTimeout(() => {
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

function _insertSubagentResultCard(data, statusClass, statusIcon, statusLabel, durationText) {
    // Find or create assistant message container for the result
    let msgEl = currentMessageEl;
    if (!msgEl) {
        msgEl = createMessageContainer('assistant');
    }

    const toolsEl = msgEl.querySelector('.message-tools');
    if (!toolsEl) return;

    const catColor = '#06b6d4'; // agents category color
    const resultEl = document.createElement('div');
    resultEl.className = `subagent-result-card ${statusClass}`;
    resultEl.innerHTML = `
        <div class="subagent-result-header">
            <span class="tool-icon-badge" style="background:${catColor}22;color:${catColor}"><i class="ri-robot-2-line"></i></span>
            <span class="subagent-result-name" style="color:${catColor}">${escapeHtml(data.subagent_name)}</span>
            <span class="subagent-result-status ${statusClass}"><i class="${statusIcon}"></i> ${statusLabel}${durationText}</span>
        </div>
        <div class="subagent-result-desc">${escapeHtml(data.description || '')}</div>
        ${data.result_preview ? `
        <div class="subagent-result-body collapsed">
            <div class="subagent-result-content">${formatMessage(data.result_preview)}</div>
        </div>
        <button class="subagent-result-toggle" onclick="_toggleSubagentResult(this)">
            <i class="ri-arrow-down-s-line"></i> Show result
        </button>
        ` : ''}
        ${data.error ? `<div class="subagent-result-error">${escapeHtml(data.error.substring(0, 300))}</div>` : ''}
    `;

    toolsEl.appendChild(resultEl);
    autoScroll();
}

function _toggleSubagentResult(btn) {
    const card = btn.closest('.subagent-result-card');
    const body = card.querySelector('.subagent-result-body');
    const isCollapsed = body.classList.contains('collapsed');
    body.classList.toggle('collapsed');
    btn.innerHTML = isCollapsed
        ? '<i class="ri-arrow-up-s-line"></i> Hide result'
        : '<i class="ri-arrow-down-s-line"></i> Show result';
}

// ---------------------------------------------------------------------------
// Report auto-preview
// ---------------------------------------------------------------------------

function handleReportUpdated(data) {
    const path = data.path;
    if (!path) return;

    // Auto-open file preview with the report
    openFilePreview(path);
}

function getFileIconClass(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        'py': 'ri-code-s-slash-line',
        'js': 'ri-javascript-line',
        'ts': 'ri-braces-line',
        'json': 'ri-braces-line',
        'csv': 'ri-grid-line',
        'md': 'ri-markdown-line',
        'txt': 'ri-file-text-line',
        'html': 'ri-html5-line',
        'css': 'ri-css3-line',
        'pdf': 'ri-file-pdf-line',
        'zip': 'ri-file-zip-line',
        'png': 'ri-image-line',
        'jpg': 'ri-image-line'
    };
    return icons[ext] || 'ri-file-line';
}

function linkifyFilePaths(html) {
    const pathPattern = /(\/(?:workspace|uploads|app|home|tmp|var|etc)\/[^\s<>"'`,;()[\]{}]+\.[a-zA-Z0-9]+)/g;
    return html.replace(pathPattern, (match, path) => {
        const cleanPath = path.replace(/[.,;:!?)]+$/, '');
        const trailing = path.slice(cleanPath.length);
        return `<span class="file-link" onclick="openFilePreview('${cleanPath}')" title="Click to preview">${escapeHtml(cleanPath)}</span>${trailing}`;
    });
}

function linkifyExcalidrawUrls(html) {
    // Turn excalidraw.com shareable URLs into clickable links
    let result = html.replace(
        /\[([^\]]*)\]\((https:\/\/excalidraw\.com\/#json=[^\)]+)\)/g,
        '<a href="$2" target="_blank" class="excalidraw-link"><i class="ri-artboard-line"></i> $1</a>'
    );
    result = result.replace(
        /(https:\/\/excalidraw\.com\/#json=[^\s<"']+)/g,
        '<a href="$1" target="_blank" class="excalidraw-link"><i class="ri-artboard-line"></i> Open in Excalidraw</a>'
    );
    return result;
}

// --- Config Panel ---

async function renderConfigPanel() {
    const configPanel = document.getElementById('config-panel');
    if (!configPanel) return;

    if (!configData) {
        try {
            const response = await fetch('/config');
            if (response.ok) {
                const raw = await response.json();
                configData = raw.features || raw;
                // Config loaded
            }
        } catch (e) {
            configPanel.innerHTML = '<p class="empty-state">Error loading config</p>';
            return;
        }
    }

    if (!configData) {
        configPanel.innerHTML = '<p class="empty-state">No config available</p>';
        return;
    }

    let html = '';

    // Runtime
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-server-line"></i> Runtime</div>
            <div class="config-item">
                <span class="config-label">Docker Runtime</span>
                <span class="config-value">${escapeHtml(configData.runtime || 'default')}</span>
            </div>
        </div>
    `;

    // Hooks
    const hooks = configData.hooks || [];
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-shield-check-line"></i> Hooks (${hooks.length})</div>
    `;
    for (const hook of hooks) {
        html += `
            <div class="config-item">
                <span class="config-label">${escapeHtml(hook.name || hook.event)}</span>
                <span class="config-value tag">${escapeHtml(hook.event)}</span>
            </div>
        `;
        if (hook.description) {
            html += `<div class="config-sub-item">${escapeHtml(hook.description)}</div>`;
        }
        if (hook.matcher) {
            html += `<div class="config-sub-item">matcher: <code>${escapeHtml(hook.matcher)}</code></div>`;
        }
        if (hook.background) {
            html += `<div class="config-sub-item">background: true</div>`;
        }
    }
    html += '</div>';

    // Middleware
    const middleware = configData.middleware || [];
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-stack-line"></i> Middleware (${middleware.length})</div>
    `;
    for (const mw of middleware) {
        const name = typeof mw === 'string' ? mw : (mw.name || 'unknown');
        const desc = typeof mw === 'object' && mw.description ? mw.description : '';
        html += `
            <div class="config-item">
                <span class="config-label">${escapeHtml(name)}</span>
                ${desc ? `<span class="config-value tag">${escapeHtml(desc)}</span>` : ''}
            </div>
        `;
    }
    html += '</div>';

    // Processors
    const procs = configData.processors || {};
    const eviction = procs.eviction || {};
    const slidingWindow = procs.sliding_window || {};
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-cpu-line"></i> Processors</div>
            <div class="config-item">
                <span class="config-label">Eviction Limit</span>
                <span class="config-value">${eviction.token_limit ? eviction.token_limit + ' tokens' : 'disabled'}</span>
            </div>
            <div class="config-item">
                <span class="config-label">Patch Tool Calls</span>
                <span class="config-value">${procs.patch_tool_calls ? 'enabled' : 'disabled'}</span>
            </div>
            <div class="config-item">
                <span class="config-label">Sliding Window</span>
                <span class="config-value">${slidingWindow.trigger ? slidingWindow.trigger + ' -> keep ' + slidingWindow.keep : 'disabled'}</span>
            </div>
        </div>
    `;

    // MCP Servers
    const mcpServers = configData.mcp_servers || [];
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-plug-line"></i> MCP Servers (${mcpServers.length})</div>
    `;
    for (const server of mcpServers) {
        const name = typeof server === 'string' ? server : (server.name || server.prefix || 'unknown');
        const stype = typeof server === 'object' && server.type ? server.type : '';
        html += `
            <div class="config-item">
                <span class="config-label">${escapeHtml(name)}</span>
                ${stype ? `<span class="config-value tag">${escapeHtml(stype)}</span>` : ''}
            </div>
        `;
    }
    html += '</div>';

    // Context Files
    const contextFiles = configData.context_files || [];
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-file-info-line"></i> Context Files (${contextFiles.length})</div>
    `;
    for (const cf of contextFiles) {
        html += `<div class="config-item"><span class="config-label">${escapeHtml(cf)}</span></div>`;
    }
    html += '</div>';

    // Checkpointing
    const cp = configData.checkpointing || {};
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-save-line"></i> Checkpointing</div>
            <div class="config-item">
                <span class="config-label">Status</span>
                <span class="config-value">${cp.enabled ? 'enabled' : 'disabled'}</span>
            </div>
            ${cp.enabled ? `
            <div class="config-item">
                <span class="config-label">Frequency</span>
                <span class="config-value">${escapeHtml(cp.frequency || 'unknown')}</span>
            </div>
            <div class="config-item">
                <span class="config-label">Max Checkpoints</span>
                <span class="config-value">${cp.max_checkpoints || 'unlimited'}</span>
            </div>
            ` : ''}
        </div>
    `;

    // Features
    const interruptTools = configData.interrupt_on
        ? Object.entries(configData.interrupt_on).filter(([, v]) => v).map(([k]) => k)
        : [];
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-toggle-line"></i> Features</div>
            <div class="config-item">
                <span class="config-label">Image Support</span>
                <span class="config-value">${configData.image_support ? 'enabled' : 'disabled'}</span>
            </div>
            <div class="config-item">
                <span class="config-label">Human-in-the-Loop</span>
                <span class="config-value">${interruptTools.length > 0 ? interruptTools.map(t => escapeHtml(t)).join(', ') : 'disabled'}</span>
            </div>
        </div>
    `;

    // Subagents
    const subagents = configData.subagents || [];
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-group-line"></i> Subagents (${subagents.length})</div>
    `;
    for (const sa of subagents) {
        const saName = typeof sa === 'string' ? sa : (sa.name || 'unknown');
        const saDesc = typeof sa === 'object' && sa.description ? sa.description : '';
        html += `
            <div class="config-item">
                <span class="config-label">${escapeHtml(saName)}</span>
                ${saDesc ? `<span class="config-value tag">${escapeHtml(saDesc)}</span>` : ''}
            </div>
        `;
    }
    if (configData.general_purpose_subagent) {
        html += `
            <div class="config-item">
                <span class="config-label">general-purpose</span>
                <span class="config-value tag">built-in</span>
            </div>
        `;
    }
    html += '</div>';

    // Skills
    const skills = configData.skills || [];
    const skillDirs = configData.skill_directories || [];
    html += `
        <div class="config-section">
            <div class="config-section-title"><i class="ri-lightbulb-line"></i> Skills</div>
    `;
    for (const dir of skillDirs) {
        html += `<div class="config-item"><span class="config-label">Dir: ${escapeHtml(typeof dir === 'string' ? dir : dir.path)}</span></div>`;
    }
    for (const sk of skills) {
        html += `
            <div class="config-item">
                <span class="config-label">${escapeHtml(sk.name || sk)}</span>
                <span class="config-value tag">programmatic</span>
            </div>
        `;
    }
    html += '</div>';

    // Tool Usage Stats
    html += `
        <div class="config-section" id="tool-stats-section">
            <div class="config-section-title"><i class="ri-bar-chart-box-line"></i> Tool Usage (Live)</div>
            <div id="tool-stats-content">
                ${renderToolStats()}
            </div>
        </div>
    `;

    configPanel.innerHTML = html;
}

function renderToolStats() {
    let html = `
        <div class="config-item">
            <span class="config-label">Total Calls</span>
            <span class="config-value">${toolStats.call_count}</span>
        </div>
        <div class="config-item">
            <span class="config-label">Total Duration</span>
            <span class="config-value">${(toolStats.total_duration_ms / 1000).toFixed(1)}s</span>
        </div>
    `;

    const toolsUsed = toolStats.tools_used || {};
    const entries = Object.entries(toolsUsed).sort((a, b) => b[1] - a[1]);
    if (entries.length > 0) {
        html += '<div class="config-sub-item" style="margin-top: 4px; font-weight: 500;">Breakdown:</div>';
        for (const [tool, count] of entries) {
            html += `
                <div class="config-item">
                    <span class="config-label" style="padding-left: 8px;">${escapeHtml(tool)}</span>
                    <span class="config-value">${count}</span>
                </div>
            `;
        }
    }

    return html;
}

function updateToolStatsDisplay() {
    const statsContent = document.getElementById('tool-stats-content');
    if (statsContent) {
        statsContent.innerHTML = renderToolStats();
    }
}

// --- Middleware & Hook Event Handlers ---

function handleMiddlewareEvent(data) {
    if (data.total_calls !== undefined) {
        toolStats.call_count = data.total_calls;
    }
    if (data.total_duration_ms !== undefined) {
        toolStats.total_duration_ms = data.total_duration_ms;
    }
    if (data.tools_breakdown) {
        toolStats.tools_used = data.tools_breakdown;
    }

    updateToolStatsDisplay();

    if (data.event === 'tool_audit' && data.tool_name && currentMessageEl) {
        const toolsEl = currentMessageEl.querySelector('.message-tools');
        if (toolsEl) {
            const badge = document.createElement('div');
            badge.className = 'middleware-badge';
            badge.innerHTML = `<i class="ri-shield-check-line"></i> ${escapeHtml(data.tool_name)} <span class="mw-count">#${data.total_calls}</span>`;
            toolsEl.appendChild(badge);
        }
    }
}

// --- Plan Mode: Ask User Question ---

function handleAskUserQuestion(data) {
    if (!currentMessageEl) {
        currentMessageEl = createMessageContainer('assistant');
    }

    const toolsEl = currentMessageEl.querySelector('.message-tools');
    if (!toolsEl) return;

    const container = document.createElement('div');
    container.className = 'ask-user-container';
    container.dataset.questionId = data.question_id;

    // Question text
    const questionEl = document.createElement('div');
    questionEl.className = 'ask-user-question';
    questionEl.innerHTML = `<i class="ri-question-line"></i> ${escapeHtml(data.question)}`;
    container.appendChild(questionEl);

    // Options
    const optionsEl = document.createElement('div');
    optionsEl.className = 'ask-user-options';

    (data.options || []).forEach(option => {
        const btn = document.createElement('button');
        btn.className = 'ask-user-option';
        const isRecommended = (option.recommended || '').toLowerCase() === 'true';
        if (isRecommended) btn.classList.add('recommended');

        btn.innerHTML = `
            <div class="option-top">
                <span class="option-label">${escapeHtml(option.label)}</span>
                ${isRecommended ? '<span class="option-badge">Recommended</span>' : ''}
            </div>
            ${option.description ? `<span class="option-desc">${escapeHtml(option.description)}</span>` : ''}
        `;
        btn.onclick = () => sendQuestionAnswer(data.question_id, option.label, container);
        optionsEl.appendChild(btn);
    });

    container.appendChild(optionsEl);

    // Custom answer input
    const customEl = document.createElement('div');
    customEl.className = 'ask-user-custom';
    const inputEl = document.createElement('input');
    inputEl.type = 'text';
    inputEl.placeholder = 'Or type your own answer...';
    inputEl.className = 'ask-user-input';
    inputEl.onkeydown = (e) => {
        if (e.key === 'Enter' && inputEl.value.trim()) {
            sendQuestionAnswer(data.question_id, inputEl.value.trim(), container);
        }
    };
    const submitBtn = document.createElement('button');
    submitBtn.className = 'ask-user-submit';
    submitBtn.innerHTML = '<i class="ri-send-plane-fill"></i>';
    submitBtn.onclick = () => {
        if (inputEl.value.trim()) {
            sendQuestionAnswer(data.question_id, inputEl.value.trim(), container);
        }
    };
    customEl.appendChild(inputEl);
    customEl.appendChild(submitBtn);
    container.appendChild(customEl);

    toolsEl.appendChild(container);
    forceScroll();

    inputEl.focus();
}

function sendQuestionAnswer(questionId, answer, container) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    ws.send(JSON.stringify({
        question_answer: {
            question_id: questionId,
            answer: answer,
        }
    }));

    if (container) {
        container.classList.add('answered');
        const answeredEl = document.createElement('div');
        answeredEl.className = 'ask-user-answered';
        answeredEl.innerHTML = `<i class="ri-check-line"></i> ${escapeHtml(answer)}`;
        container.appendChild(answeredEl);
    }
}

function handleHookEvent(data) {
    if (!currentMessageEl) return;

    const toolsEl = currentMessageEl.querySelector('.message-tools');
    if (!toolsEl) return;

    const hookEl = document.createElement('div');
    hookEl.className = `hook-event ${data.allowed === false ? 'blocked' : ''}`;

    const icon = data.allowed === false ? 'ri-shield-cross-line' : 'ri-shield-check-line';
    const label = data.allowed === false ? 'BLOCKED' : 'HOOK';

    hookEl.innerHTML = `
        <i class="${icon}"></i>
        <span class="hook-label">${label}</span>
        <span class="hook-detail">${escapeHtml(data.hook_name || data.event || '')}${data.tool_name ? ' on ' + escapeHtml(data.tool_name) : ''}</span>
        ${data.reason ? `<span class="hook-reason">${escapeHtml(data.reason)}</span>` : ''}
    `;

    toolsEl.appendChild(hookEl);
    autoScroll();
}

// ---------------------------------------------------------------------------
// Checkpointing: Timeline, Rewind, Fork
// ---------------------------------------------------------------------------

let checkpoints = [];

function handleCheckpointSaved(data) {
    const existing = checkpoints.findIndex(cp => cp.id === data.checkpoint_id);
    const cpData = {
        id: data.checkpoint_id,
        label: data.label,
        turn: data.turn,
        message_count: data.message_count,
        metadata: data.metadata || {},
        created_at: new Date().toISOString(),
    };

    if (existing >= 0) {
        checkpoints[existing] = cpData;
    } else {
        checkpoints.push(cpData);
    }

    if (currentMessageEl) {
        // Store checkpoint on the message element
        currentMessageEl.dataset.checkpointId = data.checkpoint_id;
        currentMessageEl.dataset.checkpointLabel = data.label;

        // Populate the action bar with rewind/fork buttons
        const actionsEl = currentMessageEl.querySelector('.message-actions');
        if (actionsEl) {
            _renderMessageActions(actionsEl, data.checkpoint_id, data.label);
        }
    }

    if (currentOutlineTab === 'timeline') {
        renderTimeline();
    }
}

async function handleCheckpointRewind(data) {
    messagesContainer.innerHTML = '';
    await loadHistory();
    addMessage(
        `Rewound to checkpoint **${escapeHtml(data.label)}** (${data.message_count} messages restored).`,
        'system'
    );

    const idx = checkpoints.findIndex(cp => cp.id === data.checkpoint_id);
    if (idx >= 0) {
        checkpoints = checkpoints.slice(0, idx + 1);
    }

    if (currentOutlineTab === 'timeline') {
        renderTimeline();
    }
}

async function loadCheckpoints() {
    if (!sessionId) {
        renderTimeline();
        return;
    }

    try {
        const response = await fetch(`/checkpoints?session_id=${encodeURIComponent(sessionId)}`);
        if (response.ok) {
            const data = await response.json();
            checkpoints = data.checkpoints || [];
        }
    } catch (e) {
        console.error('Failed to load checkpoints:', e);
    }

    renderTimeline();
}

function renderTimeline() {
    const panel = document.getElementById('timeline-panel');
    if (!panel) return;

    if (checkpoints.length === 0) {
        panel.innerHTML = `
            <div class="timeline-empty">
                <i class="ri-time-line"></i>
                <p>No checkpoints yet</p>
                <span>Checkpoints are saved automatically after each turn.</span>
            </div>
        `;
        return;
    }

    const sorted = [...checkpoints].reverse();

    let html = `<div class="timeline-header">
        <span>${checkpoints.length} checkpoint${checkpoints.length !== 1 ? 's' : ''}</span>
    </div>`;

    html += '<div class="timeline-list">';
    for (const cp of sorted) {
        const time = cp.created_at ? new Date(cp.created_at).toLocaleTimeString() : '';
        const toolName = cp.metadata?.last_tool || '';
        const isLatest = cp === sorted[0];

        html += `
            <div class="timeline-item ${isLatest ? 'latest' : ''}">
                <div class="timeline-dot-col">
                    <div class="timeline-dot ${isLatest ? 'pulse' : ''}"></div>
                    <div class="timeline-line"></div>
                </div>
                <div class="timeline-content">
                    <div class="timeline-label">${escapeHtml(cp.label)}</div>
                    <div class="timeline-meta">
                        <span title="Turn ${cp.turn}"><i class="ri-repeat-line"></i> ${cp.turn}</span>
                        <span title="${cp.message_count} messages"><i class="ri-chat-3-line"></i> ${cp.message_count}</span>
                        ${toolName ? `<span class="timeline-tool" title="Last tool: ${escapeHtml(toolName)}"><i class="ri-tools-line"></i> ${escapeHtml(toolName)}</span>` : ''}
                        ${time ? `<span class="timeline-time"><i class="ri-time-line"></i> ${time}</span>` : ''}
                    </div>
                    <div class="timeline-actions">
                        <button class="timeline-btn rewind" onclick="rewindToCheckpoint('${cp.id}', '${escapeHtml(cp.label)}')" title="Rewind to this point">
                            <i class="ri-arrow-go-back-line"></i> Rewind
                        </button>
                        <button class="timeline-btn fork" onclick="forkFromCheckpoint('${cp.id}')" title="Fork into new session">
                            <i class="ri-git-branch-line"></i> Fork
                        </button>
                    </div>
                </div>
            </div>
        `;
    }
    html += '</div>';

    panel.innerHTML = html;
}

async function rewindToCheckpoint(checkpointId, label) {
    if (!confirm(`Rewind to checkpoint "${label}"? Messages after this point will be discarded.`)) {
        return;
    }

    try {
        const response = await fetch(
            `/checkpoints/${checkpointId}/rewind?session_id=${encodeURIComponent(sessionId)}`,
            { method: 'POST' }
        );

        if (response.ok) {
            const data = await response.json();
            messagesContainer.innerHTML = '';
            await loadHistory();
            addMessage(
                `Rewound to checkpoint **${escapeHtml(data.label)}** (${data.message_count} messages restored).`,
                'system'
            );

            const idx = checkpoints.findIndex(cp => cp.id === checkpointId);
            if (idx >= 0) {
                checkpoints = checkpoints.slice(0, idx + 1);
            }
            renderTimeline();
        } else {
            const err = await response.json();
            alert('Rewind failed: ' + (err.detail || 'Unknown error'));
        }
    } catch (e) {
        alert('Rewind failed: ' + e.message);
    }
}

async function forkFromCheckpoint(checkpointId) {
    try {
        const response = await fetch(
            `/checkpoints/${checkpointId}/fork?session_id=${encodeURIComponent(sessionId)}`,
            { method: 'POST' }
        );

        if (response.ok) {
            const data = await response.json();
            const newUrl = `${window.location.origin}/?session_id=${data.new_session_id}`;
            window.open(newUrl, '_blank');
            addMessage(
                `Forked new session from checkpoint (${data.message_count} messages). Opened in new tab.`,
                'system'
            );
        } else {
            const err = await response.json();
            alert('Fork failed: ' + (err.detail || 'Unknown error'));
        }
    } catch (e) {
        alert('Fork failed: ' + e.message);
    }
}

// ---------------------------------------------------------------------------
// Right-Side Conversation Outline Panel
// ---------------------------------------------------------------------------

let outlinePanelVisible = true;
let currentOutlineTab = 'messages';

function toggleOutlinePanel() {
    const panel = document.getElementById('outline-panel');
    const floatBtn = document.getElementById('outline-float-btn');
    if (!panel) return;

    outlinePanelVisible = !outlinePanelVisible;
    panel.classList.toggle('collapsed', !outlinePanelVisible);
    if (floatBtn) {
        floatBtn.style.display = outlinePanelVisible ? 'none' : 'flex';
    }
}

function switchOutlineTab(tab) {
    currentOutlineTab = tab;
    document.querySelectorAll('.outline-tab').forEach(b => b.classList.remove('active'));
    const activeBtn = document.querySelector(`.outline-tab[data-outline-tab="${tab}"]`);
    if (activeBtn) activeBtn.classList.add('active');

    const outlineList = document.getElementById('outline-list');
    const timelinePanel = document.getElementById('timeline-panel');

    if (tab === 'messages') {
        outlineList.style.display = 'block';
        timelinePanel.style.display = 'none';
    } else {
        outlineList.style.display = 'none';
        timelinePanel.style.display = 'block';
        loadCheckpoints();
    }
}

function updateOutlinePanel() {
    const list = document.getElementById('outline-list');
    if (!list) return;

    const messages = messagesContainer.querySelectorAll('.message');
    if (messages.length === 0) {
        list.innerHTML = '<div class="outline-empty">No messages yet</div>';
        return;
    }

    let html = '';
    messages.forEach((msgEl, idx) => {
        const isUser = msgEl.classList.contains('user');
        const isAssistant = msgEl.classList.contains('assistant');
        const isSystem = msgEl.classList.contains('system');

        let icon, roleClass, text;

        if (isUser) {
            icon = 'ri-user-smile-line';
            roleClass = 'user';
            const contentEl = msgEl.querySelector('.message-content');
            text = contentEl ? contentEl.textContent.trim() : '';
        } else if (isAssistant) {
            icon = 'ri-search-eye-line';
            roleClass = 'assistant';
            // Check if there are tool cards
            const toolCards = msgEl.querySelectorAll('.tool-call');
            const contentEl = msgEl.querySelector('.message-content');
            const contentText = contentEl ? contentEl.textContent.trim() : '';
            if (toolCards.length > 0 && !contentText) {
                // Tool-only message — show first tool name
                const firstTool = toolCards[0];
                const toolName = firstTool.querySelector('.tool-name, .search-provider, .subagent-name');
                text = toolName ? toolName.textContent.trim() : 'Tool call';
                icon = 'ri-tools-line';
                roleClass = 'tool';
            } else {
                text = contentText;
            }
        } else if (isSystem) {
            icon = 'ri-error-warning-fill';
            roleClass = 'system';
            const contentEl = msgEl.querySelector('.message-content');
            text = contentEl ? contentEl.textContent.trim() : 'System';
        } else {
            return;
        }

        // Truncate text
        if (!text) text = '...';
        if (text.length > 50) text = text.substring(0, 50) + '…';

        html += `<div class="outline-item ${roleClass}" data-msg-idx="${idx}" onclick="scrollToMessage(${idx})">
            <span class="outline-item-icon"><i class="${icon}"></i></span>
            <span class="outline-item-text">${escapeHtml(text)}</span>
        </div>`;
    });

    list.innerHTML = html;
}

function scrollToMessage(idx) {
    const messages = messagesContainer.querySelectorAll('.message');
    if (idx >= 0 && idx < messages.length) {
        messages[idx].scrollIntoView({ behavior: 'smooth', block: 'start' });

        // Highlight active item in outline
        const items = document.querySelectorAll('.outline-item');
        items.forEach(item => item.classList.remove('active'));
        const activeItem = document.querySelector(`.outline-item[data-msg-idx="${idx}"]`);
        if (activeItem) activeItem.classList.add('active');
    }
}

// Track active outline item based on scroll position
let outlineScrollTimer = null;
if (messagesContainer) {
    messagesContainer.addEventListener('scroll', () => {
        if (outlineScrollTimer) clearTimeout(outlineScrollTimer);
        outlineScrollTimer = setTimeout(updateActiveOutlineItem, 100);
    });
}

function updateActiveOutlineItem() {
    const messages = messagesContainer.querySelectorAll('.message');
    const items = document.querySelectorAll('.outline-item');
    if (messages.length === 0 || items.length === 0) return;

    const containerRect = messagesContainer.getBoundingClientRect();
    const midY = containerRect.top + containerRect.height * 0.3;

    let closestIdx = 0;
    let closestDist = Infinity;

    messages.forEach((msgEl, idx) => {
        const rect = msgEl.getBoundingClientRect();
        const dist = Math.abs(rect.top - midY);
        if (dist < closestDist) {
            closestDist = dist;
            closestIdx = idx;
        }
    });

    items.forEach(item => item.classList.remove('active'));
    const activeItem = document.querySelector(`.outline-item[data-msg-idx="${closestIdx}"]`);
    if (activeItem) {
        activeItem.classList.add('active');
        // Scroll outline list to show active item
        activeItem.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
}

// ---------------------------------------------------------------------------
// Session List Management
// ---------------------------------------------------------------------------

let sessionsList = [];

async function loadSessionsList() {
    try {
        const resp = await fetch('/sessions');
        if (!resp.ok) return;
        const data = await resp.json();
        sessionsList = data.sessions || [];
        renderSessionsList();
        populateWelcomeSessions();
    } catch (e) {
        console.error('Failed to load sessions:', e);
    }
}

function renderSessionsList() {
    const container = document.getElementById('sessions-list');
    if (!container) return;

    if (sessionsList.length === 0) {
        container.innerHTML = '<div class="sessions-empty"><i class="ri-chat-new-line"></i> No sessions yet</div>';
        return;
    }

    container.innerHTML = sessionsList.map(s => {
        const isActive = s.session_id === sessionId;
        const title = escapeHtml(s.title || 'New Session');
        const time = _timeAgo(s.updated_at);
        const count = s.message_count || 0;
        return `
            <div class="session-item${isActive ? ' session-active' : ''}" data-sid="${s.session_id}" onclick="switchSession('${s.session_id}')">
                <div class="session-item-main">
                    <span class="session-title">${title}</span>
                    <span class="session-meta">${time} · ${count} msgs</span>
                </div>
                <button class="session-delete-btn" onclick="event.stopPropagation(); deleteSession('${s.session_id}')" title="Delete">
                    <i class="ri-delete-bin-line"></i>
                </button>
            </div>
        `;
    }).join('');
}

function _timeAgo(isoStr) {
    if (!isoStr) return '';
    const date = new Date(isoStr);
    const now = new Date();
    const diff = Math.floor((now - date) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
    return date.toLocaleDateString();
}

async function switchSession(sid) {
    if (sid === sessionId) return;

    // Close current WebSocket and reset state
    if (ws) ws.close();
    sessionId = sid;
    localStorage.setItem('sessionId', sid);

    // Reset UI state
    currentMessageEl = null;
    currentToolsEl = null;
    streamedText = '';
    rawStreamedText = '';
    isAgentRunning = false;
    excalidrawCanvasShown = false;
    latestTodos = [];
    resetTasksPanel();
    messagesContainer.innerHTML = '';
    _hideExcalidrawContainer();

    // Reconnect and load
    connectWebSocket();
    await loadSession(sid);
    refreshFiles();
    renderSessionsList();
}

async function createNewSession() {
    // Close current connection
    if (ws) ws.close();
    sessionId = null;
    localStorage.removeItem('sessionId');

    // Reset UI
    currentMessageEl = null;
    currentToolsEl = null;
    streamedText = '';
    rawStreamedText = '';
    isAgentRunning = false;
    excalidrawCanvasShown = false;
    latestTodos = [];
    resetTasksPanel();
    _hideExcalidrawContainer();
    toolStats = { call_count: 0, tools_used: {}, total_duration_ms: 0 };
    configData = null;
    checkpoints = [];

    // Show welcome screen
    messagesContainer.innerHTML = `
        <div class="message system">
            <div class="message-content">
                <div class="welcome-banner">
                    <h3><i class="ri-search-eye-line"></i> DeepResearch</h3>
                    <p>Full-featured autonomous research agent with web search, code execution, subagents, plan mode, and Excalidraw diagrams.</p>
                    <div class="capabilities">
                        <span><i class="ri-search-line"></i> Web Search</span> \u2022
                        <span><i class="ri-links-line"></i> URL Reader</span> \u2022
                        <span><i class="ri-file-text-line"></i> File Ops</span> \u2022
                        <span><i class="ri-terminal-box-line"></i> Shell Execution</span> \u2022
                        <span><i class="ri-group-line"></i> Subagents</span> \u2022
                        <span><i class="ri-draft-line"></i> Plan Mode</span> \u2022
                        <span><i class="ri-artboard-line"></i> Excalidraw</span> \u2022
                        <span><i class="ri-image-line"></i> Images</span> \u2022
                        <span><i class="ri-time-line"></i> Checkpoints</span>
                    </div>
                    <div id="welcome-sessions" class="welcome-sessions"></div>
                </div>
            </div>
        </div>
    `;
    populateWelcomeSessions();

    connectWebSocket();
    refreshFiles();
    renderSessionsList();
}

async function deleteSession(sid) {
    if (!confirm('Delete this session permanently?')) return;
    try {
        await fetch(`/sessions/${encodeURIComponent(sid)}`, { method: 'DELETE' });
        if (sid === sessionId) {
            await createNewSession();
        }
        await loadSessionsList();
    } catch (e) {
        console.error('Failed to delete session:', e);
    }
}

function populateWelcomeSessions() {
    const container = document.getElementById('welcome-sessions');
    if (!container) return;

    const recent = sessionsList.slice(0, 5);
    if (recent.length === 0) {
        container.innerHTML = `
            <div class="welcome-sessions-empty">
                <i class="ri-chat-smile-2-line"></i>
                <span>Start your first research session below</span>
            </div>
        `;
        return;
    }

    container.innerHTML = `
        <div class="welcome-sessions-label">Recent Sessions</div>
        <div class="welcome-sessions-grid">
            ${recent.map(s => {
                const title = escapeHtml(s.title || 'New Session');
                const time = _timeAgo(s.updated_at);
                const count = s.message_count || 0;
                return `
                    <button class="welcome-session-card" onclick="switchSession('${s.session_id}')">
                        <span class="wsc-title">${title}</span>
                        <span class="wsc-meta">${time} · ${count} msgs</span>
                    </button>
                `;
            }).join('')}
        </div>
    `;
}

