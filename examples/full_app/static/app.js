// pydantic-deep Demo Frontend with WebSocket Streaming

// WebSocket connection
let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

// Session management - check URL params first (for forked sessions), then localStorage
let sessionId = new URLSearchParams(window.location.search).get('session_id')
    || localStorage.getItem('sessionId')
    || null;

// State
let currentTab = 'uploads';
let configData = null;
let toolStats = { call_count: 0, tools_used: {}, total_duration_ms: 0 };

// DOM Elements
const messagesContainer = document.getElementById('messages');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');
const fileInput = document.getElementById('file-input');
const uploadArea = document.getElementById('upload-area');
const uploadStatus = document.getElementById('upload-status');
const filesList = document.getElementById('files-list');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    setupResizer();
    connectWebSocket();
    refreshFiles();
    if (sessionId) {
        loadHistory();
    }
});

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        reconnectAttempts = 0;
        updateConnectionStatus(true);
    };

    ws.onclose = () => {
        console.log('WebSocket disconnected');
        updateConnectionStatus(false);

        // Try to reconnect
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

async function loadHistory() {
    if (!sessionId) return;
    try {
        const resp = await fetch(`/history?session_id=${encodeURIComponent(sessionId)}`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data.messages || data.messages.length === 0) return;

        messagesContainer.innerHTML = '';
        for (const msg of data.messages) {
            if (msg.role === 'user') {
                addMessage(msg.content, 'user');
            } else if (msg.role === 'assistant') {
                addMessage(msg.content, 'assistant');
            } else if (msg.role === 'tool_call') {
                addMessage(`**${msg.tool_name}** called`, 'system');
            }
        }
    } catch (e) {
        console.error('Failed to load history:', e);
    }
}

function updateConnectionStatus(connected) {
    sendBtn.disabled = !connected;
}

// Current message state for streaming
let currentMessageEl = null;
let currentToolsEl = null;
let streamedText = '';  // Accumulated streamed text
let isAgentRunning = false;  // Track if agent is currently generating
let rawStreamedText = '';  // Raw text for copy button

function handleWebSocketMessage(event) {
    const data = JSON.parse(event.data);

    switch (data.type) {
        case 'session_created':
            sessionId = data.session_id;
            localStorage.setItem('sessionId', sessionId);
            console.log('New session created:', sessionId);
            break;

        case 'start':
            currentMessageEl = createMessageContainer('assistant');
            currentToolsEl = null;
            streamedText = '';
            rawStreamedText = '';
            resetTasksPanel();
            setAgentRunning(true);
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
            }
            break;

        case 'done':
            finishMessage();
            refreshFiles();
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
    }
}

function createMessageContainer(type) {
    const id = 'msg-' + Date.now();
    const messageEl = document.createElement('div');
    messageEl.className = `message ${type}`;
    messageEl.id = id;

    const labelMap = {
        'user': {text: 'You', icon: 'icon-user', i: 'ri-user-smile-line'},
        'assistant': {text: 'Deep Agent', icon: 'icon-ai', i: 'ri-robot-2-fill'},
        'system': {text: 'System', icon: 'icon-system', i: 'ri-error-warning-fill'}
    };

    const info = labelMap[type] || labelMap['system'];

    messageEl.innerHTML = `
        <div class="message-header ${info.icon}">
            <i class="${info.i}"></i> <span>${info.text}</span>
            <button class="msg-copy-btn" onclick="copyMessage(this)" title="Copy"><i class="ri-file-copy-line"></i></button>
        </div>
        <div class="message-tools"></div>
        <div class="message-content"></div>
    `;

    messagesContainer.appendChild(messageEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

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

    const toolEl = document.createElement('div');
    toolEl.className = 'tool-call streaming';
    toolEl.dataset.toolCallId = toolCallId || '';

    toolEl.innerHTML = `
        <div class="tool-header">
            <span class="tool-name">./${escapeHtml(toolName)}</span>
            <span class="tool-status streaming">STREAMING</span>
        </div>
        <div class="tool-args streaming-args"><code></code></div>
        <div class="tool-output"></div>
    `;

    toolsEl.appendChild(toolEl);
    currentToolsEl = toolEl;
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function appendToolArgsDelta(toolName, argsDelta) {
    if (!currentToolsEl) return;

    streamingToolArgs += argsDelta;

    const argsEl = currentToolsEl.querySelector('.tool-args code');
    if (argsEl) {
        argsEl.textContent = streamingToolArgs;
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

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
        : '<span class="subagent-status done"><i class="ri-checkbox-circle-fill"></i> Done</span>';

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
        : '<span class="subagent-status done"><i class="ri-checkbox-circle-fill"></i> Done</span>';

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

function addToolEvent(toolName, args) {
    if (!currentMessageEl) return;

    const toolsEl = currentMessageEl.querySelector('.message-tools');
    if (!toolsEl) return;

    // Detect subagent delegation or agent factory call
    const agentInfo = _isSubagentCall(toolName, args);
    const factoryInfo = !agentInfo ? _isAgentFactoryCall(toolName, args) : null;
    const isSpecial = agentInfo || factoryInfo;

    const existingStreamingTool = toolsEl.querySelector('.tool-call.streaming');
    if (existingStreamingTool) {
        existingStreamingTool.classList.remove('streaming');

        if (agentInfo) {
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

    if (agentInfo) {
        toolEl.className = 'tool-call subagent-delegation';
        toolEl.innerHTML = _renderSubagentCard(agentInfo, 'running');
    } else if (factoryInfo) {
        toolEl.className = 'tool-call subagent-delegation';
        toolEl.innerHTML = _renderFactoryCard(factoryInfo, 'running');
    } else {
        toolEl.className = 'tool-call';
        toolEl.innerHTML = `
            <div class="tool-header">
                <span class="tool-name">./${escapeHtml(toolName)}</span>
                <span class="tool-status running">RUNNING...</span>
            </div>
            <div class="tool-args">${formatToolArgs(args)}</div>
            <div class="tool-output"></div>
        `;
    }

    toolsEl.appendChild(toolEl);
    currentToolsEl = toolEl;
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
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

    const isSubagent = currentToolsEl.classList.contains('subagent-delegation');
    const outputEl = currentToolsEl.querySelector('.tool-output');

    if (isSubagent) {
        // Update status to done
        const statusEl = currentToolsEl.querySelector('.subagent-status');
        if (statusEl) {
            statusEl.className = 'subagent-status done';
            statusEl.innerHTML = '<i class="ri-checkbox-circle-fill"></i> Done';
        }
        // Render output as formatted markdown in a result card
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
            statusEl.textContent = 'done';
        }
    }
}

function appendTextChunk(chunk) {
    if (!currentMessageEl) return;

    streamedText += chunk;
    rawStreamedText += chunk;

    const contentEl = currentMessageEl.querySelector('.message-content');
    if (contentEl) {
        contentEl.innerHTML = formatMessage(streamedText);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

function appendThinkingChunk(chunk) {
    if (!currentMessageEl) return;

    let thinkingEl = currentMessageEl.querySelector('.message-thinking');
    if (!thinkingEl) {
        thinkingEl = document.createElement('div');
        thinkingEl.className = 'message-thinking';
        thinkingEl.innerHTML = '<span class="thinking-label"><i class="ri-brain-line"></i> Thinking...</span><div class="thinking-content"></div>';
        const contentEl = currentMessageEl.querySelector('.message-content');
        currentMessageEl.insertBefore(thinkingEl, contentEl);
    }

    const thinkingContent = thinkingEl.querySelector('.thinking-content');
    if (thinkingContent) {
        thinkingContent.textContent += chunk;
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
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
            el.textContent = 'done';
        });
    }

    currentMessageEl = null;
    currentToolsEl = null;
    setAgentRunning(false);
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

// Pending approval requests
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
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
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

    uploadArea.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', handleFileSelect);

    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    });

    uploadArea.addEventListener('dragleave', () => {
        uploadArea.classList.remove('dragover');
    });

    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            uploadFile(files[0]);
        }
    });

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTab = btn.dataset.tab;

            const configPanel = document.getElementById('config-panel');
            const timelinePanel = document.getElementById('timeline-panel');
            if (currentTab === 'config') {
                filesList.style.display = 'none';
                timelinePanel.style.display = 'none';
                configPanel.style.display = 'block';
                renderConfigPanel();
            } else if (currentTab === 'timeline') {
                filesList.style.display = 'none';
                configPanel.style.display = 'none';
                timelinePanel.style.display = 'block';
                loadCheckpoints();
            } else {
                filesList.style.display = 'block';
                configPanel.style.display = 'none';
                timelinePanel.style.display = 'none';
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

    // Read attachments as base64 locally (fast, no HTTP upload needed)
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
            // result is "data:image/png;base64,xxxx..." — extract just the base64 part
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

function addAttachment(file) {
    // Prevent duplicates
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
        'assistant': {text: 'Agent', i: 'ri-robot-2-fill'},
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
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

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

        // Check if second row is separator
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

    // Line breaks (but not inside block elements we just created)
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
    uploadStatus.innerHTML = `<i class="ri-loader-4-line spin"></i> Uploading ${file.name}...`;
    uploadStatus.className = '';

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
            uploadStatus.innerHTML = `<i class="ri-check-line"></i> Uploaded: ${data.filename}`;
            uploadStatus.className = 'success';
            refreshFiles();
            addMessage(`File uploaded: ${data.filename} (${formatBytes(data.size)})`, 'system');
        } else {
            uploadStatus.textContent = `Error: ${data.detail}`;
            uploadStatus.className = 'error';
        }
    } catch (error) {
        uploadStatus.textContent = `Error: ${error.message}`;
        uploadStatus.className = 'error';
    }

    fileInput.value = '';
    setTimeout(() => {
        uploadStatus.textContent = '';
        uploadStatus.className = '';
    }, 3000);
}

const expandedFolders = new Set();

async function refreshFiles() {
    if (!sessionId) return;

    try {
        const response = await fetch(`/files?session_id=${encodeURIComponent(sessionId)}`);
        if (!response.ok) return;
        const data = await response.json();

        const files = currentTab === 'uploads' ? data.uploads : data.workspace;

        if (files.length === 0) {
            filesList.innerHTML = '<p class="empty-state">No files yet</p>';
            return;
        }

        if (currentTab === 'uploads') {
            filesList.innerHTML = files.map(file => {
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
            return;
        }

        const tree = buildFileTree(files);
        filesList.innerHTML = renderFileTree(tree, 0);

    } catch (error) {
        filesList.innerHTML = '<p class="empty-state">Error loading files</p>';
    }
}

/**
 * Build a nested tree structure from flat file paths
 */
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

/**
 * Render file tree as HTML
 */
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

/**
 * Toggle folder expanded/collapsed state
 */
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

    // Header
    label.textContent = allDone ? 'Tasks Complete' : 'Task Progress';
    badge.textContent = `${completed}/${total}`;
    panel.classList.toggle('all-done', allDone);

    // Progress bar
    fill.style.width = pct + '%';

    // Timer
    if (!allDone && tasksStartTime === 0) {
        tasksStartTime = Date.now();
        _startTasksTimer();
    }
    if (allDone) _stopTasksTimer();
    elapsed.style.display = (!allDone && tasksStartTime) ? 'flex' : 'none';

    // Collapsed preview
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

    // Expanded list
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

async function resetAgent() {
    if (!confirm('Are you sure you want to reset the agent? This will clear all files and history.')) {
        return;
    }

    try {
        if (sessionId) {
            await fetch(`/reset?session_id=${encodeURIComponent(sessionId)}`, {method: 'POST'});
        }
        sessionId = null;
        localStorage.removeItem('sessionId');
        toolStats = { call_count: 0, tools_used: {}, total_duration_ms: 0 };
        configData = null;
        checkpoints = [];
        resetTasksPanel();

        messagesContainer.innerHTML = '';
        addMessage(`
            <p><strong>Agent Reset!</strong> Ready to start fresh.</p>
        `, 'system');

        refreshFiles();

        if (ws) ws.close();
        connectWebSocket();
    } catch (error) {
        alert('Error resetting agent: ' + error.message);
    }
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

// File types that support live preview
const PREVIEWABLE_EXTENSIONS = ['html', 'htm', 'svg'];

async function openFilePreview(filePath) {
    if (!sessionId) return;

    try {
        // Prepare UI
        const filename = filePath.split('/').pop();
        previewFilename.textContent = filename;
        const iconClass = getFileIconClass(filename);
        previewIcon.innerHTML = `<i class="${iconClass}"></i>`;

        filePreviewPanel.classList.remove('hidden');
        previewContainer.innerHTML = '<div style="padding: 20px; color: var(--text-muted);">Loading...</div>';

        // Check if file is previewable and show/hide toggle
        const ext = filename.split('.').pop().toLowerCase();
        if (PREVIEWABLE_EXTENSIONS.includes(ext)) {
            previewModeToggle.classList.add('visible');
        } else {
            previewModeToggle.classList.remove('visible');
            currentPreviewMode = 'code'; // Reset to code mode for non-previewable
        }

        // Reset toggle state
        updatePreviewModeButtons();

        // PDF: skip text fetch, render embed directly
        const ext2 = filename.split('.').pop().toLowerCase();
        if (ext2 === 'pdf') {
            currentPreviewPath = filePath;
            currentPreviewContent = '';
            previewContainer.innerHTML = `
                <embed class="embed-container" src="/files/binary/${encodeURIComponent(filePath)}?session_id=${encodeURIComponent(sessionId)}" type="application/pdf">
            `;
            return;
        }

        // Fetch text content
        const response = await fetch(`/files/content/${encodeURIComponent(filePath)}?session_id=${encodeURIComponent(sessionId)}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to load file');
        }

        const data = await response.json();
        currentPreviewPath = filePath;
        // Strip line numbers from content (backend returns cat -n format)
        currentPreviewContent = stripLineNumbers(data.content);

        renderPreview(filename, currentPreviewContent);

    } catch (error) {
        console.error('Error loading file:', error);
        previewContainer.innerHTML = `<div style="padding: 20px; color: var(--error);">Error loading file: ${escapeHtml(error.message)}</div>`;
    }
}

/**
 * Set preview mode (code or preview)
 */
function setPreviewMode(mode) {
    currentPreviewMode = mode;
    updatePreviewModeButtons();

    if (currentPreviewPath && currentPreviewContent) {
        const filename = currentPreviewPath.split('/').pop();
        renderPreview(filename, currentPreviewContent);
    }
}

/**
 * Update toggle button states
 */
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

    // 1. Live Preview mode for HTML/SVG
    if (currentPreviewMode === 'preview' && PREVIEWABLE_EXTENSIONS.includes(ext)) {
        renderLivePreview(content, ext);
        return;
    }

    // 2. Image Preview (binary)
    if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'ico'].includes(ext)) {
        const imageUrl = `/files/binary/${encodeURIComponent(currentPreviewPath)}?session_id=${encodeURIComponent(sessionId)}`;
        previewContainer.innerHTML = `
            <div style="display:flex; justify-content:center; align-items:center; height:100%; padding:20px; background:#1a1a1a;">
                <img src="${imageUrl}" alt="${escapeHtml(filename)}" style="max-width:100%; max-height:100%; object-fit:contain; border-radius:4px;">
            </div>
        `;
        return;
    }

    // 3. SVG - can render directly (text-based)
    if (ext === 'svg' && currentPreviewMode === 'code') {
        // Show code, preview handled above
    }

    // 4. CSV Reader
    if (ext === 'csv') {
        const tableHtml = parseCSVtoTable(content);
        previewContainer.innerHTML = `<div class="csv-container">${tableHtml}</div>`;
        return;
    }

    // 5. PDF Reader (Simple Embed) — use binary endpoint for full path support
    if (ext === 'pdf') {
        previewContainer.innerHTML = `
            <embed class="embed-container" src="/files/binary/${encodeURIComponent(currentPreviewPath)}?session_id=${sessionId}" type="application/pdf">
        `;
        return;
    }

    // 6. Code / Text (PrismJS)
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
    code.textContent = content; // Safely sets text

    pre.appendChild(code);
    previewContainer.innerHTML = ''; // clear
    previewContainer.appendChild(pre);

    // Trigger highlighting
    if (window.Prism) {
        Prism.highlightElement(code);
    }
}

/**
 * Render live preview of HTML/SVG in an iframe
 * Uses /preview endpoint to serve files directly from container,
 * allowing relative CSS/JS/images to resolve naturally.
 */
function renderLivePreview(content, ext) {
    const iframe = document.createElement('iframe');
    iframe.className = 'live-preview-frame';
    iframe.sandbox = 'allow-scripts allow-same-origin'; // Security: sandboxed iframe

    previewContainer.innerHTML = '';
    previewContainer.appendChild(iframe);

    if (ext === 'svg') {
        // SVG: write directly with wrapper (no external resources needed)
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
        // HTML: load via /preview endpoint so relative paths work
        // e.g., /preview/{session_id}/workspace/index.html
        // When HTML requests style.css, browser resolves to /preview/{session_id}/workspace/style.css
        const previewUrl = `/preview/${sessionId}${currentPreviewPath}`;
        iframe.src = previewUrl;
    }
}

/**
 * Strip line numbers from cat -n formatted content
 * Format is: "     1\tline content\n     2\tnext line\n"
 */
function stripLineNumbers(content) {
    if (!content) return content;

    // Split into lines, strip line number prefix from each, rejoin
    return content.split('\n').map(line => {
        // Match: optional spaces, digits, tab, then the actual content
        const match = line.match(/^\s*\d+\t(.*)$/);
        return match ? match[1] : line;
    }).join('\n');
}

/**
 * Parse CSV line respecting quoted values (handles commas inside quotes)
 */
function parseCSVLine(line) {
    const result = [];
    let current = '';
    let inQuotes = false;

    for (let i = 0; i < line.length; i++) {
        const char = line[i];
        const nextChar = line[i + 1];

        if (char === '"') {
            if (inQuotes && nextChar === '"') {
                // Escaped quote ""
                current += '"';
                i++; // Skip next quote
            } else {
                // Toggle quote mode
                inQuotes = !inQuotes;
            }
        } else if (char === ',' && !inQuotes) {
            // End of field
            result.push(current.trim());
            current = '';
        } else {
            current += char;
        }
    }

    // Don't forget last field
    result.push(current.trim());
    return result;
}

function parseCSVtoTable(csvText) {
    const lines = csvText.trim().split(/\r?\n/);
    if (lines.length === 0) return '<p>Empty CSV</p>';

    // Parse headers
    const headers = parseCSVLine(lines[0]);
    const numCols = headers.length;

    let html = '<table class="csv-table"><thead><tr>';
    html += `<th class="row-num">#</th>`; // Row number column
    headers.forEach(h => html += `<th>${escapeHtml(h)}</th>`);
    html += '</tr></thead><tbody>';

    for (let i = 1; i < lines.length; i++) {
        if (!lines[i].trim()) continue; // Skip empty lines

        const row = parseCSVLine(lines[i]);

        html += '<tr>';
        html += `<td class="row-num">${i}</td>`; // Row number
        for (let j = 0; j < numCols; j++) {
            const cell = row[j] || '';
            // Truncate very long cells for display
            const displayCell = cell.length > 100 ? cell.substring(0, 100) + '...' : cell;
            html += `<td title="${escapeHtml(cell)}">${escapeHtml(displayCell)}</td>`;
        }
        html += '</tr>';
    }
    html += '</tbody></table>';

    // Add row count info
    const rowCount = lines.length - 1;
    html = `<div class="csv-info">${rowCount} rows × ${numCols} columns</div>` + html;

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

// --- Config Panel ---

async function renderConfigPanel() {
    const configPanel = document.getElementById('config-panel');
    if (!configPanel) return;

    // Fetch config from backend
    if (!configData) {
        try {
            const response = await fetch('/config');
            if (response.ok) {
                const raw = await response.json();
                configData = raw.features || raw;
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
                <span class="config-value">${slidingWindow.trigger ? slidingWindow.trigger + ' → keep ' + slidingWindow.keep : 'disabled'}</span>
            </div>
        </div>
    `;

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
    // Update tool stats
    if (data.total_calls !== undefined) {
        toolStats.call_count = data.total_calls;
    }
    if (data.total_duration_ms !== undefined) {
        toolStats.total_duration_ms = data.total_duration_ms;
    }
    if (data.tools_breakdown) {
        toolStats.tools_used = data.tools_breakdown;
    }

    // Update config panel if visible
    updateToolStatsDisplay();

    // Show subtle inline badge after tool calls
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
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    // Focus the custom input
    inputEl.focus();
}

function sendQuestionAnswer(questionId, answer, container) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;

    // Send answer to backend
    ws.send(JSON.stringify({
        question_answer: {
            question_id: questionId,
            answer: answer,
        }
    }));

    // Disable the question UI and show selection
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
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// ---------------------------------------------------------------------------
// Checkpointing: Timeline, Rewind, Fork
// ---------------------------------------------------------------------------

let checkpoints = [];

function handleCheckpointSaved(data) {
    // Update local checkpoints list
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

    // Add inline checkpoint badge after tool output in chat
    if (currentMessageEl) {
        const toolsEl = currentMessageEl.querySelector('.message-tools');
        if (toolsEl) {
            const badge = document.createElement('div');
            badge.className = 'checkpoint-badge';
            const toolName = data.metadata?.last_tool || '';
            badge.innerHTML = `<i class="ri-bookmark-line"></i> ${escapeHtml(data.label)}`;
            badge.title = `Checkpoint: ${data.label} (turn ${data.turn}, ${data.message_count} messages)`;
            toolsEl.appendChild(badge);
        }
    }

    // Refresh timeline panel if visible
    if (currentTab === 'timeline') {
        renderTimeline();
    }
}

async function handleCheckpointRewind(data) {
    // Clear chat, load restored history, then show system message
    messagesContainer.innerHTML = '';
    await loadHistory();
    addMessage(
        `Rewound to checkpoint **${escapeHtml(data.label)}** (${data.message_count} messages restored).`,
        'system'
    );

    // Trim checkpoints list to remove those after the rewind point
    const idx = checkpoints.findIndex(cp => cp.id === data.checkpoint_id);
    if (idx >= 0) {
        checkpoints = checkpoints.slice(0, idx + 1);
    }

    // Refresh timeline
    if (currentTab === 'timeline') {
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
                <span>Checkpoints are saved automatically after each tool call.</span>
            </div>
        `;
        return;
    }

    // Show most recent first
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

            // Trim local checkpoints
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
            // Open new session in a new tab
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