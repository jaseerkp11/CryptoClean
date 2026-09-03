/**
 * KryptLedg Frontend Application
 * Professional Crypto Tax Reporting Dashboard
 */

// State
const state = {
    currentPage: 'landing',
    selectedFiles: [],
    selectedPlan: 'free',
    timezone: 'UTC',
    results: null,
    apiOnline: false,
    activeTab: 'overview',
    activeSubTab: 'events',
    detectedExchange: null,
    detectedReports: [],
    transactionCount: 0,
    planValidation: null,
    filteredTransactions: [],
    txPage: 1,
    txPageSize: 25,
    currentTx: null,
    reportReadiness: null
};

// Elements
const elements = {
    pages: {
        landing: document.getElementById('page-landing'),
        upload: document.getElementById('page-upload'),
        processing: document.getElementById('page-processing'),
        results: document.getElementById('page-results'),
        security: document.getElementById('page-security'),
        faq: document.getElementById('page-faq')
    },
    uploadZone: document.getElementById('upload-zone'),
    fileInput: document.getElementById('file-input'),
    uploadPrompt: document.getElementById('upload-prompt'),
    uploadFileSelected: document.getElementById('upload-file-selected'),
    selectedFileName: document.getElementById('selected-file-name'),
    selectedFileSize: document.getElementById('selected-file-size'),
    processBtn: document.getElementById('process-btn'),
    progressFill: document.getElementById('progress-fill'),
    processingTitle: document.getElementById('processing-title'),
    processingStatus: document.getElementById('processing-status'),
    toastContainer: document.getElementById('toast-container'),
    taxYearSelect: document.getElementById('tax-year-select'),
    uploadedReports: document.getElementById('uploaded-reports'),
    reportsList: document.getElementById('reports-list'),
    readinessSection: document.getElementById('readiness-section'),
    readinessStatus: document.getElementById('readiness-status'),
    readinessDetails: document.getElementById('readiness-details'),
    coverageGuidance: document.getElementById('coverage-guidance')
};

// ============================================
// Data Mapping Layer — Safe Accessors
// ============================================

function safeNum(value) {
    if (value === null || value === undefined || value === '') return null;
    const num = parseFloat(value);
    return isNaN(num) ? null : num;
}

function safeStr(value) {
    if (value === null || value === undefined) return null;
    return String(value).trim();
}

function fmtCurrency(value, currency = 'USD') {
    const num = safeNum(value);
    if (num === null) return '<span class="unresolved">UNRESOLVED</span>';
    return num.toLocaleString('en-US', { style: 'currency', currency: currency.toUpperCase(), minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtNumber(value) {
    const num = safeNum(value);
    if (num === null) return '<span class="unresolved">UNRESOLVED</span>';
    if (Math.abs(num) >= 1000000) return (num / 1000000).toFixed(2) + 'M';
    if (Math.abs(num) >= 1000) return (num / 1000).toFixed(2) + 'K';
    if (Math.abs(num) < 0.01 && num !== 0) return num.toExponential(2);
    return num.toLocaleString('en-US', { maximumFractionDigits: 6 });
}

function fmtDate(value) {
    if (!value) return '<span class="unresolved">UNRESOLVED</span>';
    const date = new Date(value);
    if (isNaN(date.getTime())) return '<span class="unresolved">UNRESOLVED</span>';
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function fmtBadge(type) {
    const t = safeStr(type) || 'UNKNOWN';
    return `<span class="badge badge-${t.toLowerCase()}">${t}</span>`;
}

// ============================================
// Initialization
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupUploadZone();
    setupTabs();
    setupSubTabs();
    setupSearch();
    setupPlanSelection();
    setupTaxYearFilter();
    checkApiStatus();
});

function checkApiStatus() {
    api.checkHealth().then(result => {
        state.apiOnline = result.online;
    });
}

// ============================================
// Navigation
// ============================================

function setupNavigation() {
    document.querySelectorAll('.nav-link, .mobile-link').forEach(link => {
        link.addEventListener('click', (e) => {
            const href = link.getAttribute('href');
            if (href && href.startsWith('#') && href.length > 1) {
                e.preventDefault();
                const target = document.querySelector(href);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth' });
                }
            }
        });
    });
}

function toggleMobile() {
    const mobile = document.getElementById('nav-mobile');
    mobile.classList.toggle('active');
}

function navigateTo(page) {
    state.currentPage = page;
    Object.values(elements.pages).forEach(p => p.classList.remove('active'));
    elements.pages[page]?.classList.add('active');
    window.scrollTo(0, 0);
}

// ============================================
// Plan Selection
// ============================================

function setupPlanSelection() {
    document.querySelectorAll('input[name="report-plan"]').forEach(radio => {
        radio.addEventListener('change', (e) => {
            state.selectedPlan = e.target.value;
            updateUploadHeaderForPlan(state.selectedPlan);
            validatePlan();
        });
    });
}

function selectPlan(plan) {
    state.selectedPlan = plan;
    const radio = document.querySelector(`input[name="report-plan"][value="${plan}"]`);
    if (radio) {
        radio.checked = true;
    }
    updateUploadHeaderForPlan(plan);
    navigateTo('upload');
}

function updateUploadHeaderForPlan(plan) {
    const planNames = {
        free: 'Free Report',
        standard: 'Standard Report — $9',
        complete: 'Complete Report — $19'
    };
    const uploadHeader = document.querySelector('.upload-header h1');
    if (uploadHeader && plan) {
        uploadHeader.textContent = `Upload Your Report — ${planNames[plan] || ''}`;
    }
}

function validatePlan() {
    const summaryEl = document.getElementById('upload-plan-summary');
    const validationEl = document.getElementById('plan-validation');
    const processBtn = document.getElementById('process-btn');

    if (!summaryEl || !validationEl) return;

    const planConfig = {
        free: { label: 'Free Report', limit: 100 },
        standard: { label: 'Standard Report', limit: 5000 },
        complete: { label: 'Complete Report', limit: null }
    };

    const config = planConfig[state.selectedPlan] || planConfig.free;
    summaryEl.style.display = 'flex';
    document.getElementById('plan-summary-label').textContent = config.label;
    document.getElementById('plan-summary-limit').textContent = config.limit ? `Up to ${config.limit} transactions` : 'Unlimited transactions';

    if (state.transactionCount > 0) {
        if (config.limit && state.transactionCount > config.limit) {
            validationEl.className = 'plan-validation error';
            validationEl.innerHTML = `<span>✕</span> This file contains ${state.transactionCount} transactions. The ${config.label} supports up to ${config.limit} transactions. <a href="#pricing" onclick="document.getElementById('pricing').scrollIntoView({behavior:'smooth'}); return false;">Upgrade Plan</a>`;
            processBtn.disabled = true;
            state.planValidation = 'over_limit';
        } else {
            validationEl.className = 'plan-validation success';
            validationEl.innerHTML = `<span>✓</span> ${state.transactionCount} / ${config.limit || '∞'} transactions`;
            processBtn.disabled = !state.selectedFiles || state.selectedFiles.length === 0;
            state.planValidation = null;
        }
    } else {
        validationEl.className = 'plan-validation';
        validationEl.innerHTML = '';
        processBtn.disabled = !state.selectedFiles || state.selectedFiles.length === 0;
        state.planValidation = null;
    }
}

// ============================================
// Upload
// ============================================

function setupUploadZone() {
    const zone = elements.uploadZone;
    const input = elements.fileInput;

    zone.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        input.click();
    });

    input.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(Array.from(e.target.files));
        }
    });

    zone.addEventListener('dragover', (e) => {
        e.preventDefault();
        zone.classList.add('drag-over');
    });

    zone.addEventListener('dragleave', () => {
        zone.classList.remove('drag-over');
    });

    zone.addEventListener('drop', (e) => {
        e.preventDefault();
        zone.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) {
            const files = Array.from(e.dataTransfer.files);
            const validFiles = files.filter(f => f.name.toLowerCase().endsWith('.csv'));
            if (validFiles.length > 0) {
                handleFileSelect(validFiles);
            } else {
                showToast('error', 'Invalid File', 'Please upload CSV files only.');
            }
        }
    });
}

function handleFileSelect(files) {
    if (!files || files.length === 0) return;
    
    const validFiles = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.csv'));
    if (validFiles.length === 0) {
        showToast('error', 'Invalid File', 'Please upload CSV files only.');
        return;
    }

    state.selectedFiles = validFiles;
    elements.uploadPrompt.style.display = 'none';
    elements.uploadFileSelected.style.display = 'flex';
    elements.selectedFileName.textContent = validFiles.length === 1 ? validFiles[0].name : `${validFiles.length} files selected`;
    elements.selectedFileSize.textContent = formatFileSize(validFiles.reduce((sum, f) => sum + f.size, 0));
    elements.processBtn.disabled = false;

    detectFiles(validFiles);
}

async function detectFiles(files, append = false) {
    if (!append) {
        state.detectedReports = [];
    }
    for (const file of files) {
        const result = await api.ingestFile(file);
        state.detectedReports.push({
            file: file,
            exchange: result.success && result.data ? result.data.exchange : 'unknown',
            report_type: result.success && result.data ? result.data.report_type : 'unknown',
            confidence: result.success && result.data ? result.data.confidence : 0,
            rows: result.success && result.data ? result.data.rows || 0 : 0,
            warnings: result.success && result.data ? result.data.warnings || [] : []
        });
    }

    if (state.detectedReports.length > 0) {
        const primary = state.detectedReports[0];
        state.detectedExchange = primary.exchange;
        state.transactionCount = primary.rows;
        const detectEl = document.getElementById('detected-exchange');
        if (detectEl) {
            detectEl.textContent = `Detected exchange: ${primary.exchange}${primary.report_type ? ' (' + primary.report_type + ')' : ''}`;
            detectEl.style.display = 'block';
        }
    }

    updateUploadedReportsList();
    updateCoverageGuidance();
    validatePlan();
}

function resetUpload() {
    state.selectedFiles = [];
    state.detectedExchange = null;
    state.detectedReports = [];
    state.transactionCount = 0;
    state.planValidation = null;
    state.reportReadiness = null;
    elements.fileInput.value = '';
    elements.uploadPrompt.style.display = 'flex';
    elements.uploadFileSelected.style.display = 'none';
    elements.uploadedReports.style.display = 'none';
    elements.reportsList.innerHTML = '';
    elements.readinessSection.style.display = 'none';
    elements.coverageGuidance.style.display = 'none';
    elements.coverageGuidance.innerHTML = '';
    elements.processBtn.disabled = true;
    const detectEl = document.getElementById('detected-exchange');
    if (detectEl) {
        detectEl.style.display = 'none';
        detectEl.textContent = '';
    }
    const validationEl = document.getElementById('plan-validation');
    if (validationEl) {
        validationEl.className = 'plan-validation';
        validationEl.innerHTML = '';
    }
    const summaryEl = document.getElementById('upload-plan-summary');
    if (summaryEl) {
        summaryEl.style.display = 'none';
    }
}

function addMoreFiles() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.csv';
    input.multiple = true;
    input.onchange = async (e) => {
        if (e.target.files.length > 0) {
            const newFiles = Array.from(e.target.files).filter(f => f.name.toLowerCase().endsWith('.csv'));
            if (newFiles.length > 0) {
                state.selectedFiles = [...state.selectedFiles, ...newFiles];
                elements.selectedFileName.textContent = `${state.selectedFiles.length} files selected`;
                elements.selectedFileSize.textContent = formatFileSize(state.selectedFiles.reduce((sum, f) => sum + f.size, 0));
                elements.processBtn.disabled = false;

                await detectFiles(newFiles, true);
            }
        }
    };
    input.click();
}

function updateUploadedReportsList() {
    if (!elements.reportsList) return;
    
    elements.reportsList.innerHTML = state.selectedFiles.map((file, index) => {
        const report = state.detectedReports[index] || {};
        const exchange = report.exchange || 'Unknown';
        const reportType = report.report_type || 'Unknown';
        return `
            <div class="report-card">
                <div class="report-card-header">
                    <span class="report-card-name">${file.name}</span>
                    <span class="report-card-size">${formatFileSize(file.size)}</span>
                </div>
                <div class="report-card-body">
                    <span class="report-card-status">Detected: ${exchange}${reportType !== 'Unknown' ? ' (' + reportType + ')' : ''}</span>
                    <button class="btn btn-ghost btn-sm" onclick="removeFile(${index})" aria-label="Remove file">Remove</button>
                </div>
            </div>
        `;
    }).join('');
    
    elements.uploadedReports.style.display = 'block';
}

function removeFile(index) {
    state.selectedFiles.splice(index, 1);
    state.detectedReports.splice(index, 1);
    
    if (state.selectedFiles.length === 0) {
        resetUpload();
    } else {
        updateUploadedReportsList();
        updateCoverageGuidance();
        validatePlan();
    }
}

function updateCoverageGuidance() {
    if (!elements.coverageGuidance) return;

    const reports = state.detectedReports;
    const hasTransactionRecord = reports.some(r => r.report_type === 'transaction_record');
    const hasSpotTradeHistory = reports.some(r => r.report_type === 'spot_trade_history');
    const primaryExchange = reports.length > 0 ? reports[0].exchange : '';

    let html = '';

    if (hasTransactionRecord && hasSpotTradeHistory) {
        html = renderCombinedGuidance(primaryExchange);
    } else if (hasTransactionRecord) {
        html = renderSingleReportGuidance(primaryExchange);
    } else {
        elements.coverageGuidance.style.display = 'none';
        elements.coverageGuidance.innerHTML = '';
        return;
    }

    elements.coverageGuidance.innerHTML = html;
    elements.coverageGuidance.style.display = 'block';
}

function renderSingleReportGuidance(exchange) {
    const label = exchange.charAt(0).toUpperCase() + exchange.slice(1);
    return `
        <div class="coverage-section">
            <h3>Your ${label} Transaction Record is ready</h3>
            <p>This report includes account activity, transfers, deposits, withdrawals, fees and other transactions.</p>
        </div>
        <div class="coverage-section coverage-recommendation">
            <h3>For the most complete tax report, add:</h3>
            <div class="coverage-recommendation-body">
                <strong>${label} Spot Trade History</strong>
                <p>Trade-level pricing and values help KryptLedg calculate cost basis, proceeds and realized gains/losses.</p>
                <button class="btn btn-outline btn-sm" onclick="addMoreFiles()">+ Add Spot Trade History</button>
            </div>
        </div>
        <div class="coverage-section">
            <h3>You can continue with this report alone</h3>
            <p>You can still analyze and reconcile the transactions in this report, but some tax calculations may remain <strong>UNRESOLVED</strong> because the Transaction Record may not contain sufficient trade pricing or value information.</p>
        </div>
        <div class="coverage-section">
            <h3>Available with this report</h3>
            <ul class="coverage-list">
                <li>Transaction analysis</li>
                <li>Transaction classification</li>
                <li>Internal transfer detection</li>
                <li>Duplicate detection</li>
                <li>Deposits and withdrawals</li>
                <li>Fees and account activity</li>
                <li>FIFO transaction/lot tracking where supported</li>
                <li>Holdings tracking</li>
                <li>Missing-data identification</li>
                <li>Exceptions and warnings</li>
                <li>Audit trail</li>
                <li>Tax-year reporting</li>
            </ul>
        </div>
        <div class="coverage-section">
            <h3>Add Spot Trade History for more complete tax accounting</h3>
            <p>${label} Spot Trade History provides trade-level information such as prices, quantities and values that can help KryptLedg calculate cost basis, disposal proceeds and realized gains/losses where the source data supports the calculation.</p>
            <ul class="coverage-list">
                <li>Cost basis</li>
                <li>Disposal proceeds</li>
                <li>Realized gains/losses</li>
                <li>Capital gains reporting</li>
            </ul>
        </div>
    `;
}

function renderCombinedGuidance(exchange) {
    const label = exchange.charAt(0).toUpperCase() + exchange.slice(1);
    return `
        <div class="coverage-section coverage-combined">
            <h3>${label} reports ready</h3>
            <div class="coverage-combined-list">
                <div class="coverage-combined-item">
                    <strong>Transaction Record</strong>
                    <p>Account activity, transfers, deposits, withdrawals and fees.</p>
                </div>
                <div class="coverage-combined-item">
                    <strong>Spot Trade History</strong>
                    <p>Trade-level prices, quantities and values.</p>
                </div>
            </div>
            <p>KryptLedg will combine and reconcile these reports, identify overlapping records, prevent duplicate counting, build FIFO cost basis and calculate realized gains/losses where the source data supports the calculation.</p>
        </div>
    `;
}

function showReadiness(status, details) {
    if (!elements.readinessSection) return;
    
    elements.readinessSection.style.display = 'block';
    elements.readinessStatus.textContent = status;
    
    const statusClass = status === 'READY_FOR_REVIEW' ? 'success' : 
                       status === 'REVIEW_REQUIRED' ? 'warning' : 'error';
    elements.readinessStatus.className = `readiness-status ${statusClass}`;
    
    if (details) {
        elements.readinessDetails.innerHTML = Object.entries(details)
            .filter(([key]) => key !== 'reason')
            .map(([key, value]) => `
                <div class="readiness-detail-item">
                    <span class="readiness-detail-label">${key.replace(/_/g, ' ')}</span>
                    <span class="readiness-detail-value">${typeof value === 'boolean' ? (value ? 'Yes' : 'No') : value}</span>
                </div>
            `).join('');
    }
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function safeString(value) {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.join(', ');
    if (value && typeof value === 'object') {
        if (value.detail) return safeString(value.detail);
        try {
            return JSON.stringify(value);
        } catch {
            return '[Object]';
        }
    }
    return value ? String(value) : '';
}

// ============================================
// Process
// ============================================

async function processFile() {
    if (!state.selectedFiles || state.selectedFiles.length === 0) return;
    if (state.planValidation === 'over_limit') {
        showToast('error', 'Plan Limit Exceeded', 'Please upgrade your plan to process this file.');
        return;
    }

    const timezone = document.getElementById('timezone-select')?.value || '';
    const plan = state.selectedPlan || 'free';
    const accounting = plan === 'standard' || plan === 'complete';

    navigateTo('processing');
    elements.processingTitle.textContent = 'Processing your reports...';
    elements.processingStatus.textContent = 'Uploading and analyzing reports...';
    elements.progressFill.style.width = '0%';

    try {
        const result = await api.processFiles(state.selectedFiles, timezone, accounting, plan);

        elements.progressFill.style.width = '100%';

        if (result.success) {
            state.results = result.data;
            state.reportReadiness = {
                status: result.data.readiness_status,
                details: result.data.readiness_details
            };
            elements.processingTitle.textContent = 'Analysis complete';
            elements.processingStatus.textContent = 'Preparing results...';

            setTimeout(() => {
                try {
                    renderResults(result.data);
                    navigateTo('results');

                    if (result.partial) {
                        showToast('warning', 'Partial Success', 'Some transactions could not be processed. Check the Exceptions tab for details.');
                    } else {
                        showToast('success', 'Success', 'Your report has been processed successfully.');
                    }
                } catch (error) {
                    console.error('Results rendering failed:', error);
                    const errorMessage = error && error.message ? error.message : 'Could not display results. Please try again or contact support.';
                    showToast('error', 'Display Error', errorMessage);
                    navigateTo('upload');
                }
            }, 500);
        } else {
            console.error('Processing API error:', result.status, result.error, result.data);
            const rawError = result.error || result.data || 'Unknown error';
            const errorMessage = safeString(rawError);
            const displayMessage = result.status ? `Error ${result.status}: ${errorMessage}` : errorMessage;
            elements.processingTitle.textContent = 'Processing failed';
            elements.processingStatus.textContent = displayMessage;
            elements.progressFill.style.width = '0%';

            showToast('error', 'Processing Failed', displayMessage);

            setTimeout(() => {
                navigateTo('upload');
            }, 2000);
        }
    } catch (error) {
        console.error('Processing failed:', error);
        const message = error && typeof error === 'object' && error.message ? error.message : 'An unexpected error occurred.';
        elements.processingTitle.textContent = 'Processing failed';
        elements.processingStatus.textContent = safeString(message);
        elements.progressFill.style.width = '0%';

        showToast('error', 'Processing Failed', safeString(message + ' Please try again.'));

        setTimeout(() => {
            navigateTo('upload');
        }, 2000);
    }
}

// ============================================
// Tabs
// ============================================

function setupTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
            document.getElementById(`tab-${tabName}`)?.classList.add('active');
            state.activeTab = tabName;
        });
    });
}

function setupSubTabs() {
    document.querySelectorAll('.sub-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const subtabName = tab.dataset.subtab;
            document.querySelectorAll('.sub-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            document.querySelectorAll('.sub-tab-pane').forEach(pane => pane.classList.remove('active'));
            document.getElementById(`subtab-${subtabName}`)?.classList.add('active');
            state.activeSubTab = subtabName;
        });
    });
}

function setupTaxYearFilter() {
    const select = document.getElementById('tax-year-select');
    if (select) {
        select.addEventListener('change', () => {
            const year = select.value;
            if (state.results) {
                state.filteredTransactions = filterByTaxYear(state.results.transactions || [], year);
                state.txPage = 1;
                renderTransactionsTable(state.filteredTransactions);
                if (state.activeTab !== 'transactions') {
                    document.querySelector('[data-tab="transactions"]')?.click();
                }
            }
        });
    }
}

function filterByTaxYear(transactions, year) {
    if (!year) return transactions;
    return transactions.filter(tx => {
        const d = new Date(tx.timestamp);
        return d.getFullYear().toString() === year;
    });
}

// ============================================
// Search
// ============================================

function setupSearch() {
    const searchInput = document.getElementById('transaction-search');
    const typeFilter = document.getElementById('type-filter');

    const filterTransactions = () => {
        const searchTerm = searchInput?.value?.toLowerCase() || '';
        const typeValue = typeFilter?.value || '';
        const allTransactions = state.results?.transactions || [];
        
        let filtered = allTransactions;
        if (searchTerm || typeValue) {
            filtered = allTransactions.filter(tx => {
                const text = [
                    tx.transaction_type, tx.side, tx.asset, tx.wallet, tx.timestamp
                ].filter(Boolean).join(' ').toLowerCase();
                const typeMatch = !typeValue || (tx.transaction_type || '').toUpperCase() === typeValue;
                const searchMatch = !searchTerm || text.includes(searchTerm);
                return typeMatch && searchMatch;
            });
        }
        
        state.filteredTransactions = filtered;
        state.txPage = 1;
        renderTransactionsTable(filtered);
    };

    searchInput?.addEventListener('input', filterTransactions);
    typeFilter?.addEventListener('change', filterTransactions);
}

// ============================================
// FAQ Accordion
// ============================================

function toggleFaq(item) {
    const answer = item.querySelector('.faq-answer');
    const icon = item.querySelector('.faq-question svg');
    const isOpen = item.classList.contains('active');

    // Close all
    document.querySelectorAll('.faq-item').forEach(faq => {
        faq.classList.remove('active');
        const a = faq.querySelector('.faq-answer');
        const i = faq.querySelector('.faq-question svg');
        if (a) a.style.display = 'none';
        if (i) i.style.transform = 'rotate(0deg)';
    });

    // Open clicked if it wasn't open
    if (!isOpen) {
        item.classList.add('active');
        if (answer) answer.style.display = 'block';
        if (icon) icon.style.transform = 'rotate(180deg)';
    }
}

// ============================================
// Drawer
// ============================================

function openDrawer(tx) {
    state.currentTx = tx;
    const drawer = document.getElementById('tx-drawer');
    const overlay = document.getElementById('drawer-overlay');
    const body = document.getElementById('drawer-body');

    const fields = [
        ['Transaction ID', safeStr(tx.transaction_id)],
        ['Type', safeStr(tx.transaction_type)],
        ['Side', safeStr(tx.side)],
        ['Asset', safeStr(tx.asset)],
        ['Quantity', tx.quantity !== null && tx.quantity !== undefined ? fmtNumber(tx.quantity) : '<span class="unresolved">UNRESOLVED</span>'],
        ['Price', tx.price !== null && tx.price !== undefined ? fmtCurrency(tx.price, tx.price_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'],
        ['Value', tx.value !== null && tx.value !== undefined ? fmtCurrency(tx.value, tx.value_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'],
        ['Fee', tx.fee !== null && tx.fee !== undefined ? fmtCurrency(tx.fee, tx.fee_asset || 'USD') : '<span class="unresolved">UNRESOLVED</span>'],
        ['Wallet', safeStr(tx.wallet)],
        ['Timestamp', fmtDate(tx.timestamp)],
        ['Source', safeStr(tx.source)],
        ['Notes', safeStr(tx.notes) || '-']
    ];

    body.innerHTML = fields.map(([label, value]) => `
        <div class="drawer-field">
            <span class="drawer-label">${label}</span>
            <span class="drawer-value">${value}</span>
        </div>
    `).join('');

    drawer.classList.add('active');
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
}

function closeDrawer() {
    const drawer = document.getElementById('tx-drawer');
    const overlay = document.getElementById('drawer-overlay');
    drawer.classList.remove('active');
    overlay.classList.remove('active');
    document.body.style.overflow = '';
    state.currentTx = null;
}

// ============================================
// Export
// ============================================

function exportResults(format) {
    if (!state.results) {
        showToast('error', 'No Data', 'No results to export.');
        return;
    }

    const taxYear = elements.taxYearSelect?.value || '';
    const plan = state.selectedPlan || 'free';
    const timezone = document.getElementById('timezone-select')?.value || '';

    if (!state.selectedFiles || state.selectedFiles.length === 0) {
        showToast('error', 'Export Failed', 'No file available for export. Please re-upload your report.');
        return;
    }

    const primaryFile = state.selectedFiles[0];

    if (format === 'csv') {
        api.exportResults(state.results, 'csv', taxYear, primaryFile, plan, timezone).then(result => {
            if (result.success) {
                showToast('success', 'Export Complete', 'Your report is downloading.');
            } else {
                showToast('error', 'Export Failed', result.error);
            }
        });
        return;
    }

    if (format === 'pdf') {
        api.exportResults(state.results, 'pdf', taxYear, primaryFile, plan, timezone).then(result => {
            if (result.success) {
                showToast('success', 'Export Complete', 'Your PDF report is downloading.');
            } else {
                showToast('error', 'Export Failed', result.error);
            }
        });
        return;
    }
}

// ============================================
// Skeleton Loaders & Empty States
// ============================================

function showTableSkeleton(tableId, cols, rows = 5) {
    const tbody = document.querySelector(`#${tableId}`);
    if (!tbody) return;
    tbody.innerHTML = Array(rows).fill(0).map(() => `
        <tr>
            ${Array(cols).fill(0).map(() => `<td><div class="skeleton skeleton-text" style="width:${60 + Math.random() * 40}%"></div></td>`).join('')}
        </tr>
    `).join('');
}

function showEmptyState(tableId, message = 'No data available') {
    const tbody = document.querySelector(`#${tableId}`);
    if (!tbody) return;
    const cols = tbody.parentElement.querySelector('thead tr')?.children.length || 1;
    tbody.innerHTML = `<tr><td colspan="${cols}" class="empty-state">${message}</td></tr>`;
}

function showSectionSkeleton(containerId, lines = 3) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = Array(lines).fill(0).map(() => `
        <div class="skeleton skeleton-text" style="width:${70 + Math.random() * 30}%"></div>
    `).join('');
}

function showToast(type, title, message) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <div class="toast-content">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${message}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M12 4L4 12M4 4L12 12" stroke="currentColor" stroke-width="2"/></svg>
        </button>
    `;
    elements.toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// ============================================
// Render Results
// ============================================

function renderResults(data) {
    try {
        if (data.reports && data.reports.length > 0) {
            const reportNames = data.reports.map(r => `${r.exchange} - ${r.report_type}`).join(', ');
            document.getElementById('results-source').textContent = reportNames;
        } else {
            document.getElementById('results-source').textContent = `${safeStr(data.source) || 'Unknown'} - ${safeStr(data.report_type) || 'Unknown Report'}`;
        }

        const summary = data.summary || {};
        document.getElementById('ov-total').textContent = data.transaction_count || 0;
        document.getElementById('ov-trades').textContent = summary.trades || 0;
        document.getElementById('ov-transfers').textContent = summary.transfers || 0;
        document.getElementById('ov-deposits').textContent = summary.deposits || 0;
        document.getElementById('ov-withdrawals').textContent = summary.withdrawals || 0;
        document.getElementById('ov-fees').textContent = summary.fees || 0;

        const acct = data.accounting_result || {};
        const safeAcct = {
            summary: acct.summary || {},
            events: acct.events || [],
            lots: acct.lots || [],
            consumptions: acct.consumptions || [],
            realized_pnl: acct.realized_pnl || [],
            warnings: acct.warnings || [],
            errors: acct.errors || []
        };
        const acctSummary = safeAcct.summary || {};
        document.getElementById('ov-events').textContent = acctSummary.total_events || 0;
        document.getElementById('ov-acquisitions').textContent = acctSummary.acquisition_events || 0;
        document.getElementById('ov-disposals').textContent = acctSummary.disposal_events || 0;
        document.getElementById('ov-lots').textContent = acctSummary.total_lots_created || 0;

        const sections = [
            ['P&L Card', () => renderPnLCard(safeAcct)],
            ['Transactions', () => renderTransactionsTable(data.transactions || [])],
            ['Reconciliation', () => renderReconciliation(data)],
            ['Accounting', () => renderAccounting(safeAcct)],
            ['Tax Summary', () => renderTaxSummary(safeAcct)],
            ['Holdings', () => renderHoldings(safeAcct)],
            ['Missing Basis', () => renderMissingBasis(safeAcct)],
            ['Exceptions', () => renderExceptions(data, safeAcct)],
            ['Audit Trail', () => renderAuditTrail(safeAcct)]
        ];

        sections.forEach(([name, render]) => {
            try {
                render();
            } catch (sectionError) {
                console.error(`renderResults section failed [${name}]:`, sectionError);
                showToast('warning', 'Display Issue', `${name} section could not be rendered. Other sections are still available.`);
            }
        });
    } catch (error) {
        console.error('renderResults failed:', error);
        const errorMessage = error && error.message ? error.message : 'Could not display results. Please try again or contact support.';
        showToast('error', 'Display Error', errorMessage);
        setTimeout(() => navigateTo('upload'), 2000);
    }
}

// ============================================
// P&L Card
// ============================================

function renderPnLCard(accountingResult) {
    try {
        const pnlCard = document.getElementById('pnl-card');
        if (!accountingResult || !accountingResult.summary || Object.keys(accountingResult.summary || {}).length === 0) {
            if (pnlCard) pnlCard.style.display = 'none';
            return;
        }

        if (pnlCard) pnlCard.style.display = 'block';
        const summary = accountingResult.summary || {};
        const totalPnL = summary.total_realized_pnl;
        const currency = (summary.pnl_currency || 'USD').toString().toUpperCase();

        const pnlTotalEl = document.getElementById('pnl-total');
        const pnlBreakdownEl = document.getElementById('pnl-breakdown');
        
        if (!pnlTotalEl || !pnlBreakdownEl) return;

        if (totalPnL !== null && totalPnL !== undefined && safeStr(totalPnL) !== null) {
            const pnlValue = safeNum(totalPnL);
            pnlTotalEl.innerHTML = (pnlValue >= 0 ? '+' : '') + fmtCurrency(pnlValue, currency);
            pnlTotalEl.className = 'pnl-value ' + (pnlValue >= 0 ? 'positive' : 'negative');
        } else {
            pnlTotalEl.innerHTML = '<span class="unresolved-pill">UNRESOLVED</span>';
            pnlTotalEl.className = 'pnl-value';
        }

        pnlBreakdownEl.innerHTML = '';

        const realizedPnl = accountingResult.realized_pnl || [];
        if (realizedPnl.length > 0) {
            realizedPnl.forEach(pnl => {
                const assetEl = document.createElement('div');
                assetEl.className = 'pnl-asset';
                const value = safeNum(pnl.total_realized_pnl);
                const pnlCurrency = (pnl.currency || 'USD').toString().toUpperCase();
                assetEl.innerHTML = `
                    <span class="pnl-asset-name">${safeStr(pnl.asset) || 'UNKNOWN'}</span>
                    <span class="pnl-asset-value ${value !== null && value >= 0 ? 'positive' : 'negative'}">
                        ${value !== null && value >= 0 ? '+' : ''}${fmtCurrency(value, pnlCurrency)}
                    </span>
                `;
                pnlBreakdownEl.appendChild(assetEl);
            });
        }
    } catch (error) {
        console.error('renderPnLCard failed:', error);
        const pnlCard = document.getElementById('pnl-card');
        if (pnlCard) pnlCard.style.display = 'none';
    }
}

// ============================================
// Transactions
// ============================================

function renderTransactionsTable(transactions) {
    try {
        state.filteredTransactions = transactions || [];
        const tbody = document.getElementById('transactions-body');
        tbody.innerHTML = '';

        if (!transactions || transactions.length === 0) {
            showEmptyState('transactions-body', 'No transactions found');
            document.getElementById('pagination-info').textContent = 'Showing 0 transactions';
            renderPagination(0);
            return;
        }

        const pageSize = state.txPageSize;
        const totalPages = Math.max(1, Math.ceil(transactions.length / pageSize));
        if (state.txPage > totalPages) state.txPage = totalPages;
        const start = (state.txPage - 1) * pageSize;
        const pageData = transactions.slice(start, start + pageSize);

        pageData.forEach(tx => {
            const row = document.createElement('tr');
            row.style.cursor = 'pointer';
            row.title = 'Click for details';
            const sideClass = tx.side === 'BUY' ? 'badge-buy' : tx.side === 'SELL' ? 'badge-sell' : '';
            row.innerHTML = `
                <td>${fmtDate(tx.timestamp)}</td>
                <td>${fmtBadge(tx.transaction_type)}</td>
                <td>${tx.side ? `<span class="badge ${sideClass}">${tx.side}</span>` : '-'}</td>
                <td>${safeStr(tx.asset) || '-'}</td>
                <td>${fmtNumber(tx.quantity)}</td>
                <td>${tx.price !== null && tx.price !== undefined ? fmtCurrency(tx.price, tx.price_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                <td>${tx.value !== null && tx.value !== undefined ? fmtCurrency(tx.value, tx.value_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                <td>${tx.fee !== null && tx.fee !== undefined ? fmtCurrency(tx.fee, tx.fee_asset || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                <td>${safeStr(tx.wallet) || '-'}</td>
            `;
            row.addEventListener('click', () => openDrawer(tx));
            tbody.appendChild(row);
        });

        const showing = Math.min(start + pageData.length, transactions.length);
        document.getElementById('pagination-info').textContent = `Showing ${start + 1}-${showing} of ${transactions.length} transactions`;
        renderPagination(totalPages);
    } catch (error) {
        console.error('renderTransactionsTable failed:', error);
    }
}

function renderPagination(totalPages) {
    const container = document.getElementById('pagination-controls');
    if (!container) return;

    let html = `
        <button class="pagination-btn" onclick="goToPage(${state.txPage - 1})" ${state.txPage <= 1 ? 'disabled' : ''}>Previous</button>
    `;

    const maxVisible = 5;
    let startPage = Math.max(1, state.txPage - Math.floor(maxVisible / 2));
    let endPage = Math.min(totalPages, startPage + maxVisible - 1);
    if (endPage - startPage + 1 < maxVisible) startPage = Math.max(1, endPage - maxVisible + 1);

    if (startPage > 1) {
        html += `<button class="pagination-btn" onclick="goToPage(1)">1</button>`;
        if (startPage > 2) html += `<span style="color:var(--primary-400)">...</span>`;
    }

    for (let i = startPage; i <= endPage; i++) {
        html += `<button class="pagination-btn ${i === state.txPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }

    if (endPage < totalPages) {
        if (endPage < totalPages - 1) html += `<span style="color:var(--primary-400)">...</span>`;
        html += `<button class="pagination-btn" onclick="goToPage(${totalPages})">${totalPages}</button>`;
    }

    html += `
        <button class="pagination-btn" onclick="goToPage(${state.txPage + 1})" ${state.txPage >= totalPages ? 'disabled' : ''}>Next</button>
    `;

    container.innerHTML = html;
}

function goToPage(page) {
    const totalPages = Math.max(1, Math.ceil((state.filteredTransactions.length || 0) / state.txPageSize));
    if (page < 1 || page > totalPages) return;
    state.txPage = page;
    renderTransactionsTable(state.filteredTransactions);
}

// ============================================
// Reconciliation
// ============================================

function renderReconciliation(data) {
    try {
        const transfersContent = document.getElementById('transfers-content');
        const transferMatches = data.transfer_matches?.matches || [];
        document.getElementById('transfer-count').textContent = `${transferMatches.length} matched`;

        if (transferMatches.length > 0) {
            transfersContent.innerHTML = transferMatches.map(match => `
                <div class="recon-item">
                    <div class="recon-item-header">
                        <span class="recon-item-title">${safeStr(match.asset) || 'UNKNOWN'} - ${fmtNumber(match.quantity)}</span>
                        <span class="recon-item-detail">${fmtDate(match.timestamp)}</span>
                    </div>
                    <div class="recon-item-detail">From: ${safeStr(match.source_account) || 'Unknown'} → To: ${safeStr(match.destination_account) || 'Unknown'}</div>
                    <div class="reasons-list">${(match.reasons || []).map(r => `<span class="reason-tag">${safeStr(r) || r}</span>`).join('')}</div>
                </div>
            `).join('');
        } else {
            transfersContent.innerHTML = '<p class="empty-state">No internal transfers detected</p>';
        }

        const duplicatesContent = document.getElementById('duplicates-content');
        const duplicateGroups = data.duplicate_findings?.groups || [];
        document.getElementById('duplicate-count').textContent = `${duplicateGroups.length} found`;

        if (duplicateGroups.length > 0) {
            duplicatesContent.innerHTML = duplicateGroups.map(group => `
                <div class="recon-item">
                    <div class="recon-item-header">
                        <span class="recon-item-title">${safeStr(group.classification)?.replace(/_/g, ' ') || 'UNKNOWN'}</span>
                        <span class="recon-item-detail">Score: ${group.score !== undefined ? group.score : 'UNRESOLVED'}</span>
                    </div>
                    <div class="recon-item-detail">${group.transaction_ids?.length || 0} transactions: ${(group.transaction_ids || []).slice(0, 3).join(', ')}${group.transaction_ids?.length > 3 ? '...' : ''}</div>
                    <div class="reasons-list">${(group.reasons || []).map(r => `<span class="reason-tag">${safeStr(r) || r}</span>`).join('')}</div>
                </div>
            `).join('');
        } else {
            duplicatesContent.innerHTML = '<p class="empty-state">No duplicates detected</p>';
        }

        const convertsContent = document.getElementById('converts-content');
        const convertMatches = data.convert_matches?.matches || [];
        document.getElementById('convert-count').textContent = `${convertMatches.length} found`;

        if (convertMatches.length > 0) {
            convertsContent.innerHTML = convertMatches.map(match => `
                <div class="recon-item">
                    <div class="recon-item-header">
                        <span class="recon-item-title">${safeStr(match.input_asset) || 'UNKNOWN'} → ${safeStr(match.output_asset) || 'UNKNOWN'}</span>
                        <span class="recon-item-detail">${fmtDate(match.timestamp)}</span>
                    </div>
                    <div class="recon-item-detail">Sold: ${fmtNumber(match.input_quantity)} ${safeStr(match.input_asset) || 'UNKNOWN'} → Bought: ${fmtNumber(match.output_quantity)} ${safeStr(match.output_asset) || 'UNKNOWN'}</div>
                    <div class="reasons-list">${(match.reasons || []).map(r => `<span class="reason-tag">${safeStr(r) || r}</span>`).join('')}</div>
                </div>
            `).join('');
        } else {
            convertsContent.innerHTML = '<p class="empty-state">No convert events detected</p>';
        }
    } catch (error) {
        console.error('renderReconciliation failed:', error);
    }
}

// ============================================
// Accounting (Events, Lots, Consumptions)
// ============================================

function renderAccounting(accountingResult) {
    try {
        const summaryEvents = document.getElementById('acct-events');
        const summaryAcquisitions = document.getElementById('acct-acquisitions');
        const summaryDisposals = document.getElementById('acct-disposals');
        const summaryLots = document.getElementById('acct-lots');
        const accountingBody = document.getElementById('accounting-body');
        const lotsBody = document.getElementById('lots-body');
        const consumptionsBody = document.getElementById('consumptions-body');

        if (!accountingResult || !accountingResult.summary || Object.keys(accountingResult.summary || {}).length === 0) {
            if (summaryEvents) summaryEvents.textContent = '0';
            if (summaryAcquisitions) summaryAcquisitions.textContent = '0';
            if (summaryDisposals) summaryDisposals.textContent = '0';
            if (summaryLots) summaryLots.textContent = '0';
            showEmptyState('accounting-body', 'No accounting data available');
            showEmptyState('lots-body', 'No lots data available');
            showEmptyState('consumptions-body', 'No consumptions data available');
            return;
        }

        const summary = accountingResult.summary || {};
        if (summaryEvents) summaryEvents.textContent = summary.total_events || 0;
        if (summaryAcquisitions) summaryAcquisitions.textContent = summary.acquisition_events || 0;
        if (summaryDisposals) summaryDisposals.textContent = summary.disposal_events || 0;
        if (summaryLots) summaryLots.textContent = summary.total_lots_created || 0;

        const events = accountingResult.events || [];
        if (events.length > 0 && accountingBody) {
            accountingBody.innerHTML = events.map(event => `
                <tr>
                    <td>${fmtDate(event.timestamp)}</td>
                    <td>${fmtBadge(event.event_type)}</td>
                    <td>${safeStr(event.asset) || '-'}</td>
                    <td>${fmtNumber(event.quantity)}</td>
                    <td>${event.cost_basis !== null && event.cost_basis !== undefined ? fmtCurrency(event.cost_basis, event.cost_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${event.proceeds !== null && event.proceeds !== undefined ? fmtCurrency(event.proceeds, event.proceeds_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${event.realized_pnl !== null && event.realized_pnl !== undefined ? (safeNum(event.realized_pnl) >= 0 ? '<span class="text-positive">+' : '<span class="text-negative">') + fmtCurrency(event.realized_pnl, event.pnl_currency || 'USD') + '</span>' : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${safeStr(event.source_transaction_id) || '-'}</td>
                </tr>
            `).join('');
        } else if (accountingBody) {
            showEmptyState('accounting-body', 'No events found');
        }

        const lots = accountingResult.lots || [];
        if (lots.length > 0 && lotsBody) {
            lotsBody.innerHTML = lots.map(lot => `
                <tr>
                    <td>${safeStr(lot.lot_id) || '-'}</td>
                    <td>${safeStr(lot.asset) || '-'}</td>
                    <td>${fmtNumber(lot.acquired_quantity)}</td>
                    <td>${fmtNumber(lot.remaining_quantity)}</td>
                    <td>${lot.unit_cost !== null && lot.unit_cost !== undefined ? fmtCurrency(lot.unit_cost, 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${fmtDate(lot.acquired_timestamp)}</td>
                    <td>${safeStr(lot.source_transaction_id) || '-'}</td>
                </tr>
            `).join('');
        } else if (lotsBody) {
            showEmptyState('lots-body', 'No lots found');
        }

        const consumptions = accountingResult.consumptions || [];
        if (consumptions.length > 0 && consumptionsBody) {
            consumptionsBody.innerHTML = consumptions.map(c => `
                <tr>
                    <td>${safeStr(c.consumption_id) || '-'}</td>
                    <td>${safeStr(c.lot_id) || '-'}</td>
                    <td>${safeStr(c.disposal_event_id) || '-'}</td>
                    <td>${safeStr(c.asset) || '-'}</td>
                    <td>${fmtNumber(c.quantity_consumed)}</td>
                    <td>${c.unit_cost !== null && c.unit_cost !== undefined ? fmtCurrency(c.unit_cost, 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${fmtCurrency(c.cost_allocated, 'USD')}</td>
                    <td>${fmtCurrency(c.disposal_proceeds, 'USD')}</td>
                    <td>${fmtCurrency(c.realized_pnl, 'USD')}</td>
                </tr>
            `).join('');
        } else if (consumptionsBody) {
            showEmptyState('consumptions-body', 'No consumptions found');
        }
    } catch (error) {
        console.error('renderAccounting failed:', error);
    }
}

// ============================================
// Tax Summary (P&L, Capital Gains, Income)
// ============================================

function renderTaxSummary(accountingResult) {
    try {
        const pnlTotalEl = document.getElementById('tax-pnl-total');
        const pnlBreakdownEl = document.getElementById('tax-pnl-breakdown');
        const pnlBadge = document.getElementById('pnl-currency-badge');

        if (!accountingResult || !accountingResult.summary || Object.keys(accountingResult.summary || {}).length === 0) {
            if (pnlTotalEl) pnlTotalEl.innerHTML = '<span class="unresolved-pill">UNRESOLVED</span>';
            if (pnlBreakdownEl) pnlBreakdownEl.innerHTML = '';
            if (pnlBadge) pnlBadge.textContent = 'USD';
            showEmptyState('capital-gains-body', 'No capital gains data');
            showEmptyState('income-body', 'No income data');
            return;
        }

        const realizedPnl = accountingResult.realized_pnl || [];
        const totalRealizedPnl = accountingResult.summary?.total_realized_pnl;
        const pnlCurrency = (accountingResult.summary?.pnl_currency || 'USD').toString().toUpperCase();

        if (pnlBadge) pnlBadge.textContent = pnlCurrency;

        if (totalRealizedPnl !== null && totalRealizedPnl !== undefined && safeStr(totalRealizedPnl) !== null) {
            const pnlValue = safeNum(totalRealizedPnl);
            pnlTotalEl.innerHTML = (pnlValue >= 0 ? '+' : '') + fmtCurrency(pnlValue, pnlCurrency);
            pnlTotalEl.className = 'pnl-value ' + (pnlValue >= 0 ? 'positive' : 'negative');
        } else {
            pnlTotalEl.innerHTML = '<span class="unresolved-pill">UNRESOLVED</span>';
            pnlTotalEl.className = 'pnl-value';
        }

        pnlBreakdownEl.innerHTML = '';
        if (realizedPnl.length > 0) {
            realizedPnl.forEach(pnl => {
                const el = document.createElement('div');
                el.className = 'pnl-asset';
                const value = safeNum(pnl.total_realized_pnl);
                const c = (pnl.currency || 'USD').toString().toUpperCase();
                el.innerHTML = `
                    <span class="pnl-asset-name">${safeStr(pnl.asset) || 'UNKNOWN'}</span>
                    <span class="pnl-asset-value ${value !== null && value >= 0 ? 'positive' : 'negative'}">
                        ${value !== null && value >= 0 ? '+' : ''}${fmtCurrency(value, c)}
                    </span>
                `;
                pnlBreakdownEl.appendChild(el);
            });
        }

        // Capital Gains
        const events = accountingResult.events || [];
        const disposals = events.filter(e => e.event_type === 'DISPOSAL');
        const capitalGainsBody = document.getElementById('capital-gains-body');
        if (disposals.length > 0) {
            capitalGainsBody.innerHTML = disposals.map(e => `
                <tr>
                    <td>${safeStr(e.event_id) || '-'}</td>
                    <td>${fmtDate(e.timestamp)}</td>
                    <td>${safeStr(e.asset) || '-'}</td>
                    <td>${fmtNumber(e.quantity)}</td>
                    <td>${e.cost_basis !== null && e.cost_basis !== undefined ? fmtCurrency(e.cost_basis, e.cost_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${e.proceeds !== null && e.proceeds !== undefined ? fmtCurrency(e.proceeds, e.proceeds_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${e.realized_pnl !== null && e.realized_pnl !== undefined ? (safeNum(e.realized_pnl) >= 0 ? '<span class="text-positive">+' : '<span class="text-negative">') + fmtCurrency(e.realized_pnl, e.pnl_currency || 'USD') + '</span>' : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${fmtBadge(e.event_type)}</td>
                </tr>
            `).join('');
        } else {
            showEmptyState('capital-gains-body', 'No capital gains data');
        }

        // Income
        const acquisitions = events.filter(e => e.event_type === 'ACQUISITION' || e.event_type === 'REWARD' || e.event_type === 'FEE');
        const incomeBody = document.getElementById('income-body');
        if (acquisitions.length > 0) {
            incomeBody.innerHTML = acquisitions.map(e => `
                <tr>
                    <td>${safeStr(e.event_id) || '-'}</td>
                    <td>${fmtDate(e.timestamp)}</td>
                    <td>${safeStr(e.asset) || '-'}</td>
                    <td>${fmtNumber(e.quantity)}</td>
                    <td>${e.cost_basis !== null && e.cost_basis !== undefined ? fmtCurrency(e.cost_basis, e.cost_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${fmtBadge(e.event_type)}</td>
                </tr>
            `).join('');
        } else {
            showEmptyState('income-body', 'No income data');
        }
    } catch (error) {
        console.error('renderTaxSummary failed:', error);
    }
}

// ============================================
// Holdings
// ============================================

function renderHoldings(accountingResult) {
    try {
        const lots = accountingResult.lots || [];
        const holdingsBody = document.getElementById('holdings-body');

        // Aggregate holdings by asset
        const holdingsMap = {};
        lots.forEach(lot => {
            const asset = safeStr(lot.asset) || 'UNKNOWN';
            if (!holdingsMap[asset]) {
                holdingsMap[asset] = { remainingQty: 0, lotCount: 0, totalCost: 0, unitCosts: [] };
            }
            holdingsMap[asset].remainingQty += safeNum(lot.remaining_quantity) || 0;
            holdingsMap[asset].lotCount++;
            if (lot.unit_cost !== null && lot.unit_cost !== undefined) {
                holdingsMap[asset].totalCost += safeNum(lot.unit_cost) * (safeNum(lot.remaining_quantity) || 0);
                holdingsMap[asset].unitCosts.push(safeNum(lot.unit_cost));
            }
        });

        const holdings = Object.entries(holdingsMap).filter(([_, h]) => h.remainingQty > 0.000001);

        if (holdings.length > 0) {
            holdingsBody.innerHTML = holdings.map(([asset, h]) => {
                const avgCost = h.unitCosts.length > 0 ? h.unitCosts.reduce((a, b) => a + b, 0) / h.unitCosts.length : null;
                return `
                    <tr>
                        <td>${asset}</td>
                        <td>${fmtNumber(h.remainingQty)}</td>
                        <td>${h.lotCount}</td>
                        <td>${h.totalCost > 0 ? fmtCurrency(h.totalCost) : '<span class="unresolved">UNRESOLVED</span>'}</td>
                        <td>${avgCost !== null ? fmtCurrency(avgCost) : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    </tr>
                `;
            }).join('');
        } else {
            showEmptyState('holdings-body', 'No holdings found');
        }
    } catch (error) {
        console.error('renderHoldings failed:', error);
    }
}

// ============================================
// Missing Cost Basis
// ============================================

function renderMissingBasis(accountingResult) {
    try {
        const events = accountingResult?.events || [];
        const missingBasis = events.filter(e => e.event_type === 'DISPOSAL' && (e.cost_basis === null || e.cost_basis === undefined));
        const missingBody = document.getElementById('missing-basis-body');

        if (missingBasis.length > 0) {
            missingBody.innerHTML = missingBasis.map(e => `
                <tr>
                    <td>${safeStr(e.event_id) || '-'}</td>
                    <td>${fmtDate(e.timestamp)}</td>
                    <td>${safeStr(e.asset) || '-'}</td>
                    <td>${fmtNumber(e.quantity)}</td>
                    <td>${e.proceeds !== null && e.proceeds !== undefined ? fmtCurrency(e.proceeds, e.proceeds_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${safeStr(e.source_transaction_id) || '-'}</td>
                </tr>
            `).join('');
        } else {
            showEmptyState('missing-basis-body', 'All disposals have cost basis');
        }
    } catch (error) {
        console.error('renderMissingBasis failed:', error);
    }
}

// ============================================
// Exceptions & Review
// ============================================

function groupWarnings(warnings) {
    const groups = {};
    warnings.forEach(w => {
        const key = safeStr(w.code) || safeStr(w.message) || 'general';
        if (!groups[key]) groups[key] = { code: key, items: [], count: 0 };
        groups[key].items.push(w);
        groups[key].count++;
    });
    return Object.values(groups);
}

function renderExceptions(data, accountingResult) {
    try {
        // Processing warnings
        const warnings = data.warnings || [];
        const procWarningsList = document.getElementById('proc-warnings-list');
        document.getElementById('proc-warning-count').textContent = warnings.length;

        if (warnings.length > 0) {
            const groups = groupWarnings(warnings);
            procWarningsList.innerHTML = groups.map(group => `
                <div class="warning-group">
                    <div class="warning-group-header">
                        <span class="warning-group-code">${safeStr(group.code) || 'Warning'}</span>
                        <span class="warning-group-count">${group.count}</span>
                    </div>
                    <div class="warning-group-items">
                        ${group.items.slice(0, 5).map(w => `
                            <div class="warning-item warning">
                                <div class="warning-icon">
                                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 19 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#F59E0B" stroke-width="2"/></svg>
                                </div>
                                <div class="warning-content"><div class="warning-message">${safeStr(w.message || w) || 'UNKNOWN'}</div></div>
                            </div>
                        `).join('')}
                        ${group.items.length > 5 ? `<div class="warning-more">+${group.items.length - 5} more</div>` : ''}
                    </div>
                </div>
            `).join('');
        } else {
            procWarningsList.innerHTML = '<p class="empty-state">No processing warnings</p>';
        }

        // Data quality issues
        const accountingWarnings = accountingResult.warnings || [];
        const qualityIssuesList = document.getElementById('quality-issues-list');
        document.getElementById('quality-issue-count').textContent = accountingWarnings.length;

        if (accountingWarnings.length > 0) {
            const groups = groupWarnings(accountingWarnings);
            qualityIssuesList.innerHTML = groups.map(group => `
                <div class="warning-group">
                    <div class="warning-group-header">
                        <span class="warning-group-code">${safeStr(group.code) || 'Issue'}</span>
                        <span class="warning-group-count">${group.count}</span>
                    </div>
                    <div class="warning-group-items">
                        ${group.items.slice(0, 5).map(w => `
                            <div class="warning-item info">
                                <div class="warning-icon">
                                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 19 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#6366F1" stroke-width="2"/></svg>
                                </div>
                                <div class="warning-content">
                                    <div class="warning-message">${safeStr(w.message) || 'UNKNOWN'}</div>
                                    ${w.source_transaction_id ? `<div class="warning-detail">Source: ${safeStr(w.source_transaction_id)}</div>` : ''}
                                </div>
                            </div>
                        `).join('')}
                        ${group.items.length > 5 ? `<div class="warning-more">+${group.items.length - 5} more</div>` : ''}
                    </div>
                </div>
            `).join('');
        } else {
            qualityIssuesList.innerHTML = '<p class="empty-state">No data quality issues</p>';
        }

        // Errors
        const errors = data.errors || (accountingResult.errors || []);
        const errorsList = document.getElementById('errors-list');
        document.getElementById('error-count').textContent = errors.length;

        if (errors.length > 0) {
            const errorItems = errors.map(e => ({
                code: safeStr(e.code) || safeStr(e.message) || 'error',
                message: safeStr(e.message || e) || 'UNKNOWN',
                source: safeStr(e.source_transaction_id)
            }));
            const groups = groupWarnings(errorItems);
            errorsList.innerHTML = groups.map(group => `
                <div class="warning-group">
                    <div class="warning-group-header">
                        <span class="warning-group-code">${safeStr(group.code) || 'Error'}</span>
                        <span class="warning-group-count">${group.count}</span>
                    </div>
                    <div class="warning-group-items">
                        ${group.items.slice(0, 5).map(w => `
                            <div class="warning-item error">
                                <div class="warning-icon">
                                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 19 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#EF4444" stroke-width="2"/></svg>
                                </div>
                                <div class="warning-content"><div class="warning-message">${w.message}</div></div>
                            </div>
                        `).join('')}
                        ${group.items.length > 5 ? `<div class="warning-more">+${group.items.length - 5} more</div>` : ''}
                    </div>
                </div>
            `).join('');
        } else {
            errorsList.innerHTML = '<p class="empty-state">No errors</p>';
        }
    } catch (error) {
        console.error('renderExceptions failed:', error);
    }
}

// ============================================
// Audit Trail
// ============================================

function renderAuditTrail(accountingResult) {
    try {
        const events = accountingResult?.events || [];
        const auditBody = document.getElementById('audit-body');

        if (events.length > 0) {
            auditBody.innerHTML = events.map(e => `
                <tr>
                    <td>${safeStr(e.event_id) || '-'}</td>
                    <td>${fmtDate(e.timestamp)}</td>
                    <td>${fmtBadge(e.event_type)}</td>
                    <td>${safeStr(e.asset) || '-'}</td>
                    <td>${fmtNumber(e.quantity)}</td>
                    <td>${e.cost_basis !== null && e.cost_basis !== undefined ? fmtCurrency(e.cost_basis, e.cost_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${e.proceeds !== null && e.proceeds !== undefined ? fmtCurrency(e.proceeds, e.proceeds_currency || 'USD') : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${e.realized_pnl !== null && e.realized_pnl !== undefined ? (safeNum(e.realized_pnl) >= 0 ? '<span class="text-positive">+' : '<span class="text-negative">') + fmtCurrency(e.realized_pnl, e.pnl_currency || 'USD') + '</span>' : '<span class="unresolved">UNRESOLVED</span>'}</td>
                    <td>${e.linked_lot_ids && e.linked_lot_ids.length > 0 ? e.linked_lot_ids.join(', ') : '-'}</td>
                    <td>${safeStr(e.source_transaction_id) || '-'}</td>
                </tr>
            `).join('');
        } else {
            showEmptyState('audit-body', 'No audit trail data');
        }
    } catch (error) {
        console.error('renderAuditTrail failed:', error);
    }
}
