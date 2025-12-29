// pydantic-deep Demo Frontend with WebSocket Streaming

// WebSocket connection
let ws = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 5;

// Session management
let sessionId = localStorage.getItem('sessionId') || null;

// State
let currentTab = 'uploads';

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

function updateConnectionStatus(connected) {
    sendBtn.disabled = !connected;
}

// Current message state for streaming
let currentMessageEl = null;
let currentToolsEl = null;
let streamedText = '';  // Accumulated streamed text

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
        </div>
        <div class="message-tools"></div>
        <div class="message-content"></div>
    `;

    messagesContainer.appendChild(messageEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return messageEl;
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

function addToolEvent(toolName, args) {
    if (!currentMessageEl) return;

    const toolsEl = currentMessageEl.querySelector('.message-tools');
    if (!toolsEl) return;

    const existingStreamingTool = toolsEl.querySelector('.tool-call.streaming');
    if (existingStreamingTool) {
        existingStreamingTool.classList.remove('streaming');
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
        currentToolsEl = existingStreamingTool;
        return;
    }

    const toolEl = document.createElement('div');
    toolEl.className = 'tool-call';
    toolEl.innerHTML = `
        <div class="tool-header">
            <span class="tool-name">./${escapeHtml(toolName)}</span>
            <span class="tool-status running">RUNNING...</span>
        </div>
        <div class="tool-args">${formatToolArgs(args)}</div>
        <div class="tool-output"></div>
    `;

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

    const outputEl = currentToolsEl.querySelector('.tool-output');
    const statusEl = currentToolsEl.querySelector('.tool-status');

    if (outputEl) {
        outputEl.innerHTML = `<pre>${escapeHtml(output)}</pre>`;
    }

    if (statusEl) {
        statusEl.className = 'tool-status done';
        statusEl.textContent = 'done';
    }
}

function appendTextChunk(chunk) {
    if (!currentMessageEl) return;

    streamedText += chunk;

    const contentEl = currentMessageEl.querySelector('.message-content');
    if (contentEl) {
        // Use formatMessage to render markdown and citations in real-time
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

        const toolStatuses = currentMessageEl.querySelectorAll('.tool-status.running');
        toolStatuses.forEach(el => {
            el.className = 'tool-status done';
            el.textContent = 'done';
        });
    }

    currentMessageEl = null;
    currentToolsEl = null;
    sendBtn.disabled = false;
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
            refreshFiles();
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

function sendMessage() {
    const message = messageInput.value.trim();
    if (!message) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        addMessage('Not connected to server. Reconnecting...', 'system');
        connectWebSocket();
        return;
    }

    messageInput.value = '';
    messageInput.style.height = 'auto';

    addMessage(message, 'user');
    sendBtn.disabled = true;

    const payload = {message};
    if (sessionId) {
        payload.session_id = sessionId;
    }
    ws.send(JSON.stringify(payload));
}

function sendQuickMessage(message) {
    messageInput.value = message;
    sendMessage();
}

function addMessage(content, type) {
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

    messageEl.innerHTML = `
        <span class="message-header"><i class="${info.i}"></i> ${info.text}</span>
        <div class="message-content">${formatMessage(content)}</div>
    `;

    messagesContainer.appendChild(messageEl);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    return id;
}

function formatMessage(content) {
    if (!content) return '';

    // 1) Extract citations first (before escaping) so spaces/special chars are preserved
    const citations = [];
    const withPlaceholders = content.replace(/\[\[citation:([^|\]]+)\|([\s\S]*?)\]\]/g, (match, path, quote) => {
        const idx = citations.length;
        citations.push({
            path: path.trim(),
            quote: quote.trim(),
        });
        return `__CITATION_${idx}__`;
    });

    // 2) Escape the remaining text for safety
    let html = escapeHtml(withPlaceholders);

    // 3) Apply basic formatting
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');

    // 4) Newlines
    html = html.replace(/\n/g, '<br>');

    // 5) Linkify file paths (safe because citations are placeholders)
    html = linkifyFilePaths(html);

    // 6) Restore citations with safe HTML
    citations.forEach((c, index) => {
        const safePath = c.path;
        const safeQuote = c.quote.replace(/'/g, "\\'");
        const isHttp = /^https?:\/\//i.test(safePath);

        const citationHtml = isHttp
            ? `<a class="citation-link" href="${escapeHtml(safePath)}" target="_blank" rel="noreferrer noopener" title="Source: ${escapeHtml(safePath)}"><i class="ri-links-line"></i> ${escapeHtml(c.quote)}</a>`
            : `<span class="citation-link" onclick="openFilePreview('${safePath}', '${safeQuote}')" title="Source: ${escapeHtml(safePath)}"><i class="ri-links-line"></i> ${escapeHtml(c.quote)}</span>`;

        html = html.replace(`__CITATION_${index}__`, citationHtml);
    });

    return html;
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

let latestTodos = [];

function handleTodosUpdate(todos) {
    latestTodos = todos || [];
    if (currentMessageEl) {
        renderTodosWidget(currentMessageEl, latestTodos);
    }
}

function renderTodosWidget(messageEl, todos) {
    let todosEl = messageEl.querySelector('.message-todos');
    if (!todosEl) {
        todosEl = document.createElement('div');
        todosEl.className = 'message-todos';
        messageEl.appendChild(todosEl);
    }

    if (!todos || todos.length === 0) {
        todosEl.style.display = 'none';
        return;
    }

    todosEl.style.display = 'block';

    const completed = todos.filter(t => t.status === 'completed').length;
    const inProgress = todos.filter(t => t.status === 'in_progress').length;
    const total = todos.length;

    let html = `<div class="todos-header"><i class="ri-list-check-2"></i> Task Progress <span class="todos-count">${completed}/${total}</span></div>`;
    html += '<div class="todos-items">';

    for (const todo of todos) {
        const status = todo.status || 'pending';
        const iconMap = {
            'completed': 'ri-checkbox-circle-fill',
            'in_progress': 'ri-loader-4-line',
            'pending': 'ri-checkbox-blank-circle-line'
        };
        const icon = iconMap[status] || iconMap['pending'];
        const text = status === 'in_progress' && todo.activeForm ? todo.activeForm : todo.content;
        html += `<div class="todo-item-inline ${status}"><i class="${icon}"></i><span>${escapeHtml(text)}</span></div>`;
    }

    html += '</div>';
    todosEl.innerHTML = html;
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
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

async function openFilePreview(filePath, quote = null) {
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

        // Fetch
        const response = await fetch(`/files/content/${encodeURIComponent(filePath)}?session_id=${encodeURIComponent(sessionId)}`);
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to load file');
        }

        const data = await response.json();
        currentPreviewPath = filePath;
        // Strip line numbers from content (backend returns cat -n format)
        currentPreviewContent = stripLineNumbers(data.content);

        renderPreview(filename, currentPreviewContent, quote);

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

function renderPreview(filename, content, quote = null) {
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

    // 5. PDF Reader (Simple Embed)
    if (ext === 'pdf') {
        previewContainer.innerHTML = `
            <embed class="embed-container" src="/files/download/${encodeURIComponent(currentPreviewPath)}?session_id=${sessionId}" type="application/pdf">
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

    if (quote) {
        highlightQuoteInPreview(quote);
    }
}

function highlightQuoteInPreview(quote) {
    // Simple implementation using window.find to scroll to text
    // Note: This searches the whole page, but since we just opened the preview,
    // it's likely the user wants to see it there.
    // We can try to scope it by focusing the container first.

    setTimeout(() => {
        // Clear previous selection
        if (window.getSelection) {
            window.getSelection().removeAllRanges();
        }

        // Try to find the text
        // window.find(aString, aCaseSensitive, aBackwards, aWrapAround, aWholeWord, aSearchInFrames, aShowDialog);
        const found = window.find(quote, false, false, true, false, true, false);

        if (found) {
            // Ensure the selection is within the preview container
            const selection = window.getSelection();
            if (selection.rangeCount > 0) {
                const range = selection.getRangeAt(0);
                const container = document.getElementById('preview-container');
                if (!container.contains(range.commonAncestorContainer)) {
                    // Found outside preview (e.g. in chat), try finding again
                    // This is tricky with window.find.
                    // Let's just hope it finds the one in preview because it's later in DOM?
                    // Or we can try to scroll the preview container to the text.
                } else {
                    // Scroll into view
                    const element = range.startContainer.parentElement;
                    if (element) {
                        element.scrollIntoView({behavior: 'smooth', block: 'center'});
                        // Add a temporary highlight class
                        // element.classList.add('highlight-flash');
                    }
                }
            }
        }
    }, 500);
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
    // Match paths but capture the preceding character to check if it's a quote or parenthesis
    // This prevents replacing paths inside HTML attributes or function calls
    const pathPattern = /([^\w/'"]|^)(\/(?:workspace|uploads|app|home|tmp|var|etc)\/[^\s<>"'`,;()[\]{}]+\.[a-zA-Z0-9]+)/g;

    return html.replace(pathPattern, (match, prefix, path) => {
        // If preceded by quote or opening parenthesis, it's likely inside code or attribute -> skip
        if (prefix === "'" || prefix === '"' || prefix === '(') {
            return match;
        }

        const cleanPath = path.replace(/[.,;:!?)]+$/, '');
        const trailing = path.slice(cleanPath.length);
        return `${prefix}<span class="file-link" onclick="openFilePreview('${cleanPath}')" title="Click to preview">${escapeHtml(cleanPath)}</span>${trailing}`;
    });
}
