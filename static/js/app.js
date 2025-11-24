const socket = io();
const progressSocket = io('/progress'); // Separate socket for progress updates

const companyInput = document.getElementById('companyInput');
const sendBtn = document.getElementById('sendBtn');
const chatMessages = document.getElementById('chatMessages');
const welcomeScreen = document.getElementById('welcomeScreen');
const dashboard = document.getElementById('dashboard');
const plansList = document.getElementById('plansList');
const progressScreen = document.getElementById('progressScreen');
// const viewPlansBtn = document.getElementById('viewPlansBtn'); // Removed from HTML
const newResearchBtn = document.getElementById('newResearchBtn');
const backToDashboardBtn = document.getElementById('backToDashboard');
const newChatBtn = document.getElementById('newChatBtn');
const chatHistory = document.getElementById('chatHistory');

let currentCompany = null;
let currentAccountPlan = null;
let researchInProgress = false;
let progressStartTime = null;
let progressInterval = null;
let progressInitialized = false;
let researchDone = false;  // Track if research has been completed
let selectedAgents = ['overview', 'value', 'goals', 'domain', 'synergy']; // Default all selected
let pendingCompanyName = null; // Store company name for agent selection modal
let sourcesExpanded = false; // Track expansion state for live sources
let currentChatId = null; // Track current active chat session
let chats = []; // Store all chat sessions
let chatHistoryLoadTimer = null; // Debounce timer for loading chat history

const DEFAULT_FAVICON_DATA_URI = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%238b5cf6"%3E%3Ccircle cx="12" cy="12" r="10"/%3E%3Cpath fill="white" d="M12 6a6 6 0 0 0-6 6h2a4 4 0 0 1 4-4V6z"/%3E%3C/svg%3E';

function registerProgressChannel(retryCount = 0) {
    if (!progressSocket || progressSocket.disconnected) {
        return;
    }

    if (socket && socket.id) {
        progressSocket.emit('register_session', { main_sid: socket.id });
    } else if (retryCount < 20) {
        setTimeout(() => registerProgressChannel(retryCount + 1), 100);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    setupResizableSidebar();
    showWelcomeScreen();
    loadChatHistory(); // Load chat history on page load
});

function setupEventListeners() {
    sendBtn.addEventListener('click', handleSendMessage);
    companyInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !researchInProgress) {
            handleSendMessage();
        }
    });

    // viewPlansBtn removed from HTML
    // if (viewPlansBtn) viewPlansBtn.addEventListener('click', showPlansList);
    if (newResearchBtn) newResearchBtn.addEventListener('click', showWelcomeScreen);
    if (backToDashboardBtn) backToDashboardBtn.addEventListener('click', showDashboard);
    if (newChatBtn) newChatBtn.addEventListener('click', handleCreateNewChat);

    socket.on('connect', () => {
        console.log('Connected to server, socket ID:', socket.id);
        registerProgressChannel();
    });
    
    progressSocket.on('connect', () => {
        console.log('Connected to progress namespace, socket ID:', progressSocket.id);
        registerProgressChannel();
    });
    
    progressSocket.on('progress_registered', (data) => {
        console.log('Progress channel registered for room:', data?.room);
    });
    
    socket.on('connection_response', handleConnectionResponse);
    socket.on('chat_response', handleChatResponse);
    socket.on('chat_typing', handleTypingIndicator);
    socket.on('session_reset', handleSessionReset);
    socket.on('chat_name_updated', handleChatNameUpdated);
    socket.on('research_started', handleResearchStarted);
    socket.on('research_complete', handleResearchComplete);
    socket.on('research_error', handleResearchError);
    socket.on('sources_data', handleSourcesData);
    socket.on('error', handleError);
    
    // Progress events on separate namespace
    progressSocket.on('progress_update', handleProgressUpdate);
    progressSocket.on('scraping_progress', handleScrapingProgress);
    progressSocket.on('error', handleError); // Also listen for errors on progress namespace

    // Agent selection modal handlers
    setupAgentSelectionModal();

    // Regenerate button handlers
    setupRegenerateButtons();
    
    // Section regenerate modal handlers
    setupSectionRegenerateModal();

    // Global regenerate modal handlers
    setupGlobalRegenerateModal();
    
    // Setup dashboard tabs
    setupDashboardTabs();

    // Live sources controls
    setupLiveSourcesControls();
}

function setupResizableSidebar() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    const MIN_WIDTH = 250;
    const MAX_WIDTH = 600;
    const RESIZE_HANDLE_WIDTH = 10;

    const resizeHandle = document.createElement('div');
    resizeHandle.style.position = 'absolute';
    resizeHandle.style.top = '0';
    resizeHandle.style.right = '-5px';
    resizeHandle.style.width = `${RESIZE_HANDLE_WIDTH}px`;
    resizeHandle.style.height = '100%';
    resizeHandle.style.cursor = 'col-resize';
    resizeHandle.style.zIndex = '1000';
    sidebar.appendChild(resizeHandle);

    resizeHandle.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = sidebar.getBoundingClientRect().width;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;

        const delta = e.clientX - startX;
        const newWidth = Math.min(Math.max(startWidth + delta, MIN_WIDTH), MAX_WIDTH);
        sidebar.style.width = `${newWidth}px`;
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
}

function setupLiveSourcesControls() {
    const expandBtn = document.getElementById('sourcesExpandBtn');
    if (expandBtn) {
        expandBtn.addEventListener('click', toggleSourcesExpand);
    }
}

function toggleSourcesExpand() {
    const container = document.getElementById('sourcesProgress');
    const tableContainer = document.getElementById('sourcesProgressTableContainer');
    const expandBtn = document.getElementById('sourcesExpandBtn');
    const tbody = document.getElementById('sourcesProgressTableBody');
    if (!container || !tableContainer || !expandBtn) return;

    sourcesExpanded = !sourcesExpanded;
    container.classList.toggle('expanded', sourcesExpanded);
    expandBtn.setAttribute('aria-expanded', String(sourcesExpanded));
    const label = expandBtn.querySelector('.sources-expand-label');
    if (label) {
        label.textContent = sourcesExpanded ? 'Collapse' : 'Expand';
    }

    if (!sourcesExpanded && tbody) {
        tbody.scrollTop = 0;
    }
}

function handleSendMessage() {
    const message = companyInput.value.trim();
    if (!message || researchInProgress) return;

    // Add user message to chat
    addChatMessage(message, 'user');
    
    // Clear input
    companyInput.value = '';

    // Simple heuristic: If message looks like it might be a company research request
    // and we haven't done research yet, consider showing agent selection
    // For now, always use standard flow - backend handles classification
    // Agent selection will be shown programmatically when needed
    
    // Emit as chat message (backend will classify and route)
    socket.emit('chat_message', {
        message: message
    });
}

function handleConnectionResponse(data) {
    console.log('Connection response:', data);
    // Don't add initial greeting to chat
    // if (data.message) {
    //     addChatMessage(data.message, 'assistant', 'system');
    // }
}

function handleChatResponse(data) {
    const { message, type, source_label, timestamp, show_agent_selection, company_name } = data;
    
    // Check if backend requested to show agent selection modal
    if (show_agent_selection && company_name) {
        // Show agent selection modal (don't add any chat message yet)
        showAgentSelectionModal(company_name);
        return;
    }
    
    // Skip empty messages
    if (!message || message.trim() === '') {
        return;
    }
    
    // Add message with appropriate styling
    let displayMessage = message;
    
    if (source_label) {
        displayMessage = `${source_label}\n\n${message}`;
    }
    
    addChatMessage(displayMessage, 'assistant', type);
    
    // Scroll to bottom
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function handleTypingIndicator(data) {
    const { typing } = data;
    
    // Remove existing typing indicator
    const existingIndicator = document.querySelector('.typing-indicator');
    if (existingIndicator) {
        existingIndicator.remove();
    }
    
    if (typing) {
        // Add typing indicator
        const indicator = document.createElement('div');
        indicator.className = 'chat-message assistant typing-indicator';
        indicator.innerHTML = `
            <div class="message-bubble">
                <div class="typing-dots">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
            </div>
        `;
        chatMessages.appendChild(indicator);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }
}

function handleResearchStarted(data) {
    const { company_name } = data;
    
    currentCompany = company_name || currentCompany;
    researchInProgress = true;
    researchDone = false;
    progressStartTime = Date.now();
    sourcesData = getEmptySourcesData();
    resetLiveSourcesProgress();
    const scrapingSection = document.getElementById('scrapingProgress');
    if (scrapingSection) {
        scrapingSection.style.display = 'none';
    }
    updateDataStageExtensionVisibility();
    
    sendBtn.disabled = true;
    ensureProgressScreenActive(company_name);
}

function handleNewSession() {
    if (confirm('Are you sure you want to start a new session? Current research data will be cleared.')) {
        socket.emit('new_session');
    }
}

function handleSessionReset(data) {
    console.log('Session reset:', data);
    
    // Reset local state
    researchDone = false;
    currentCompany = null;
    currentAccountPlan = null;
    researchInProgress = false;
    sendBtn.disabled = false;
    
    // Clear chat
    chatMessages.innerHTML = '';
    
    // Reset sources
    sourcesData = getEmptySourcesData();
    resetLiveSourcesProgress();
    const scrapingSection = document.getElementById('scrapingProgress');
    if (scrapingSection) {
        scrapingSection.style.display = 'none';
    }
    updateDataStageExtensionVisibility();
    
    // Don't reload chat history here - it will be loaded by handleChatNameUpdated or on demand
    
    // Show welcome screen
    showWelcomeScreen();
    
    // Enable input
    companyInput.disabled = false;
    companyInput.value = '';
}

function handleError(data) {
    console.error('Error:', data);
    addChatMessage(`❌ Error: ${data.message}`, 'assistant', 'error');
    researchInProgress = false;
    sendBtn.disabled = false;
}

function handleChatNameUpdated(data) {
    const { company_name, session_id } = data;
    console.log('Chat name updated:', company_name);
    
    // Update current company name
    currentCompany = company_name;
    
    // Reload chat history with debouncing (wait 300ms to batch multiple updates)
    debouncedLoadChatHistory();
}

function handleProgressUpdate(data) {
    ensureProgressScreenActive();
    console.log('Progress update received:', data);
    const { step, message, details } = data;
    const progress = data.progress || data.percentage || 0;
    const icon = data.icon || '⚙️';
    
    console.log(`[PROGRESS] Step: ${step}, Message: ${message}, Progress: ${progress}%`);
    
    // Update progress screen only (no chat messages)
    updateProgressScreen(step, message, progress, details);
}

function handleScrapingProgress(data) {
    console.log('Scraping progress received:', data);
    const { url, domain, title, description, status } = data;
    
    // Show scraping progress section
    const scrapingProgress = document.getElementById('scrapingProgress');
    if (scrapingProgress) {
        scrapingProgress.style.display = 'block';
        updateDataStageExtensionVisibility();
    } else {
        console.warn('scrapingProgress element not found');
    }
    
    // Get favicon using Google's favicon service
    const faviconUrl = `https://www.google.com/s2/favicons?domain=${domain}&sz=64`;
    
    // Update the scraping item
    const faviconEl = document.getElementById('scrapingFavicon');
    const titleEl = document.getElementById('scrapingTitle');
    const urlEl = document.getElementById('scrapingUrl');
    const descEl = document.getElementById('scrapingDescription');
    
    if (faviconEl) {
        faviconEl.src = faviconUrl;
        faviconEl.onerror = function() {
            // Fallback to a default globe icon if favicon fails to load
            this.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="%238b5cf6"><circle cx="12" cy="12" r="10"/><path fill="white" d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8z"/><path fill="white" d="M12 6a6 6 0 0 0-6 6h2a4 4 0 0 1 4-4V6z"/></svg>';
        };
    }
    
    if (titleEl) {
        titleEl.textContent = title || domain;
    }
    
    if (urlEl) {
        urlEl.textContent = url;
    }
    
    if (descEl) {
        descEl.textContent = description || 'Fetching content...';
    }
    
    // Add status indicator
    const scrapingItem = document.getElementById('currentScrapingItem');
    if (scrapingItem) {
        scrapingItem.className = 'scraping-item';
        if (status === 'cached') {
            scrapingItem.classList.add('cached');
        } else if (status === 'success') {
            scrapingItem.classList.add('success');
        }
    }
}

function getEmptySourcesData() {
    return {
        pinecone_eightfold: [],
        pinecone_target: [],
        web_scraped: []
    };
}

let sourcesData = getEmptySourcesData();

function handleSourcesData(data) {
    console.log('Received sources data:', data);
    console.log(`Sources count - Eightfold: ${data.pinecone_eightfold?.length || 0}, Target: ${data.pinecone_target?.length || 0}, Web: ${data.web_scraped?.length || 0}`);
    
    // Store with correct key names
    sourcesData = {
        pinecone_eightfold: data.pinecone_eightfold || [],
        pinecone_target: data.pinecone_target || [],
        web_scraped: data.web_scraped || []
    };
    
    console.log('Sources stored successfully:', sourcesData);
    updateLiveSourcesProgress();
    if (currentCompany) {
        populateSources(sourcesData, currentCompany);
    }
}

function resetLiveSourcesProgress() {
    const container = document.getElementById('sourcesProgress');
    const stack = document.getElementById('sourcesFaviconStack');
    const countEl = document.getElementById('sourcesProgressCount');
    const expandBtn = document.getElementById('sourcesExpandBtn');
    const tbody = document.getElementById('sourcesProgressTableBody');
    sourcesExpanded = false;
    if (container) {
        container.style.display = 'none';
        container.classList.remove('expanded');
    }
    if (stack) {
        stack.innerHTML = '<span class="sources-progress-placeholder">Waiting...</span>';
    }
    if (countEl) {
        countEl.textContent = '0 sources';
    }
    if (expandBtn) {
        expandBtn.setAttribute('aria-expanded', 'false');
        const label = expandBtn.querySelector('.sources-expand-label');
        if (label) {
            label.textContent = 'Expand';
        }
    }
    if (tbody) {
        tbody.innerHTML = `
            <tr>
                <td colspan="3">
                    <p class="sources-progress-placeholder">Waiting for first source...</p>
                </td>
            </tr>`;
        tbody.scrollTop = 0;
    }
    updateDataStageExtensionVisibility();
}

function updateLiveSourcesProgress() {
    const container = document.getElementById('sourcesProgress');
    const countEl = document.getElementById('sourcesProgressCount');
    if (!container) return;

    const allWebSources = sourcesData.web_scraped || [];
    if (!allWebSources.length) {
        resetLiveSourcesProgress();
        return;
    }

    container.style.display = 'block';
    if (!sourcesExpanded) {
        container.classList.remove('expanded');
    } else {
        container.classList.add('expanded');
    }

    if (countEl) {
        const total = allWebSources.length;
        countEl.textContent = `${total} ${total === 1 ? 'source' : 'sources'}`;
    }

    updateSourcesFaviconStack(allWebSources);
    renderSourcesProgressTable(allWebSources);
}

function updateSourcesFaviconStack(allSources) {
    const stack = document.getElementById('sourcesFaviconStack');
    if (!stack) return;

    const recentSources = getRecentUniqueSources(allSources, 4);
    if (!recentSources.length) {
        stack.innerHTML = '<span class="sources-progress-placeholder">Waiting...</span>';
        return;
    }

    stack.innerHTML = recentSources.map((source, index) => {
        const domain = source.domain || getDomainFromUrl(source.url);
        const faviconUrl = getFaviconUrl(domain, 32);
        return `
            <img 
                class="sources-favicon"
                src="${faviconUrl}"
                alt="${escapeHtml(domain || 'source favicon')}"
                style="z-index: ${index + 1};"
                onerror="this.onerror=null;this.src='${DEFAULT_FAVICON_DATA_URI}';"
            />
        `;
    }).join('');
}

function renderSourcesProgressTable(allSources) {
    const tbody = document.getElementById('sourcesProgressTableBody');
    if (!tbody) return;

    const recentRows = getRecentUniqueSources(allSources).slice(-20).reverse();
    if (!recentRows.length) {
        tbody.innerHTML = `
            <tr>
                <td colspan="3">
                    <p class="sources-progress-placeholder">Waiting for first source...</p>
                </td>
            </tr>`;
        updateDataStageExtensionVisibility();
        return;
    }

    tbody.innerHTML = recentRows.map((source) => {
        const domain = source.domain || getDomainFromUrl(source.url);
        const title = escapeHtml(source.title || domain || 'Web Source');
        const summary = truncateText(source.description || '', 140);
        const summaryText = summary ? escapeHtml(summary) : '—';
        const domainText = domain ? escapeHtml(domain) : '—';
        return `
            <tr>
                <td>${title}</td>
                <td>${domainText}</td>
                <td>${summaryText}</td>
            </tr>
        `;
    }).join('');

    updateDataStageExtensionVisibility();
}

function handleResearchComplete(data) {
    researchInProgress = false;
    researchDone = true;  // Mark research as complete
    companyInput.disabled = false;
    sendBtn.disabled = false;

    currentAccountPlan = data.plan;
    currentCompany = data.company_name;
    
    // Store selected agents for filtering UI
    selectedAgents = data.plan.selected_agents || ['overview', 'value', 'goals', 'domain', 'synergy'];
    
    // Clear progress interval (if it exists)
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
    
    // Update final stage status
    updateProgressScreen('complete', 'Research Complete!', 100, 'Account plan generated successfully');
    
    // Show dashboard after a short delay
    setTimeout(() => {
        showDashboard();
        populateDashboard(data.plan);
        hideUnselectedSections();  // Hide sections that weren't selected
    }, 1500);
}

function handleResearchError(data) {
    researchInProgress = false;
    companyInput.disabled = false;
    sendBtn.disabled = false;
    
    // Clear progress interval
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
    
    updateProgressScreen('error', '❌ Error Occurred', 0, data.message);
    addChatMessage(`❌ Error: ${data.message}`, 'system');
    
    setTimeout(() => {
        showWelcomeScreen();
    }, 3000);
}

function showWelcomeScreen() {
    welcomeScreen.style.display = 'block';
    dashboard.style.display = 'none';
    plansList.style.display = 'none';
    progressScreen.style.display = 'none';
    progressInitialized = false;
}

function showProgressScreen() {
    welcomeScreen.style.display = 'none';
    dashboard.style.display = 'none';
    plansList.style.display = 'none';
    progressScreen.style.display = 'flex';
}

function showDashboard() {
    welcomeScreen.style.display = 'none';
    dashboard.style.display = 'block';
    plansList.style.display = 'none';
    progressScreen.style.display = 'none';
    progressInitialized = false;
}

async function showPlansList() {
    welcomeScreen.style.display = 'none';
    dashboard.style.display = 'none';
    plansList.style.display = 'block';

    try {
        const response = await fetch('/api/account-plans');
        const plans = await response.json();
        
        const plansGrid = document.getElementById('plansGrid');
        plansGrid.innerHTML = '';
        
        plans.forEach(plan => {
            const planCard = document.createElement('div');
            planCard.className = 'plan-card';
            planCard.innerHTML = `
                <h3>${plan.company_name}</h3>
                <p class="plan-date">${new Date(plan.created_at).toLocaleDateString()}</p>
                <p class="plan-preview">${plan.preview || 'View account plan details...'}</p>
            `;
            planCard.addEventListener('click', () => loadAccountPlan(plan.company_name));
            plansGrid.appendChild(planCard);
        });
    } catch (error) {
        console.error('Error loading plans:', error);
    }
}

async function loadAccountPlan(companyName) {
    try {
        const response = await fetch(`/api/account-plan/${encodeURIComponent(companyName)}`);
        const plan = await response.json();
        
        currentAccountPlan = plan;
        currentCompany = companyName;
        showDashboard();
        populateDashboard(plan);
    } catch (error) {
        console.error('Error loading account plan:', error);
    }
}

function addChatMessage(text, sender = 'user', messageType = 'normal') {
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${sender}`;
    
    // Add additional class for message type
    if (messageType && messageType !== 'normal') {
        messageDiv.classList.add(`message-${messageType}`);
    }
    
    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'message-bubble';
    
    // Handle markdown rendering for assistant messages
    if (sender === 'assistant' && typeof marked !== 'undefined') {
        bubbleDiv.innerHTML = marked.parse(text);
    } else {
        bubbleDiv.textContent = text;
    }
    
    messageDiv.appendChild(bubbleDiv);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function populateDashboard(plan) {
    // Additional Data Response - show prominently if present
    const additionalDataCard = document.getElementById('additionalDataCard');
    const additionalDataContent = document.getElementById('additionalDataContent');
    
    if (plan.additional_data && plan.additional_data.trim()) {
        additionalDataCard.style.display = 'block';
        additionalDataContent.innerHTML = formatSection(plan.additional_data);
    } else {
        additionalDataCard.style.display = 'none';
    }
    
    // Company Overview - with tabs
    populateSectionWithTabs('overviewContent', plan.company_overview, [
        'Company Summary',
        'Key Challenges & Needs',
        'Eightfold Value Proposition'
    ]);
    
    // Value Proposition - with tabs
    populateSectionWithTabs('valueContent', plan.product_fit, [
        'Goal-Product Mapping',
        'Feature-Fit Examples',
        'Implementation Priority'
    ]);
    
    // Long-term Goals - with tabs
    populateSectionWithTabs('goalsContent', plan.long_term_goals, [
        'Long-Term Strategic Goals',
        'Growth Indicators',
        'Talent Strategy Alignment'
    ]);
    
    // Domain Fit - with tabs
    populateSectionWithTabs('domainContent', plan.dept_mapping, [
        'Primary Stakeholder Departments',
        'Decision-Maker Hierarchy',
        'Entry Points',
        'Company Size Context'
    ]);
    
    // Synergy Opportunities - with tabs
    populateSectionWithTabs('synergyContent', plan.synergy_opportunities, [
        'Capability Synergies',
        'Strategic Alignment',
        'Value Multipliers',
        'Competitive Positioning',
        'Case Analogies'
    ]);
    
    // Populate sources with merged objects from plan + live stream
    const planSources = plan.sources_used || {};
    const mergedSources = {
        pinecone_eightfold: (planSources.pinecone_eightfold && planSources.pinecone_eightfold.length)
            ? planSources.pinecone_eightfold
            : (sourcesData.pinecone_eightfold || []),
        pinecone_target: (planSources.pinecone_target && planSources.pinecone_target.length)
            ? planSources.pinecone_target
            : (sourcesData.pinecone_target || []),
        web_scraped: (planSources.web_scraped && planSources.web_scraped.length)
            ? planSources.web_scraped
            : (sourcesData.web_scraped || [])
    };

    console.log('Populating sources with:', mergedSources);
    const hasSources = (
        (mergedSources.pinecone_eightfold && mergedSources.pinecone_eightfold.length) ||
        (mergedSources.pinecone_target && mergedSources.pinecone_target.length) ||
        (mergedSources.web_scraped && mergedSources.web_scraped.length)
    );

    if (hasSources) {
        populateSources(mergedSources, plan.company_name);
    } else {
        console.warn('No sources available to populate');
    }
}

function hideUnselectedSections() {
    // Map of section IDs to agent keys
    const sectionMapping = {
        'overviewCard': 'overview',
        'valueCard': 'value',
        'goalsCard': 'goals',
        'domainCard': 'domain',
        'synergyCard': 'synergy'
    };
    
    // Hide sections that weren't selected
    Object.entries(sectionMapping).forEach(([cardId, agentKey]) => {
        const card = document.getElementById(cardId);
        if (card) {
            card.style.display = selectedAgents.includes(agentKey) ? 'block' : 'none';
        }
    });
}

function formatSection(text) {
    if (!text) return '<p>No data available</p>';
    
    // Use marked.js to render markdown with proper configuration
    marked.setOptions({
        breaks: true,
        gfm: true,
        headerIds: false,
        mangle: false
    });
    
    // Render markdown to HTML
    return marked.parse(text);
}

/**
 * Parse content into sections based on markdown headings
 * @param {string} text - Markdown text content
 * @param {Array<string>} expectedSections - Expected section names
 * @returns {Object} - Object mapping section names to content
 */
function parseSections(text, expectedSections) {
    if (!text) return {};
    
    const sections = {};
    const lines = text.split('\n');
    let currentSection = null;
    let currentContent = [];
    
    // Pattern to match section headings (##, ###, or **)
    const headingPattern = /^(?:#{1,3}\s+|\*\*)\s*(.+?)(?:\*\*)?$/;
    
    lines.forEach(line => {
        const match = line.match(headingPattern);
        
        if (match) {
            // Save previous section if exists
            if (currentSection && currentContent.length > 0) {
                sections[currentSection] = currentContent.join('\n').trim();
            }
            
            // Start new section
            const headingText = match[1].trim();
            
            // Find matching expected section (case-insensitive partial match)
            const matchedSection = expectedSections.find(expected => 
                headingText.toLowerCase().includes(expected.toLowerCase()) ||
                expected.toLowerCase().includes(headingText.toLowerCase())
            );
            
            if (matchedSection) {
                currentSection = matchedSection;
                currentContent = [];
            } else {
                // If no match, use heading text as-is
                currentSection = headingText;
                currentContent = [];
            }
        } else if (currentSection) {
            currentContent.push(line);
        } else {
            // Content before first heading - put in first expected section
            if (expectedSections.length > 0 && !sections[expectedSections[0]]) {
                currentSection = expectedSections[0];
                currentContent = [line];
            }
        }
    });
    
    // Save last section
    if (currentSection && currentContent.length > 0) {
        sections[currentSection] = currentContent.join('\n').trim();
    }
    
    return sections;
}

/**
 * Create tabbed interface for a section
 * @param {string} containerId - ID of container element
 * @param {string} content - Full section content
 * @param {Array<string>} tabNames - Names of tabs to create
 */
function populateSectionWithTabs(containerId, content, tabNames) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    // Check if content is empty or "No data available"
    if (!content || content.trim() === '' || content.trim().toLowerCase().includes('no data available')) {
        container.innerHTML = '<p>No data available</p>';
        return;
    }
    
    // Parse content into sections
    const sections = parseSections(content, tabNames);
    
    // Filter out sections with no data
    const filteredSections = {};
    Object.keys(sections).forEach(sectionName => {
        const sectionContent = sections[sectionName];
        // Check if section has actual content (not just "No data available" or empty)
        if (sectionContent && 
            sectionContent.trim() !== '' && 
            !sectionContent.trim().toLowerCase().includes('no data available') &&
            !sectionContent.trim().toLowerCase().match(/^no\s+\w+\s+available\.?$/i)) {
            filteredSections[sectionName] = sectionContent;
        }
    });
    
    // If no sections found after filtering, show no data message
    if (Object.keys(filteredSections).length === 0) {
        container.innerHTML = '<p>No data available</p>';
        return;
    }
    
    // If only one section after filtering, render without tabs
    if (Object.keys(filteredSections).length === 1) {
        container.innerHTML = formatSection(Object.values(filteredSections)[0]);
        return;
    }
    
    // Create tabbed interface
    const tabsContainer = document.createElement('div');
    tabsContainer.className = 'tabs-container';
    
    // Create tab buttons
    const tabButtons = document.createElement('div');
    tabButtons.className = 'tab-buttons';
    
    // Create tab contents
    const tabContents = document.createElement('div');
    tabContents.className = 'tab-contents';
    
    // Get actual sections that have content (already filtered)
    const availableSections = Object.keys(filteredSections);
    
    availableSections.forEach((sectionName, index) => {
        // Create button
        const button = document.createElement('button');
        button.className = 'tab-button' + (index === 0 ? ' active' : '');
        button.textContent = sectionName;
        button.setAttribute('data-tab', `tab-${containerId}-${index}`);
        button.addEventListener('click', () => switchTab(containerId, index));
        tabButtons.appendChild(button);
        
        // Create content pane
        const pane = document.createElement('div');
        pane.className = 'tab-pane' + (index === 0 ? ' active' : '');
        pane.id = `tab-${containerId}-${index}`;
        pane.innerHTML = formatSection(filteredSections[sectionName]);
        tabContents.appendChild(pane);
    });
    
    tabsContainer.appendChild(tabButtons);
    tabsContainer.appendChild(tabContents);
    container.innerHTML = '';
    container.appendChild(tabsContainer);
}

/**
 * Switch active tab in a tabbed section
 * @param {string} containerId - ID of container element
 * @param {number} tabIndex - Index of tab to activate
 */
function switchTab(containerId, tabIndex) {
    const container = document.getElementById(containerId);
    if (!container) return;
    
    // Update buttons
    const buttons = container.querySelectorAll('.tab-button');
    buttons.forEach((btn, idx) => {
        if (idx === tabIndex) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    
    // Update panes
    const panes = container.querySelectorAll('.tab-pane');
    panes.forEach((pane, idx) => {
        if (idx === tabIndex) {
            pane.classList.add('active');
        } else {
            pane.classList.remove('active');
        }
    });
}

// ===== Progress Tracking Functions =====

function ensureProgressScreenActive(companyName) {
    const targetName = getDisplayCompanyName(companyName || currentCompany || pendingCompanyName);
    if (progressScreen.style.display !== 'flex') {
        showProgressScreen();
    }
    if (!progressInitialized) {
        initializeProgressTracking(targetName || 'Selected company');
        progressInitialized = true;
    }
    if (targetName) {
        const nameEl = document.getElementById('progressCompanyName');
        if (nameEl) {
            nameEl.textContent = `Researching ${targetName}...`;
        }
    }
}

function initializeProgressTracking(companyName) {
    // Set company name
    document.getElementById('progressCompanyName').textContent = `Researching ${getDisplayCompanyName(companyName)}...`;
    
    // Reset all stages
    const stages = ['prompt', 'data', 'agents', 'finalizing'];
    stages.forEach(stage => {
        const stageEl = document.getElementById(`stage-${stage}`);
        if (stageEl) {
            stageEl.setAttribute('data-status', 'pending');
            const statusEl = stageEl.querySelector('.stage-status');
            if (statusEl) statusEl.textContent = '⏳';
        }
    });
    
    // Reset current activity
    const activityEl = document.getElementById('currentActivity');
    if (activityEl) {
        activityEl.textContent = 'Initializing...';
    }
}

function updateProgressScreen(step, message, progress, details) {
    console.log('Updating progress screen:', { step, message, progress, details });
    
    // Update current activity
    const activityEl = document.getElementById('currentActivity');
    if (activityEl) {
        activityEl.textContent = message;
        console.log('Updated currentActivity to:', message);
    } else {
        console.warn('currentActivity element not found');
    }
    
    // Update stage statuses based on step
    updateStageStatus(step);
}

function updateStageStatus(step) {
    console.log('updateStageStatus called with step:', step);
    
    const stageMapping = {
        'prompt_processing': 'prompt',
        'prompt_processed': 'prompt',
        'data_gathering': 'data',
        'data_gathered': 'data',
        'all_data_gathered': 'data',
        'agents_starting': 'agents',
        'agent_overview_complete': 'agents',
        'agent_product_fit_complete': 'agents',
        'agent_goals_complete': 'agents',
        'agent_dept_mapping_complete': 'agents',
        'agent_synergy_complete': 'agents',
        'agent_pricing_complete': 'agents',
        'agent_roi_complete': 'agents',
        'agent_additional_data_complete': 'agents',
        'finalizing': 'finalizing',
        'complete': 'finalizing',
        'error': 'finalizing'
    };
    
    // Handle dynamic steps (like associated_data_gathering_0, associated_data_gathering_1, etc.)
    let currentStage = stageMapping[step];
    
    // If no direct mapping, check for pattern-based mapping
    if (!currentStage) {
        if (step.startsWith('associated_data_gathering_')) {
            currentStage = 'data';
        }
    }
    
    console.log('Mapped stage:', currentStage, 'for step:', step);
    
    if (!currentStage) {
        console.warn('No stage mapping found for step:', step);
        return;
    }
    
    // Hide scraping progress when moving past data gathering stage
    if (currentStage !== 'data' || step === 'data_gathered' || step === 'all_data_gathered') {
        const scrapingProgress = document.getElementById('scrapingProgress');
        if (scrapingProgress) {
            scrapingProgress.style.display = 'none';
        }
    }
    
    // Mark current stage as active or complete
    const stageEl = document.getElementById(`stage-${currentStage}`);
    if (stageEl) {
        const status = step.includes('complete') || step.includes('gathered') || step.includes('processed') ? 'complete' : 'active';
        stageEl.setAttribute('data-status', status);
        const statusEl = stageEl.querySelector('.stage-status');
        if (statusEl) {
            statusEl.textContent = status === 'complete' ? '✅' : '⚙️';
        }
    }
    
    // Mark previous stages as complete
    const stages = ['prompt', 'data', 'agents', 'finalizing'];
    const currentIndex = stages.indexOf(currentStage);
    for (let i = 0; i < currentIndex; i++) {
        const prevStageEl = document.getElementById(`stage-${stages[i]}`);
        if (prevStageEl) {
            prevStageEl.setAttribute('data-status', 'complete');
            const statusEl = prevStageEl.querySelector('.stage-status');
            if (statusEl) {
                statusEl.textContent = '✅';
            }
        }
    }
}

// Remove unused functions that reference removed elements
// function updateProgressCircle() - REMOVED
// function animateValue() - REMOVED  
// function startTimeEstimation() - REMOVED

// ===== Agent Selection Modal Functions =====

function setupAgentSelectionModal() {
    const modal = document.getElementById('agentSelectionModal');
    const overlay = document.getElementById('agentModalOverlay');
    const cancelBtn = document.getElementById('cancelAgentSelection');
    const confirmBtn = document.getElementById('confirmAgentSelection');
    const agentCards = document.querySelectorAll('#agentSelectionModal .agent-card');

    // Toggle agent selection
    agentCards.forEach(card => {
        card.addEventListener('click', () => {
            card.classList.toggle('selected');
            updateSelectedAgentCount();
        });
    });

    // Cancel selection - treat as all agents selected
    cancelBtn.addEventListener('click', () => {
        modal.style.display = 'none';
        // If user closes modal, consider all agents selected
        if (pendingCompanyName) {
            selectedAgents = ['overview', 'value', 'goals', 'domain', 'synergy'];
            console.log('Modal canceled - starting research with all agents:', selectedAgents);
            startResearchWithAgents(pendingCompanyName, selectedAgents);
            pendingCompanyName = null;
        }
    });

    overlay.addEventListener('click', () => {
        modal.style.display = 'none';
        // If user closes modal, consider all agents selected
        if (pendingCompanyName) {
            selectedAgents = ['overview', 'value', 'goals', 'domain', 'synergy'];
            console.log('Modal overlay clicked - starting research with all agents:', selectedAgents);
            startResearchWithAgents(pendingCompanyName, selectedAgents);
            pendingCompanyName = null;
        }
    });

    // Confirm selection and start research
    confirmBtn.addEventListener('click', () => {
        const selectedCards = document.querySelectorAll('#agentSelectionModal .agent-card.selected');
        selectedAgents = Array.from(selectedCards).map(card => card.dataset.agent);
        
        console.log('Confirm button clicked. Selected agents:', selectedAgents);
        console.log('Pending company name:', pendingCompanyName);
        
        if (selectedAgents.length === 0) {
            alert('Please select at least one research area');
            return;
        }

        console.log('Research confirmed with selected agents:', selectedAgents);
        
        // Store company name before clearing pendingCompanyName
        const companyToResearch = pendingCompanyName;
        
        // Hide modal
        modal.style.display = 'none';
        
        // Start research with selected agents
        if (companyToResearch) {
            console.log('Calling startResearchWithAgents for:', companyToResearch);
            startResearchWithAgents(companyToResearch, selectedAgents);
        } else {
            console.error('No pending company name - cannot start research');
        }
    });
}

function showAgentSelectionModal(companyName) {
    pendingCompanyName = companyName;
    const modal = document.getElementById('agentSelectionModal');
    const companyNameEl = document.getElementById('agentModalCompanyName');
    
    companyNameEl.textContent = companyName;
    
    // Reset all agents to selected
    const agentCards = document.querySelectorAll('#agentSelectionModal .agent-card');
    agentCards.forEach(card => card.classList.add('selected'));
    updateSelectedAgentCount();
    
    modal.style.display = 'flex';
}

function updateSelectedAgentCount() {
    const selectedCards = document.querySelectorAll('#agentSelectionModal .agent-card.selected');
    const countEl = document.getElementById('selectedAgentCount');
    if (countEl) {
        countEl.textContent = selectedCards.length;
    }
}

function startResearchWithAgents(companyName, agents) {
    console.log(`🚀 startResearchWithAgents called for: ${companyName} with agents:`, agents);
    
    if (!companyName) {
        console.error('❌ Cannot start research - no company name provided');
        return;
    }
    
    if (!agents || agents.length === 0) {
        console.error('❌ Cannot start research - no agents selected');
        return;
    }
    
    currentCompany = companyName;
    researchInProgress = true;
    researchDone = false;
    progressStartTime = Date.now();
    pendingCompanyName = null;
    sendBtn.disabled = true;
    ensureProgressScreenActive(companyName);
    
    console.log('✅ Emitting confirm_agent_selection to backend');
    
    // Emit confirmation to backend with selected agents
    socket.emit('confirm_agent_selection', {
        selected_agents: agents
    });
}

// ===== Individual Regenerate Functions =====

function setupRegenerateButtons() {
    const regenerateBtns = document.querySelectorAll('.btn-regenerate');
    
    regenerateBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const section = btn.dataset.section;
            showSectionRegenerateModal(section);
        });
    });
}

function showSectionRegenerateModal(section) {
    const modal = document.getElementById('sectionRegenerateModal');
    const sectionName = document.getElementById('sectionRegenerateName');
    const textarea = document.getElementById('sectionContextTextarea');
    
    if (!modal) return;
    
    // Set section name
    sectionName.textContent = getSectionName(section);
    
    // Clear previous context
    textarea.value = '';
    
    // Store current section in modal dataset
    modal.dataset.currentSection = section;
    
    // Show modal
    modal.style.display = 'flex';
}

function setupSectionRegenerateModal() {
    const modal = document.getElementById('sectionRegenerateModal');
    const closeBtn = document.getElementById('closeSectionRegenerate');
    const cancelBtn = document.getElementById('cancelSectionRegenerate');
    const confirmBtn = document.getElementById('confirmSectionRegenerate');
    const overlay = document.getElementById('sectionModalOverlay');
    
    if (!modal) return;
    
    // Close handlers
    const closeModal = () => {
        modal.style.display = 'none';
        document.getElementById('sectionContextTextarea').value = '';
    };
    
    closeBtn.addEventListener('click', closeModal);
    cancelBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', closeModal);
    
    // Confirm regeneration
    confirmBtn.addEventListener('click', () => {
        const section = modal.dataset.currentSection;
        const context = document.getElementById('sectionContextTextarea').value.trim();
        
        if (!section) {
            console.error('No section specified');
            return;
        }
        
        // Context is optional - allow regeneration even without context
        closeModal();
        regenerateSection(section, context);
    });
}

function toggleContextPanel(section, show) {
    // Deprecated - kept for backwards compatibility
    // Now using modal instead
    const panel = document.getElementById(`${section}ContextPanel`);
    if (panel) {
        panel.style.display = show ? 'block' : 'none';
    }
}

async function regenerateSection(section, context) {
    if (!currentCompany) {
        console.error('No company selected');
        return;
    }

    console.log(`Regenerating ${section} with context: ${context}`);

    // Show loading state
    const contentEl = document.getElementById(`${section}Content`);
    const originalContent = contentEl.innerHTML;
    contentEl.innerHTML = '<p class="loading">Regenerating...</p>';

    // Add chat update
    addChatMessage(`🔄 Regenerating ${section} analysis with your additional context...`, 'assistant', 'system');

    try {
        const response = await fetch('/api/research/regenerate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: socket.id,
                agent_name: section,
                company_name: currentCompany,
                additional_context: context,
                previous_results: currentAccountPlan
            })
        });

        const data = await response.json();

        if (data.success) {
            // Update only this section
            updateDashboardSection(section, data.result);
            
            // Update chat with success message
            addChatMessage(`✓ ${getSectionName(section)} has been regenerated with your additional requirements.`, 'assistant', 'update');
        } else {
            throw new Error(data.error || 'Regeneration failed');
        }
    } catch (error) {
        console.error('Error regenerating section:', error);
        contentEl.innerHTML = originalContent; // Restore original
        addChatMessage(`❌ Failed to regenerate ${section}: ${error.message}`, 'assistant', 'error');
    }
}

function updateDashboardSection(section, content) {
    const contentEl = document.getElementById(`${section}Content`);
    if (contentEl) {
        contentEl.innerHTML = marked.parse(content);
    }

    // Update stored plan
    if (currentAccountPlan) {
        const fieldMap = {
            'overview': 'company_overview',
            'value': 'product_fit',
            'goals': 'long_term_goals',
            'domain': 'dept_mapping',
            'synergy': 'synergy_opportunities'
        };
        const field = fieldMap[section];
        if (field) {
            currentAccountPlan[field] = content;
        }
    }
}

function getSectionName(section) {
    const names = {
        'overview': 'Company Overview',
        'value': 'Value Proposition Alignment',
        'goals': 'Long-term Goals',
        'domain': 'Domain Fit',
        'synergy': 'Synergy Opportunities'
    };
    return names[section] || section;
}

// ===== Global Regenerate Modal Functions =====

function setupGlobalRegenerateModal() {
    const modal = document.getElementById('globalRegenerateModal');
    const openBtn = document.getElementById('globalRegenerateBtn');
    const cancelBtn = document.getElementById('cancelGlobalRegenerate');
    const confirmBtn = document.getElementById('confirmGlobalRegenerate');
    const checkboxes = document.querySelectorAll('.global-agent-checkbox input[type="checkbox"]');
    const overlay = modal ? modal.querySelector('.modal-overlay') : null;

    if (!modal || !openBtn) return;

    // Open modal
    openBtn.addEventListener('click', () => {
        modal.style.display = 'flex';
        updateGlobalSelectedCount();
    });

    // Close modal
    cancelBtn.addEventListener('click', () => {
        modal.style.display = 'none';
    });

    if (overlay) {
        overlay.addEventListener('click', () => {
            modal.style.display = 'none';
        });
    }

    // Update count when checkboxes change
    checkboxes.forEach(checkbox => {
        checkbox.addEventListener('change', updateGlobalSelectedCount);
    });

    // Confirm regeneration
    confirmBtn.addEventListener('click', () => {
        const selectedCheckboxes = document.querySelectorAll('.global-agent-checkbox input[type="checkbox"]:checked');
        const selectedSections = Array.from(selectedCheckboxes).map(cb => cb.value);
        const context = document.getElementById('globalContextTextarea').value.trim();

        if (selectedSections.length === 0) {
            alert('Please select at least one section');
            return;
        }

        // Context is optional - allow regeneration without it
        modal.style.display = 'none';
        regenerateMultipleSections(selectedSections, context);
        
        // Reset
        document.getElementById('globalContextTextarea').value = '';
    });
}

function updateGlobalSelectedCount() {
    const selectedCheckboxes = document.querySelectorAll('.global-agent-checkbox input[type="checkbox"]:checked');
    const countEl = document.getElementById('globalSelectedCount');
    if (countEl) {
        countEl.textContent = selectedCheckboxes.length;
    }
}

async function regenerateMultipleSections(sections, context) {
    if (!currentCompany) {
        console.error('No company selected');
        return;
    }

    console.log(`Regenerating ${sections.length} sections:`, sections);

    // Show loading state for all sections
    sections.forEach(section => {
        const contentEl = document.getElementById(`${section}Content`);
        if (contentEl) {
            contentEl.innerHTML = '<p class="loading">Regenerating...</p>';
        }
    });

    // Add chat update
    const sectionNames = sections.map(s => getSectionName(s)).join(', ');
    addChatMessage(`🔄 Regenerating ${sections.length} sections (${sectionNames}) with your additional context...`, 'assistant', 'system');

    try {
        const response = await fetch('/api/research/regenerate-multiple', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                session_id: socket.id,
                agents: sections,
                company_name: currentCompany,
                additional_context: context,
                previous_results: currentAccountPlan
            })
        });

        const data = await response.json();

        if (data.success) {
            // Update each section
            Object.entries(data.results).forEach(([section, content]) => {
                updateDashboardSection(section, content);
                
                // If this section was previously hidden, show it and add to selectedAgents
                if (!selectedAgents.includes(section)) {
                    selectedAgents.push(section);
                    const cardId = `${section}Card`;
                    const card = document.getElementById(cardId);
                    if (card) {
                        card.style.display = 'block';
                    }
                }
            });
            
            // Update chat with success message
            addChatMessage(`✓ Successfully regenerated ${sections.length} sections with your additional requirements.`, 'assistant', 'update');
        } else {
            throw new Error(data.error || 'Regeneration failed');
        }
    } catch (error) {
        console.error('Error regenerating sections:', error);
        addChatMessage(`❌ Failed to regenerate sections: ${error.message}`, 'assistant', 'error');
        
        // Reload current data
        if (currentAccountPlan) {
            sections.forEach(section => {
                const fieldMap = {
                    'overview': 'company_overview',
                    'value': 'product_fit',
                    'goals': 'long_term_goals',
                    'domain': 'dept_mapping',
                    'synergy': 'synergy_opportunities'
                };
                const field = fieldMap[section];
                if (field && currentAccountPlan[field]) {
                    updateDashboardSection(section, currentAccountPlan[field]);
                }
            });
        }
    }
}

// ========================================
// Dashboard Tabs & Sources Management
// ========================================

function setupDashboardTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.dataset.tab;
            
            console.log('Tab clicked:', tabName);
            
            // Remove active class from all tabs and contents
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            // Add active class to clicked tab and corresponding content
            btn.classList.add('active');
            const targetTab = document.getElementById(`${tabName}Tab`);
            if (targetTab) {
                targetTab.classList.add('active');
                targetTab.style.display = 'block';
                console.log('Showing tab:', `${tabName}Tab`);
            } else {
                console.warn('Tab not found:', `${tabName}Tab`);
            }
            
            // Hide other tabs
            tabContents.forEach(c => {
                if (c.id !== `${tabName}Tab`) {
                    c.style.display = 'none';
                }
            });
        });
    });
}

function populateSources(sources, companyName) {
    console.log('Populating sources:', sources);
    
    // Ensure sources tab exists and is ready
    const sourcesTab = document.getElementById('sourcesTab');
    const sourcesContainer = document.querySelector('.sources-container');
    
    if (sourcesContainer) {
        sourcesContainer.style.display = 'block'; // Ensure container is visible when tab is shown
    }
    
    // Update target company name
    const targetCompanyNameEl = document.getElementById('targetCompanyName');
    if (targetCompanyNameEl) {
        targetCompanyNameEl.textContent = getDisplayCompanyName(companyName) || 'Target Company';
    }
    
    // // Populate Eightfold sources
    // const eightfoldSourcesEl = document.getElementById('eightfoldSources');
    // if (eightfoldSourcesEl && sources.pinecone_eightfold && sources.pinecone_eightfold.length > 0) {
    //     eightfoldSourcesEl.innerHTML = sources.pinecone_eightfold.map(source => `
    //         <div class="source-item">
    //             <div class="source-icon">📄</div>
    //             <div class="source-info">
    //                 <div class="source-title">${escapeHtml(source.title || (source.text ? `${source.text.substring(0, 100)}...` : 'Vector Document'))}</div>
    //                 <div class="source-meta">Score: ${(source.score || 0).toFixed(3)} | Type: Vector Document</div>
    //             </div>
    //         </div>
    //     `).join('');
    // } else if (eightfoldSourcesEl) {
    //     eightfoldSourcesEl.innerHTML = '<p class="source-placeholder">No Eightfold sources used</p>';
    // }
    
    // // Populate target company sources
    // const targetSourcesEl = document.getElementById('targetSources');
    // if (targetSourcesEl && sources.pinecone_target && sources.pinecone_target.length > 0) {
    //     targetSourcesEl.innerHTML = sources.pinecone_target.map(source => `
    //         <div class="source-item">
    //             <div class="source-icon">📄</div>
    //             <div class="source-info">
    //                 <div class="source-title">${escapeHtml(source.title || (source.text ? `${source.text.substring(0, 100)}...` : 'Vector Document'))}</div>
    //                 <div class="source-meta">Score: ${(source.score || 0).toFixed(3)} | Type: Vector Document</div>
    //             </div>
    //         </div>
    //     `).join('');
    // } else if (targetSourcesEl) {
    //     targetSourcesEl.innerHTML = '<p class="source-placeholder">No target company sources used</p>';
    // }
    
    // Populate web sources in compressed table format (show every scraped entry)
    const webSourcesEl = document.getElementById('webSources');
    console.log(sources);
    const allWebSources = Array.isArray(sources.web_scraped) ? sources.web_scraped : [];
    updateWebSourcesCount(allWebSources.length);
    if (webSourcesEl && allWebSources.length > 0) {
        webSourcesEl.innerHTML = buildWebSourcesTable(allWebSources);
        console.log('✅ Web sources populated:', allWebSources.length, 'entries');
    } else if (webSourcesEl) {
        webSourcesEl.innerHTML = '<p class="source-placeholder">No web sources used</p>';
        console.log('⚠️ No web sources to display');
    } else {
        console.error('❌ webSources element not found');
    }
}

function buildWebSourcesTable(sources) {
    const orderedSources = [...sources].reverse(); // Newest first
    const rowsHtml = orderedSources.map((source) => {
        const domain = source.domain || getDomainFromUrl(source.url);
        const title = escapeHtml(source.title || domain || 'Web Source');
        const summary = truncateText(source.description || '', 160);
        const summaryCell = summary ? escapeHtml(summary) : '—';
        let linkCell = '—';
        if (source.url) {
            const safeUrl = escapeHtml(source.url);
            const linkLabel = escapeHtml(domain || source.url);
            linkCell = `<a href="${safeUrl}" target="_blank" rel="noopener" class="source-url">${linkLabel}</a>`;
        } else if (domain) {
            linkCell = escapeHtml(domain);
        }
        return `
            <tr>
                <td>${title}</td>
                <td>${linkCell}</td>
                <td>${summaryCell}</td>
            </tr>
        `;
    }).join('');
    
    return `
        <div class="sources-table-wrapper">
            <table class="sources-table">
                <thead>
                    <tr>
                        <th>Source</th>
                        <th>Link / Domain</th>
                        <th>Summary</th>
                    </tr>
                </thead>
                <tbody>
                    ${rowsHtml}
                </tbody>
            </table>
        </div>
    `;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getDomainFromUrl(url) {
    if (!url) return '';
    try {
        return new URL(url).hostname;
    } catch (error) {
        return url;
    }
}

function getRecentUniqueSources(sources, limit) {
    if (!Array.isArray(sources) || sources.length === 0) {
        return [];
    }
    const unique = [];
    const seen = new Set();
    for (let i = sources.length - 1; i >= 0; i -= 1) {
        const entry = sources[i];
        if (!entry) continue;
        const key = entry.url || entry.title || `source-${i}`;
        if (seen.has(key)) {
            continue;
        }
        seen.add(key);
        unique.unshift(entry);
        if (limit && unique.length >= limit) {
            break;
        }
    }
    return unique;
}

function truncateText(text, maxLength = 140) {
    if (!text) return '';
    if (text.length <= maxLength) {
        return text;
    }
    return `${text.substring(0, maxLength - 3)}...`;
}

function getFaviconUrl(domain, size = 32) {
    const safeDomain = domain || 'example.com';
    return `https://www.google.com/s2/favicons?domain=${safeDomain}&sz=${size}`;
}

function updateWebSourcesCount(count) {
    const badge = document.getElementById('webSourcesCount');
    if (!badge) return;
    badge.textContent = `${count} ${count === 1 ? 'entry' : 'entries'}`;
}

function getDisplayCompanyName(rawName) {
    if (currentAccountPlan?.company_name && currentAccountPlan.company_name.trim()) {
        return currentAccountPlan.company_name.trim();
    }

    const fallback = currentCompany || pendingCompanyName;
    let name = rawName || fallback;
    if (typeof name !== 'string' || !name.trim()) {
        return 'Selected company';
    }

    let candidate = name.trim();

    const calledMatch = candidate.match(/(?:called|named)\s+([^.!?\n]+)/i);
    if (calledMatch && calledMatch[1]) {
        candidate = calledMatch[1].trim();
    } else {
        const sentence = candidate.split(/[\n.!?]/).find(segment => segment && segment.trim());
        if (sentence) {
            candidate = sentence.trim();
        }
    }

    candidate = candidate.split(/[—-]/)[0].trim();
    candidate = candidate.replace(/^hey there\s*,?\s*/i, '').replace(/^hi\s*,?\s*/i, '');

    if (candidate.length > 80) {
        candidate = `${candidate.substring(0, 77)}...`;
    }

    return candidate || 'Selected company';
}

function updateDataStageExtensionVisibility() {
    const extension = document.getElementById('dataStageExtension');
    if (!extension) return;
    const scrapingVisible = isElementCurrentlyVisible(document.getElementById('scrapingProgress'));
    const sourcesVisible = isElementCurrentlyVisible(document.getElementById('sourcesProgress'));
    extension.style.display = (scrapingVisible || sourcesVisible) ? 'block' : 'none';
}

function isElementCurrentlyVisible(element) {
    if (!element) {
        return false;
    }
    if (element.style.display) {
        return element.style.display !== 'none';
    }
    return window.getComputedStyle(element).display !== 'none';
}

// ============================================================================
// CHAT PERSISTENCE FUNCTIONS
// ============================================================================

function debouncedLoadChatHistory() {
    // Clear any pending timer
    if (chatHistoryLoadTimer) {
        clearTimeout(chatHistoryLoadTimer);
    }
    
    // Set new timer to load after 300ms of inactivity
    chatHistoryLoadTimer = setTimeout(() => {
        loadChatHistory();
    }, 300);
}

async function loadChatHistory() {
    try {
        const response = await fetch('/api/chats');
        const data = await response.json();
        
        if (data.success && data.chats) {
            chats = data.chats;
            renderChatHistory();
        }
    } catch (error) {
        console.error('Failed to load chat history:', error);
        chatHistory.innerHTML = '<div class="chat-history-loading">Failed to load chats</div>';
    }
}

function renderChatHistory() {
    if (!chats || chats.length === 0) {
        chatHistory.innerHTML = '<div class="chat-history-loading">No chats yet</div>';
        return;
    }
    
    chatHistory.innerHTML = '';
    
    chats.forEach(chat => {
        const chatItem = document.createElement('div');
        chatItem.className = 'chat-history-item';
        if (chat.session_id === socket.id) {
            chatItem.classList.add('active');
        }
        
        const date = new Date(chat.updated_at);
        const formattedDate = formatChatDate(date);
        
        chatItem.innerHTML = `
            <div class="chat-history-item-content">
                <div class="chat-history-item-title">${chat.company_name || 'New Chat'}</div>
                <div class="chat-history-item-date">${formattedDate}</div>
            </div>
            <button class="chat-history-item-delete" data-session-id="${chat.session_id}" title="Delete chat">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                </svg>
            </button>
        `;
        
        chatItem.addEventListener('click', (e) => {
            if (!e.target.closest('.chat-history-item-delete')) {
                loadChat(chat.session_id);
            }
        });
        
        const deleteBtn = chatItem.querySelector('.chat-history-item-delete');
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteChat(chat.session_id);
        });
        
        chatHistory.appendChild(chatItem);
    });
}

function formatChatDate(date) {
    const now = new Date();
    const diff = now - date;
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    
    if (days > 7) {
        return date.toLocaleDateString();
    } else if (days > 0) {
        return `${days}d ago`;
    } else if (hours > 0) {
        return `${hours}h ago`;
    } else if (minutes > 0) {
        return `${minutes}m ago`;
    } else {
        return 'Just now';
    }
}

async function loadChat(sessionId) {
    try {
        const response = await fetch(`/api/chats/${sessionId}`);
        const data = await response.json();
        
        if (data.success && data.chat) {
            // Clear current chat
            chatMessages.innerHTML = '';
            
            // Load messages
            const messages = data.chat.messages || [];
            messages.forEach(msg => {
                addChatMessage(msg.content, msg.role, msg.type || 'text');
            });
            
            // Update state
            currentChatId = sessionId;
            if (data.chat.research_results) {
                currentAccountPlan = data.chat.research_results;
                currentCompany = data.chat.company_name;
                researchDone = data.chat.is_research_complete;
                
                // Show dashboard if research is complete
                if (researchDone) {
                    showDashboard();
                    renderDashboard(data.chat.research_results);
                }
            }
            
            // Update active state in UI
            document.querySelectorAll('.chat-history-item').forEach(item => {
                item.classList.remove('active');
            });
            const activeItem = Array.from(document.querySelectorAll('.chat-history-item'))
                .find(item => item.querySelector(`[data-session-id="${sessionId}"]`));
            if (activeItem) {
                activeItem.classList.add('active');
            }
        }
    } catch (error) {
        console.error('Failed to load chat:', error);
        alert('Failed to load chat');
    }
}

async function handleCreateNewChat() {
    if (!confirm('Are you sure you want to start a new chat? Current research will be cleared.')) {
        return;
    }
    
    try {
        // Trigger socket new_session event which handles MongoDB creation
        socket.emit('new_session');
        
        // Clear chat messages immediately
        chatMessages.innerHTML = '';
        
        // Reset state
        currentCompany = null;
        currentAccountPlan = null;
        researchDone = false;
        researchInProgress = false;
        
        showWelcomeScreen();
        
        // Chat history will be updated via handleChatNameUpdated event from backend
    } catch (error) {
        console.error('Failed to create new chat:', error);
        alert('Failed to create new chat');
    }
}

async function deleteChat(sessionId) {
    if (!confirm('Are you sure you want to delete this chat?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/chats/${sessionId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Reload chat history
            await loadChatHistory();
            
            // If deleted chat was active, create new one
            if (sessionId === socket.id) {
                await handleCreateNewChat();
            }
        } else {
            alert('Failed to delete chat');
        }
    } catch (error) {
        console.error('Failed to delete chat:', error);
        alert('Failed to delete chat');
    }
}

function handleNewSession() {
    handleCreateNewChat();
}
