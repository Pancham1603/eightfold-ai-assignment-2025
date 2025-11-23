const socket = io();

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
const newSessionBtn = document.getElementById('newSessionBtn');

let currentCompany = null;
let currentAccountPlan = null;
let researchInProgress = false;
let progressStartTime = null;
let progressInterval = null;
let researchDone = false;  // Track if research has been completed

document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    setupResizableSidebar();
    showWelcomeScreen();
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
    if (newSessionBtn) newSessionBtn.addEventListener('click', handleNewSession);

    socket.on('connect', () => console.log('Connected to server'));
    socket.on('connection_response', handleConnectionResponse);
    socket.on('chat_response', handleChatResponse);
    socket.on('chat_typing', handleTypingIndicator);
    socket.on('session_reset', handleSessionReset);
    socket.on('research_started', handleResearchStarted);
    socket.on('progress_update', handleProgressUpdate);
    socket.on('research_complete', handleResearchComplete);
    socket.on('research_error', handleResearchError);
    socket.on('error', handleError);
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

function handleSendMessage() {
    const message = companyInput.value.trim();
    if (!message || researchInProgress) return;

    // Add user message to chat
    addChatMessage(message, 'user');
    
    // Clear input
    companyInput.value = '';

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
    const { message, type, source_label, timestamp } = data;
    
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
    
    currentCompany = company_name;
    researchInProgress = true;
    researchDone = false;
    progressStartTime = Date.now();
    
    sendBtn.disabled = true;
    
    // Don't show system message in chat - progress screen will handle updates
    // addChatMessage(message, 'assistant', 'system');
    
    // Show progress screen
    showProgressScreen();
    initializeProgressTracking(company_name);
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
    
    // Clear chat messages
    chatMessages.innerHTML = '';
    
    // Don't add system message - just reset silently
    // addChatMessage(data.message, 'assistant', 'system');
    
    // Show welcome screen
    showWelcomeScreen();
    
    // Enable input
    sendBtn.disabled = false;
    companyInput.disabled = false;
    companyInput.value = '';
}

function handleError(data) {
    console.error('Error:', data);
    addChatMessage(`❌ Error: ${data.message}`, 'assistant', 'error');
    researchInProgress = false;
    sendBtn.disabled = false;
}

function handleProgressUpdate(data) {
    const { step, message, details } = data;
    const progress = data.progress || data.percentage || 0;
    const icon = data.icon || '⚙️';
    
    // Update progress screen only (no chat messages)
    updateProgressScreen(step, message, progress, details);
}

function handleResearchComplete(data) {
    researchInProgress = false;
    researchDone = true;  // Mark research as complete
    companyInput.disabled = false;
    sendBtn.disabled = false;

    currentAccountPlan = data.plan;
    currentCompany = data.company_name;
    
    // Clear progress interval (if it exists)
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
    
    // Update final stage status
    updateProgressScreen('complete', '✅ Research Complete!', 100, 'Account plan generated successfully');
    
    // Show dashboard after a short delay
    setTimeout(() => {
        showDashboard();
        populateDashboard(data.plan);
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

function initializeProgressTracking(companyName) {
    // Set company name
    document.getElementById('progressCompanyName').textContent = `Researching ${companyName}...`;
    
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
    // Update current activity
    const activityEl = document.getElementById('currentActivity');
    if (activityEl) {
        activityEl.textContent = message;
    }
    
    // Update stage statuses based on step
    updateStageStatus(step);
}

function updateStageStatus(step) {
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
        'complete': 'finalizing'
    };
    
    const currentStage = stageMapping[step];
    if (!currentStage) return;
    
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
