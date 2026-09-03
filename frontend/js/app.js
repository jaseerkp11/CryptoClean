/**
 * KryptLedg Frontend Application
 * Professional Crypto Tax Reporting Dashboard
 */

// State
const state = {
    currentPage: 'landing',
    selectedFile: null,
    selectedPlan: 'free',
    timezone: 'UTC',
    results: null,
    apiOnline: false,
    activeTab: 'overview',
    activeSubTab: 'events',
    detectedExchange: null,
    transactionCount: 0,
    planValidation: null,
    filteredTransactions: []
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
    taxYearSelect: document.getElementById('tax-year-select')
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
            processBtn.disabled = !state.selectedFile;
            state.planValidation = null;
        }
    } else {
        validationEl.className = 'plan-validation';
        validationEl.innerHTML = '';
        processBtn.disabled = !state.selectedFile;
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
            handleFileSelect(e.target.files[0]);
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
            const file = e.dataTransfer.files[0];
            if (file.name.toLowerCase().endsWith('.csv')) {
                handleFileSelect(file);
            } else {
                showToast('error', 'Invalid File', 'Please upload a CSV file.');
            }
        }
    });
}

function handleFileSelect(file) {
    if (!file.name.toLowerCase().endsWith('.csv')) {
        showToast('error', 'Invalid File', 'Please upload a CSV file.');
        return;
    }

    state.selectedFile = file;
    elements.uploadPrompt.style.display = 'none';
    elements.uploadFileSelected.style.display = 'flex';
    elements.selectedFileName.textContent = file.name;
    elements.selectedFileSize.textContent = formatFileSize(file.size);
    elements.processBtn.disabled = false;

    detectExchange(file);
}

async function detectExchange(file) {
    const result = await api.ingestFile(file);
    const detectEl = document.getElementById('detected-exchange');
    if (result.success && result.data) {
        const exchange = result.data.exchange || 'Unknown';
        const reportType = result.data.report_type || '';
        state.detectedExchange = exchange;
        state.transactionCount = result.data.rows || 0;
        if (detectEl) {
            detectEl.textContent = `Detected exchange: ${exchange}${reportType ? ' (' + reportType + ')' : ''}`;
            detectEl.style.display = 'block';
        }
        if (exchange === 'unknown') {
            showToast('warning', 'Unrecognized Format', 'We could not recognize this CSV format. Please upload a supported Binance or Coinbase report.');
        }
        validatePlan();
    } else {
        state.detectedExchange = null;
        state.transactionCount = 0;
        if (detectEl) {
            detectEl.textContent = '';
            detectEl.style.display = 'none';
        }
        validatePlan();
    }
}

function resetUpload() {
    state.selectedFile = null;
    state.detectedExchange = null;
    state.transactionCount = 0;
    state.planValidation = null;
    elements.fileInput.value = '';
    elements.uploadPrompt.style.display = 'flex';
    elements.uploadFileSelected.style.display = 'none';
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

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ============================================
// Process
// ============================================

async function processFile() {
    if (!state.selectedFile) return;
    if (state.planValidation === 'over_limit') {
        showToast('error', 'Plan Limit Exceeded', 'Please upgrade your plan to process this file.');
        return;
    }

    const timezone = document.getElementById('timezone-select')?.value || '';
    const plan = state.selectedPlan || 'free';
    const accounting = plan === 'standard' || plan === 'complete';

    navigateTo('processing');
    elements.processingTitle.textContent = 'Processing your report...';
    elements.processingStatus.textContent = 'Uploading report...';
    elements.progressFill.style.width = '0%';

    const result = await api.processFile(state.selectedFile, timezone, accounting, plan);

    elements.progressFill.style.width = '100%';

    if (result.success) {
        state.results = result.data;
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
        elements.processingTitle.textContent = 'Processing failed';
        elements.processingStatus.textContent = result.error;
        elements.progressFill.style.width = '0%';

        showToast('error', 'Processing Failed', result.error);

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
        const rows = document.querySelectorAll('#transactions-body tr');
        let visibleCount = 0;

        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            const typeMatch = !typeValue || row.querySelector('.badge')?.textContent === typeValue;
            const searchMatch = !searchTerm || text.includes(searchTerm);
            if (typeMatch && searchMatch) {
                row.style.display = '';
                visibleCount++;
            } else {
                row.style.display = 'none';
            }
        });

        const paginationInfo = document.getElementById('pagination-info');
        if (paginationInfo) {
            paginationInfo.textContent = `Showing ${visibleCount} transactions`;
        }
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

    if (!state.selectedFile) {
        showToast('error', 'Export Failed', 'No file available for export. Please re-upload your report.');
        return;
    }

    if (format === 'csv') {
        api.exportResults(state.results, 'csv', taxYear, state.selectedFile, plan, timezone).then(result => {
            if (result.success) {
                showToast('success', 'Export Complete', 'Your report is downloading.');
            } else {
                showToast('error', 'Export Failed', result.error);
            }
        });
        return;
    }

    if (format === 'pdf') {
        api.exportResults(state.results, 'pdf', taxYear, state.selectedFile, plan, timezone).then(result => {
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
// Toast
// ============================================

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
        document.getElementById('results-source').textContent = `${safeStr(data.source) || 'Unknown'} - ${safeStr(data.report_type) || 'Unknown Report'}`;

        const summary = data.summary || {};
        document.getElementById('ov-total').textContent = data.transaction_count || 0;
        document.getElementById('ov-trades').textContent = summary.trades || 0;
        document.getElementById('ov-transfers').textContent = summary.transfers || 0;
        document.getElementById('ov-deposits').textContent = summary.deposits || 0;
        document.getElementById('ov-withdrawals').textContent = summary.withdrawals || 0;
        document.getElementById('ov-fees').textContent = summary.fees || 0;

        const acct = data.accounting_result || {};
        const acctSummary = acct.summary || {};
        document.getElementById('ov-events').textContent = acctSummary.total_events || 0;
        document.getElementById('ov-acquisitions').textContent = acctSummary.acquisition_events || 0;
        document.getElementById('ov-disposals').textContent = acctSummary.disposal_events || 0;
        document.getElementById('ov-lots').textContent = acctSummary.total_lots_created || 0;

        renderPnLCard(acct);
        renderTransactionsTable(data.transactions || []);
        renderReconciliation(data);
        renderAccounting(acct);
        renderTaxSummary(acct);
        renderHoldings(acct);
        renderMissingBasis(acct);
        renderExceptions(data, acct);
        renderAuditTrail(acct);
    } catch (error) {
        console.error('renderResults failed:', error);
        throw error;
    }
}

// ============================================
// P&L Card
// ============================================

function renderPnLCard(accountingResult) {
    try {
        const pnlCard = document.getElementById('pnl-card');
        if (!accountingResult || !accountingResult.summary) {
            pnlCard.style.display = 'none';
            return;
        }

        pnlCard.style.display = 'block';
        const summary = accountingResult.summary;
        const totalPnL = summary.total_realized_pnl;
        const currency = (summary.pnl_currency || 'USD').toString().toUpperCase();

        const pnlTotalEl = document.getElementById('pnl-total');
        if (totalPnL !== null && totalPnL !== undefined && safeStr(totalPnL) !== null) {
            const pnlValue = safeNum(totalPnL);
            pnlTotalEl.innerHTML = (pnlValue >= 0 ? '+' : '') + fmtCurrency(pnlValue, currency);
            pnlTotalEl.className = 'pnl-value ' + (pnlValue >= 0 ? 'positive' : 'negative');
        } else {
            pnlTotalEl.innerHTML = '<span class="unresolved-pill">UNRESOLVED</span>';
            pnlTotalEl.className = 'pnl-value';
        }

        const breakdownEl = document.getElementById('pnl-breakdown');
        breakdownEl.innerHTML = '';

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
                breakdownEl.appendChild(assetEl);
            });
        }
    } catch (error) {
        console.error('renderPnLCard failed:', error);
        throw error;
    }
}

// ============================================
// Transactions
// ============================================

function renderTransactionsTable(transactions) {
    try {
        const tbody = document.getElementById('transactions-body');
        tbody.innerHTML = '';

        if (!transactions || transactions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No transactions found</td></tr>';
            document.getElementById('pagination-info').textContent = 'Showing 0 transactions';
            return;
        }

        transactions.forEach(tx => {
            const row = document.createElement('tr');
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
            tbody.appendChild(row);
        });

        document.getElementById('pagination-info').textContent = `Showing ${transactions.length} transactions`;
    } catch (error) {
        console.error('renderTransactionsTable failed:', error);
        throw error;
    }
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
        throw error;
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

        if (!accountingResult || !accountingResult.summary) {
            summaryEvents.textContent = '0';
            summaryAcquisitions.textContent = '0';
            summaryDisposals.textContent = '0';
            summaryLots.textContent = '0';
            document.getElementById('accounting-body').innerHTML = '<tr><td colspan="8" class="empty-state">No accounting data available</td></tr>';
            document.getElementById('lots-body').innerHTML = '<tr><td colspan="7" class="empty-state">No lots data available</td></tr>';
            document.getElementById('consumptions-body').innerHTML = '<tr><td colspan="9" class="empty-state">No consumptions data available</td></tr>';
            return;
        }

        const summary = accountingResult.summary;
        summaryEvents.textContent = summary.total_events || 0;
        summaryAcquisitions.textContent = summary.acquisition_events || 0;
        summaryDisposals.textContent = summary.disposal_events || 0;
        summaryLots.textContent = summary.total_lots_created || 0;

        // Events
        const events = accountingResult.events || [];
        const accountingBody = document.getElementById('accounting-body');
        if (events.length > 0) {
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
        } else {
            accountingBody.innerHTML = '<tr><td colspan="8" class="empty-state">No events found</td></tr>';
        }

        // Lots
        const lots = accountingResult.lots || [];
        const lotsBody = document.getElementById('lots-body');
        if (lots.length > 0) {
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
        } else {
            lotsBody.innerHTML = '<tr><td colspan="7" class="empty-state">No lots found</td></tr>';
        }

        // Consumptions
        const consumptions = accountingResult.consumptions || [];
        const consumptionsBody = document.getElementById('consumptions-body');
        if (consumptions.length > 0) {
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
        } else {
            consumptionsBody.innerHTML = '<tr><td colspan="9" class="empty-state">No consumptions found</td></tr>';
        }
    } catch (error) {
        console.error('renderAccounting failed:', error);
        throw error;
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
            capitalGainsBody.innerHTML = '<tr><td colspan="8" class="empty-state">No capital gains data</td></tr>';
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
            incomeBody.innerHTML = '<tr><td colspan="6" class="empty-state">No income data</td></tr>';
        }
    } catch (error) {
        console.error('renderTaxSummary failed:', error);
        throw error;
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
            holdingsBody.innerHTML = '<tr><td colspan="5" class="empty-state">No holdings found</td></tr>';
        }
    } catch (error) {
        console.error('renderHoldings failed:', error);
        throw error;
    }
}

// ============================================
// Missing Cost Basis
// ============================================

function renderMissingBasis(accountingResult) {
    try {
        const events = accountingResult.events || [];
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
            missingBody.innerHTML = '<tr><td colspan="6" class="empty-state">All disposals have cost basis</td></tr>';
        }
    } catch (error) {
        console.error('renderMissingBasis failed:', error);
        throw error;
    }
}

// ============================================
// Exceptions & Review
// ============================================

function renderExceptions(data, accountingResult) {
    try {
        // Processing warnings
        const warnings = data.warnings || [];
        const procWarningsList = document.getElementById('proc-warnings-list');
        document.getElementById('proc-warning-count').textContent = warnings.length;

        if (warnings.length > 0) {
            procWarningsList.innerHTML = warnings.map(w => `
                <div class="warning-item warning">
                    <div class="warning-icon">
                        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 1 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#F59E0B" stroke-width="2"/></svg>
                    </div>
                    <div class="warning-content"><div class="warning-message">${safeStr(w) || 'UNKNOWN'}</div></div>
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
            qualityIssuesList.innerHTML = accountingWarnings.map(w => `
                <div class="warning-item info">
                    <div class="warning-icon">
                        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 1 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#6366F1" stroke-width="2"/></svg>
                    </div>
                    <div class="warning-content">
                        <div class="warning-message">${safeStr(w.message) || 'UNKNOWN'}</div>
                        ${w.source_transaction_id ? `<div class="warning-detail">Source: ${safeStr(w.source_transaction_id)}</div>` : ''}
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
            errorsList.innerHTML = errors.map(e => `
                <div class="warning-item error">
                    <div class="warning-icon">
                        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 1 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#EF4444" stroke-width="2"/></svg>
                    </div>
                    <div class="warning-content"><div class="warning-message">${safeStr(e.message || e) || 'UNKNOWN'}</div></div>
                </div>
            `).join('');
        } else {
            errorsList.innerHTML = '<p class="empty-state">No errors</p>';
        }
    } catch (error) {
        console.error('renderExceptions failed:', error);
        throw error;
    }
}

// ============================================
// Audit Trail
// ============================================

function renderAuditTrail(accountingResult) {
    try {
        const events = accountingResult.events || [];
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
            auditBody.innerHTML = '<tr><td colspan="10" class="empty-state">No audit trail data</td></tr>';
        }
    } catch (error) {
        console.error('renderAuditTrail failed:', error);
        throw error;
    }
}
