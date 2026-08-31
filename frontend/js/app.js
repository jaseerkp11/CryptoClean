/**
 * CryptoClean Frontend Application
 * Main application logic and UI management
 */

// State management
const state = {
    currentPage: 'landing',
    selectedFile: null,
    processingMode: 'standard',
    timezone: 'UTC',
    results: null,
    apiOnline: false,
    activeTab: 'transactions'
};

// DOM Elements
const elements = {
    pages: {
        landing: document.getElementById('page-landing'),
        upload: document.getElementById('page-upload'),
        processing: document.getElementById('page-processing'),
        results: document.getElementById('page-results')
    },
    navLinks: document.querySelectorAll('.nav-link'),
    uploadZone: document.getElementById('upload-zone'),
    fileInput: document.getElementById('file-input'),
    uploadPrompt: document.getElementById('upload-prompt'),
    uploadFileSelected: document.getElementById('upload-file-selected'),
    selectedFileName: document.getElementById('selected-file-name'),
    selectedFileSize: document.getElementById('selected-file-size'),
    processBtn: document.getElementById('process-btn'),
    timezoneSelect: document.getElementById('timezone-select'),
    progressFill: document.getElementById('progress-fill'),
    processingTitle: document.getElementById('processing-title'),
    processingStatus: document.getElementById('processing-status'),
    processingInfo: document.getElementById('processing-info'),
    toastContainer: document.getElementById('toast-container'),
    apiStatus: document.getElementById('api-status'),
    apiStatusText: document.getElementById('api-status-text')
};

// Initialize application
document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
});

async function initializeApp() {
    setupNavigation();
    setupUploadZone();
    setupTabs();
    setupSearch();
    await checkApiStatus();
}

// API Status Check
async function checkApiStatus() {
    const result = await api.checkHealth();
    state.apiOnline = result.online;
    
    if (result.online) {
        elements.apiStatus.className = 'status-indicator online';
        elements.apiStatusText.textContent = 'API Online';
    } else {
        elements.apiStatus.className = 'status-indicator offline';
        elements.apiStatusText.textContent = 'API Offline';
    }
}

// Navigation
function setupNavigation() {
    elements.navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const nav = link.dataset.nav;
            navigateTo(nav);
        });
    });
}

function navigateTo(page) {
    state.currentPage = page;
    
    // Update page visibility
    Object.values(elements.pages).forEach(p => p.classList.remove('active'));
    elements.pages[page]?.classList.add('active');
    
    // Update nav links
    elements.navLinks.forEach(link => {
        link.classList.toggle('active', link.dataset.nav === page);
    });
    
    // Scroll to top
    window.scrollTo(0, 0);
}

// Upload Zone Setup
function setupUploadZone() {
    const zone = elements.uploadZone;
    const input = elements.fileInput;
    
    // Click to browse
    zone.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        input.click();
    });
    
    // File selected
    input.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFileSelect(e.target.files[0]);
        }
    });
    
    // Drag and drop
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
}

function resetUpload() {
    state.selectedFile = null;
    elements.fileInput.value = '';
    elements.uploadPrompt.style.display = 'flex';
    elements.uploadFileSelected.style.display = 'none';
    elements.processBtn.disabled = true;
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// Process File
async function processFile() {
    if (!state.selectedFile) return;
    
    const timezone = elements.timezoneSelect.value;
    const accounting = document.querySelector('input[name="processing-mode"]:checked').value === 'accounting';
    
    // Switch to processing page
    navigateTo('processing');
    
    // Update processing UI
    elements.processingTitle.textContent = 'Processing your report...';
    elements.processingStatus.textContent = 'Uploading file...';
    elements.progressFill.style.width = '0%';
    
    // Simulate progress
    let progress = 0;
    const progressInterval = setInterval(() => {
        progress += Math.random() * 15;
        if (progress > 90) progress = 90;
        elements.progressFill.style.width = progress + '%';
    }, 500);
    
    // Process file
    const result = await api.processFile(state.selectedFile, timezone, accounting);
    
    clearInterval(progressInterval);
    elements.progressFill.style.width = '100%';
    
    if (result.success) {
        state.results = result.data;
        elements.processingTitle.textContent = 'Processing complete!';
        elements.processingStatus.textContent = 'Preparing results...';
        
        setTimeout(() => {
            renderResults(result.data);
            navigateTo('results');
            
            if (result.partial) {
                showToast('warning', 'Partial Success', 'Some transactions could not be processed. Check the Warnings tab for details.');
            } else {
                showToast('success', 'Success', 'Your report has been processed successfully.');
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

// Render Results
function renderResults(data) {
    // Update source info
    const sourceEl = document.getElementById('results-source');
    sourceEl.textContent = `${data.source || 'Unknown'} - ${data.report_type || 'Unknown Report'}`;
    
    // Summary cards
    const summary = data.summary || {};
    document.getElementById('stat-total').textContent = data.transaction_count || 0;
    document.getElementById('stat-trades').textContent = summary.trades || 0;
    document.getElementById('stat-transfers').textContent = summary.transfers || 0;
    document.getElementById('stat-deposits').textContent = summary.deposits || 0;
    document.getElementById('stat-withdrawals').textContent = summary.withdrawals || 0;
    document.getElementById('stat-fees').textContent = summary.fees || 0;
    
    // P&L Card
    renderPnLCard(data.accounting_result);
    
    // Transactions table
    renderTransactionsTable(data.transactions || []);
    
    // Reconciliation
    renderReconciliation(data);
    
    // Accounting
    renderAccounting(data.accounting_result);
    
    // Warnings
    renderWarnings(data);
}

function renderPnLCard(accountingResult) {
    const pnlCard = document.getElementById('pnl-card');
    
    if (!accountingResult || !accountingResult.summary) {
        pnlCard.style.display = 'none';
        return;
    }
    
    pnlCard.style.display = 'block';
    
    const summary = accountingResult.summary;
    const totalPnL = summary.total_realized_pnl;
    const currency = summary.pnl_currency || 'USD';
    
    const pnlTotalEl = document.getElementById('pnl-total');
    if (totalPnL !== null && totalPnL !== undefined) {
        const pnlValue = parseFloat(totalPnL);
        pnlTotalEl.textContent = (pnlValue >= 0 ? '+' : '') + formatCurrency(pnlValue, currency);
        pnlTotalEl.className = 'pnl-value ' + (pnlValue >= 0 ? 'positive' : 'negative');
    } else {
        pnlTotalEl.textContent = '--';
        pnlTotalEl.className = 'pnl-value';
    }
    
    // P&L breakdown by asset
    const breakdownEl = document.getElementById('pnl-breakdown');
    breakdownEl.innerHTML = '';
    
    if (accountingResult.realized_pnl && accountingResult.realized_pnl.length > 0) {
        accountingResult.realized_pnl.forEach(pnl => {
            const assetEl = document.createElement('div');
            assetEl.className = 'pnl-asset';
            const value = parseFloat(pnl.total_realized_pnl);
            assetEl.innerHTML = `
                <span class="pnl-asset-name">${pnl.asset}</span>
                <span class="pnl-asset-value ${value >= 0 ? 'positive' : 'negative'}">
                    ${value >= 0 ? '+' : ''}${formatCurrency(value, pnl.currency)}
                </span>
            `;
            breakdownEl.appendChild(assetEl);
        });
    }
}

function renderTransactionsTable(transactions) {
    const tbody = document.getElementById('transactions-body');
    tbody.innerHTML = '';
    
    transactions.forEach(tx => {
        const row = document.createElement('tr');
        const sideClass = tx.side === 'BUY' ? 'badge-buy' : tx.side === 'SELL' ? 'badge-sell' : '';
        
        row.innerHTML = `
            <td>${formatDate(tx.timestamp)}</td>
            <td><span class="badge badge-${(tx.transaction_type || 'unknown').toLowerCase()}">${tx.transaction_type}</span></td>
            <td>${tx.side ? `<span class="badge ${sideClass}">${tx.side}</span>` : '-'}</td>
            <td>${tx.asset}</td>
            <td>${formatNumber(tx.quantity)}</td>
            <td>${tx.price ? formatCurrency(tx.price) : '-'}</td>
            <td>${tx.value ? formatCurrency(tx.value) : '-'}</td>
            <td>${tx.fee ? formatCurrency(tx.fee, tx.fee_asset) : '-'}</td>
            <td>${tx.wallet || '-'}</td>
        `;
        tbody.appendChild(row);
    });
    
    document.getElementById('pagination-info').textContent = `Showing ${transactions.length} transactions`;
}

function renderReconciliation(data) {
    // Transfers
    const transfersContent = document.getElementById('transfers-content');
    const transferMatches = data.transfer_matches?.matches || [];
    document.getElementById('transfer-count').textContent = `${transferMatches.length} matched`;
    
    if (transferMatches.length > 0) {
        transfersContent.innerHTML = transferMatches.map(match => `
            <div class="recon-item">
                <div class="recon-item-header">
                    <span class="recon-item-title">${match.asset} - ${formatNumber(match.quantity)}</span>
                    <span class="recon-item-detail">${formatDate(match.timestamp)}</span>
                </div>
                <div class="recon-item-detail">
                    From: ${match.source_account || 'Unknown'} → To: ${match.destination_account || 'Unknown'}
                </div>
                <div class="reasons-list">
                    ${match.reasons.map(r => `<span class="reason-tag">${r}</span>`).join('')}
                </div>
            </div>
        `).join('');
    } else {
        transfersContent.innerHTML = '<p class="empty-state">No internal transfers detected</p>';
    }
    
    // Duplicates
    const duplicatesContent = document.getElementById('duplicates-content');
    const duplicateGroups = data.duplicate_findings?.groups || [];
    document.getElementById('duplicate-count').textContent = `${duplicateGroups.length} found`;
    
    if (duplicateGroups.length > 0) {
        duplicatesContent.innerHTML = duplicateGroups.map(group => `
            <div class="recon-item">
                <div class="recon-item-header">
                    <span class="recon-item-title">${group.classification.replace(/_/g, ' ')}</span>
                    <span class="recon-item-detail">Score: ${group.score}</span>
                </div>
                <div class="recon-item-detail">
                    ${group.transaction_ids.length} transactions: ${group.transaction_ids.slice(0, 3).join(', ')}${group.transaction_ids.length > 3 ? '...' : ''}
                </div>
                <div class="reasons-list">
                    ${group.reasons.map(r => `<span class="reason-tag">${r}</span>`).join('')}
                </div>
            </div>
        `).join('');
    } else {
        duplicatesContent.innerHTML = '<p class="empty-state">No duplicates detected</p>';
    }
    
    // Converts
    const convertsContent = document.getElementById('converts-content');
    const convertMatches = data.convert_matches?.matches || [];
    document.getElementById('convert-count').textContent = `${convertMatches.length} found`;
    
    if (convertMatches.length > 0) {
        convertsContent.innerHTML = convertMatches.map(match => `
            <div class="recon-item">
                <div class="recon-item-header">
                    <span class="recon-item-title">${match.input_asset} → ${match.output_asset}</span>
                    <span class="recon-item-detail">${formatDate(match.timestamp)}</span>
                </div>
                <div class="recon-item-detail">
                    Sold: ${formatNumber(match.input_quantity)} ${match.input_asset} → Bought: ${formatNumber(match.output_quantity)} ${match.output_asset}
                </div>
                <div class="reasons-list">
                    ${match.reasons.map(r => `<span class="reason-tag">${r}</span>`).join('')}
                </div>
            </div>
        `).join('');
    } else {
        convertsContent.innerHTML = '<p class="empty-state">No convert events detected</p>';
    }
}

function renderAccounting(accountingResult) {
    const summaryEvents = document.getElementById('acct-events');
    const summaryAcquisitions = document.getElementById('acct-acquisitions');
    const summaryDisposals = document.getElementById('acct-disposals');
    const summaryLots = document.getElementById('acct-lots');
    const accountingBody = document.getElementById('accounting-body');
    
    if (!accountingResult || !accountingResult.summary) {
        summaryEvents.textContent = '0';
        summaryAcquisitions.textContent = '0';
        summaryDisposals.textContent = '0';
        summaryLots.textContent = '0';
        accountingBody.innerHTML = '<tr><td colspan="7" class="empty-state">No accounting data available</td></tr>';
        return;
    }
    
    const summary = accountingResult.summary;
    summaryEvents.textContent = summary.total_events || 0;
    summaryAcquisitions.textContent = summary.acquisition_events || 0;
    summaryDisposals.textContent = summary.disposal_events || 0;
    summaryLots.textContent = summary.total_lots_created || 0;
    
    // Accounting events table
    const events = accountingResult.events || [];
    accountingBody.innerHTML = events.map(event => `
        <tr>
            <td>${formatDate(event.timestamp)}</td>
            <td><span class="badge badge-${getAccountingEventClass(event.event_type)}">${event.event_type}</span></td>
            <td>${event.asset}</td>
            <td>${formatNumber(event.quantity)}</td>
            <td>${event.cost_basis ? formatCurrency(event.cost_basis, event.cost_currency) : '-'}</td>
            <td>${event.proceeds ? formatCurrency(event.proceeds, event.proceeds_currency) : '-'}</td>
            <td class="${event.realized_pnl ? (parseFloat(event.realized_pnl) >= 0 ? 'text-positive' : 'text-negative') : ''}">${event.realized_pnl ? formatCurrency(event.realized_pnl, event.pnl_currency) : '-'}</td>
        </tr>
    `).join('');
}

function getAccountingEventClass(type) {
    const classes = {
        'ACQUISITION': 'deposit',
        'DISPOSAL': 'withdrawal',
        'TRANSFER': 'transfer',
        'SWAP': 'swap',
        'FEE': 'fee',
        'NON_ACCOUNTING': 'unknown'
    };
    return classes[type] || 'unknown';
}

function renderWarnings(data) {
    const warningsList = document.getElementById('warnings-list');
    const qualityList = document.getElementById('quality-list');
    
    // Processing warnings
    const warnings = data.warnings || [];
    document.getElementById('warning-count').textContent = warnings.length;
    
    if (warnings.length > 0) {
        warningsList.innerHTML = warnings.map(w => `
            <div class="warning-item warning">
                <div class="warning-icon">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                        <path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 1 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#F59E0B" stroke-width="2"/>
                    </svg>
                </div>
                <div class="warning-content">
                    <div class="warning-message">${w}</div>
                </div>
            </div>
        `).join('');
    } else {
        warningsList.innerHTML = '<p class="empty-state">No warnings</p>';
    }
    
    // Data quality issues (from accounting warnings)
    const accountingWarnings = data.accounting_result?.warnings || [];
    const qualityIssues = accountingWarnings.map(w => w.message);
    document.getElementById('quality-count').textContent = qualityIssues.length;
    
    if (qualityIssues.length > 0) {
        qualityList.innerHTML = qualityIssues.map(msg => `
            <div class="warning-item info">
                <div class="warning-icon">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                        <path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 1 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#6366F1" stroke-width="2"/>
                    </svg>
                </div>
                <div class="warning-content">
                    <div class="warning-message">${msg}</div>
                </div>
            </div>
        `).join('');
    } else {
        qualityList.innerHTML = '<p class="empty-state">No data quality issues</p>';
    }
}

// Tab handling
function setupTabs() {
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            state.activeTab = tabName;
            
            // Update tab buttons
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            // Update tab panes
            document.querySelectorAll('.tab-pane').forEach(pane => {
                pane.classList.remove('active');
            });
            document.getElementById(`tab-${tabName}`)?.classList.add('active');
        });
    });
}

// Search functionality
function setupSearch() {
    const searchInput = document.getElementById('transaction-search');
    const typeFilter = document.getElementById('type-filter');
    
    const filterTransactions = () => {
        const searchTerm = searchInput.value.toLowerCase();
        const typeValue = typeFilter.value;
        
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
        
        document.getElementById('pagination-info').textContent = `Showing ${visibleCount} transactions`;
    };
    
    searchInput.addEventListener('input', filterTransactions);
    typeFilter.addEventListener('change', filterTransactions);
}

// Export results
function exportResults() {
    if (!state.results || !state.results.transactions) {
        showToast('error', 'No Data', 'No results to export.');
        return;
    }
    
    const transactions = state.results.transactions;
    const headers = ['Date', 'Type', 'Side', 'Asset', 'Quantity', 'Price', 'Value', 'Fee', 'Fee Asset', 'Wallet'];
    
    const csvContent = [
        headers.join(','),
        ...transactions.map(tx => [
            tx.timestamp,
            tx.transaction_type,
            tx.side || '',
            tx.asset,
            tx.quantity,
            tx.price || '',
            tx.value || '',
            tx.fee || '',
            tx.fee_asset || '',
            tx.wallet || ''
        ].join(','))
    ].join('\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `cryptoclean-results-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    
    showToast('success', 'Export Complete', 'Results downloaded as CSV.');
}

// Toast notifications
function showToast(type, title, message) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icons = {
        success: '<svg class="toast-icon" width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 18C14.4183 18 18 14.4183 18 10C18 5.58172 14.4183 2 10 2C5.58172 2 2 5.58172 2 10C2 14.4183 5.58172 18 10 18Z" stroke="#10B981" stroke-width="2"/><path d="M6 10L9 13L14 7" stroke="#10B981" stroke-width="2"/></svg>',
        error: '<svg class="toast-icon" width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 18C14.4183 18 18 14.4183 18 10C18 5.58172 14.4183 2 10 2C5.58172 2 2 5.58172 2 10C2 14.4183 5.58172 18 10 18Z" stroke="#EF4444" stroke-width="2"/><path d="M13 7L7 13M7 7L13 13" stroke="#EF4444" stroke-width="2"/></svg>',
        warning: '<svg class="toast-icon" width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 1 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#F59E0B" stroke-width="2"/></svg>'
    };
    
    toast.innerHTML = `
        ${icons[type] || icons.warning}
        <div class="toast-content">
            <div class="toast-title">${title}</div>
            <div class="toast-message">${message}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M12 4L4 12M4 4L12 12" stroke="currentColor" stroke-width="2"/>
            </svg>
        </button>
    `;
    
    elements.toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// Utility functions
function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

function formatNumber(value) {
    if (value === null || value === undefined) return '-';
    const num = parseFloat(value);
    if (isNaN(num)) return value;
    
    if (Math.abs(num) >= 1000000) {
        return (num / 1000000).toFixed(2) + 'M';
    }
    if (Math.abs(num) >= 1000) {
        return (num / 1000).toFixed(2) + 'K';
    }
    if (Math.abs(num) < 0.01 && num !== 0) {
        return num.toExponential(2);
    }
    return num.toLocaleString('en-US', { maximumFractionDigits: 6 });
}

function formatCurrency(value, currency = 'USD') {
    if (value === null || value === undefined) return '-';
    const num = parseFloat(value);
    if (isNaN(num)) return value;
    
    return num.toLocaleString('en-US', {
        style: 'currency',
        currency: currency,
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
}
