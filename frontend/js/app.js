/**
 * CryptoClean Frontend Application - Professional Upgrade
 */

const state = {
    currentPage: 'landing',
    selectedFile: null,
    selectedPlan: 'free',
    timezone: 'UTC',
    results: null,
    activeTab: 'transactions',
    detectedExchange: null,
    transactionCount: 0,
    planValidation: null,
    selectedTaxYear: 'all'
};

document.addEventListener('DOMContentLoaded', () => {
    setupNavigation();
    setupUploadZone();
    setupTabs();
    setupSearch();
    setupPlanSelection();
    setupTaxYearSelector();
});

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
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add('active');
    window.scrollTo(0, 0);
}

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
    if (radio) radio.checked = true;
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
            validationEl.innerHTML = `<span>✕</span> This file contains ${state.transactionCount} transactions. The ${config.label} supports up to ${config.limit} transactions. <a href="#" onclick="navigateTo('pricing'); return false;">Upgrade Plan</a>`;
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

function setupUploadZone() {
    const zone = document.getElementById('upload-zone');
    const input = document.getElementById('file-input');

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
    document.getElementById('upload-prompt').style.display = 'none';
    document.getElementById('upload-file-selected').style.display = 'flex';
    document.getElementById('selected-file-name').textContent = file.name;
    document.getElementById('selected-file-size').textContent = formatFileSize(file.size);
    document.getElementById('process-btn').disabled = false;

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
    document.getElementById('file-input').value = '';
    document.getElementById('upload-prompt').style.display = 'flex';
    document.getElementById('upload-file-selected').style.display = 'none';
    document.getElementById('process-btn').disabled = true;
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
    document.getElementById('processing-title').textContent = 'Processing your report...';
    document.getElementById('processing-status').textContent = 'Uploading report...';
    document.getElementById('progress-fill').style.width = '0%';

    try {
        const result = await api.processFile(state.selectedFile, timezone, accounting, plan);
        document.getElementById('progress-fill').style.width = '100%';

        if (result.success) {
            state.results = result.data;
            document.getElementById('processing-title').textContent = 'Analysis complete';
            document.getElementById('processing-status').textContent = 'Preparing results...';

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
            document.getElementById('processing-title').textContent = 'Processing failed';
            document.getElementById('processing-status').textContent = result.error;
            document.getElementById('progress-fill').style.width = '0%';
            showToast('error', 'Processing Failed', result.error);
            setTimeout(() => navigateTo('upload'), 2000);
        }
    } catch (error) {
        document.getElementById('processing-title').textContent = 'Processing failed';
        document.getElementById('processing-status').textContent = 'An unexpected error occurred.';
        document.getElementById('progress-fill').style.width = '0%';
        showToast('error', 'Processing Failed', 'An unexpected error occurred. Please try again.');
        setTimeout(() => navigateTo('upload'), 2000);
    }
}

function setupTaxYearSelector() {
    const selector = document.getElementById('tax-year-select');
    if (selector) {
        selector.addEventListener('change', (e) => {
            state.selectedTaxYear = e.target.value;
            if (state.results) {
                renderResults(state.results);
            }
        });
    }
}

function filterByTaxYear(data, taxYear) {
    if (taxYear === 'all') return data;

    const filteredTransactions = (data.transactions || []).filter(tx => {
        if (!tx.timestamp) return false;
        const year = new Date(tx.timestamp).getFullYear();
        return year === parseInt(taxYear);
    });

    const filteredTxIds = new Set(filteredTransactions.map(tx => tx.transaction_id));

    const filteredAccountingResult = data.accounting_result ? {
        ...data.accounting_result,
        events: (data.accounting_result.events || []).filter(e => 
            e.source_transaction_ids && e.source_transaction_ids.some(id => filteredTxIds.has(id))
        ),
        lots: data.accounting_result.lots || [],
        consumptions: data.accounting_result.consumptions || [],
        realized_pnl: data.accounting_result.realized_pnl || [],
        warnings: data.accounting_result.warnings || [],
        errors: data.accounting_result.errors || [],
    } : null;

    const filteredTransferMatches = data.transfer_matches ? {
        ...data.transfer_matches,
        matches: (data.transfer_matches.matches || []).filter(m => 
            filteredTxIds.has(m.source_transaction_id) && filteredTxIds.has(m.destination_transaction_id)
        ),
        unmatched_leg_ids: (data.transfer_matches.unmatched_leg_ids || []).filter(id => filteredTxIds.has(id)),
    } : null;

    const filteredConvertMatches = data.convert_matches ? {
        ...data.convert_matches,
        matches: (data.convert_matches.matches || []).filter(m =>
            filteredTxIds.has(m.input_transaction_id) && filteredTxIds.has(m.output_transaction_id)
        ),
        unresolved_leg_ids: (data.convert_matches.unresolved_leg_ids || []).filter(id => filteredTxIds.has(id)),
    } : null;

    const filteredDuplicateFindings = data.duplicate_findings ? {
        ...data.duplicate_findings,
        groups: (data.duplicate_findings.groups || []).filter(g =>
            g.transaction_ids && g.transaction_ids.some(id => filteredTxIds.has(id))
        ),
    } : null;

    const recalculateSummary = (summary) => {
        const txTypes = filteredTransactions.reduce((acc, tx) => {
            acc[tx.transaction_type] = (acc[tx.transaction_type] || 0) + 1;
            return acc;
        }, {});

        const acctEvents = filteredAccountingResult?.events || [];
        const acctSummary = filteredAccountingResult?.summary || {};

        return {
            ...summary,
            total_transactions: filteredTransactions.length,
            trades: txTypes.TRADE || 0,
            transfers: txTypes.TRANSFER || 0,
            deposits: txTypes.DEPOSIT || 0,
            withdrawals: txTypes.WITHDRAWAL || 0,
            fees: txTypes.FEE || 0,
            unknown_transactions: txTypes.UNKNOWN || 0,
            swaps: txTypes.SWAP || 0,
            non_accounting: acctEvents.filter(e => e.event_type === 'NON_ACCOUNTING').length,
        };
    };

    return {
        ...data,
        transactions: filteredTransactions,
        transaction_count: filteredTransactions.length,
        summary: recalculateSummary(data.summary || {}),
        accounting_result: filteredAccountingResult,
        transfer_matches: filteredTransferMatches,
        convert_matches: filteredConvertMatches,
        duplicate_findings: filteredDuplicateFindings,
    };
}

function renderResults(data) {
    const taxYear = state.selectedTaxYear || 'all';
    const filteredData = filterByTaxYear(data, taxYear);

    document.getElementById('results-source').textContent = `${filteredData.source || 'Unknown'} - ${filteredData.report_type || 'Unknown Report'}`;

    const summary = filteredData.summary || {};
    const acct = filteredData.accounting_result || {};
    const acctSummary = acct.summary || {};

    // Top-level metric cards
    document.getElementById('stat-total').textContent = filteredData.transaction_count || 0;
    document.getElementById('stat-acquisitions').textContent = acctSummary.acquisition_events || 0;
    document.getElementById('stat-disposals').textContent = acctSummary.disposal_events || 0;
    document.getElementById('stat-transfers').textContent = summary.transfers || 0;
    document.getElementById('stat-matched-transfers').textContent = summary.internal_transfers || 0;
    document.getElementById('stat-fees').textContent = summary.fees || 0;
    document.getElementById('stat-unknown').textContent = summary.unknown_transactions || 0;
    document.getElementById('stat-review').textContent = summary.unknown_transactions || 0;

    // P&L metrics
    renderPnLCard(acct);
    renderFinancialMetrics(acctSummary, summary);

    // Transaction overview
    renderTransactionOverview(summary);

    // Reconciliation
    renderReconciliation(filteredData);

    // Accounting
    renderAccounting(acct);

    // Tax-ready summary
    renderTaxReadySummary(summary, acctSummary);

    // Warnings
    renderWarnings(filteredData);
}

function renderFinancialMetrics(acctSummary, summary) {
    const metrics = {
        'metric-proceeds': acctSummary.total_proceeds || summary.total_proceeds || null,
        'metric-cost-basis': acctSummary.total_cost_basis || summary.total_cost_basis || null,
        'metric-fees': acctSummary.total_fees || summary.total_fees || null,
        'metric-gains': acctSummary.realized_gains || summary.realized_gains || null,
        'metric-losses': acctSummary.realized_losses || summary.realized_losses || null,
        'metric-net-pnl': acctSummary.total_realized_pnl || summary.net_realized_pnl || null,
    };

    for (const [id, value] of Object.entries(metrics)) {
        const el = document.getElementById(id);
        if (!el) continue;
        if (value !== null && value !== undefined && value !== '') {
            const num = parseFloat(value);
            if (!isNaN(num)) {
                el.textContent = formatCurrency(num, 'USD');
                el.className = 'metric-value';
            } else {
                el.textContent = 'UNRESOLVED';
                el.className = 'metric-value unresolved';
            }
        } else {
            el.textContent = 'UNRESOLVED';
            el.className = 'metric-value unresolved';
        }
    }
}

function renderTransactionOverview(summary) {
    const items = [
        { label: 'Deposits', value: summary.deposits || 0 },
        { label: 'Withdrawals', value: summary.withdrawals || 0 },
        { label: 'Trades', value: summary.trades || 0 },
        { label: 'Transfers', value: summary.transfers || 0 },
        { label: 'Fees', value: summary.fees || 0 },
        { label: 'Rewards / Income', value: summary.unknown_transactions || 0 },
        { label: 'Non-Accounting', value: summary.non_accounting || 0 },
        { label: 'Duplicates', value: summary.duplicate_groups || 0 },
        { label: 'Convert Events', value: summary.convert_events || 0 },
        { label: 'Unresolved', value: summary.unresolved_convert_rows || 0 },
        { label: 'Review Required', value: summary.unknown_transactions || 0 },
    ];

    const container = document.getElementById('transaction-overview-items');
    if (container) {
        container.innerHTML = items.map(item => `
            <div class="overview-item">
                <span class="overview-label">${item.label}</span>
                <span class="overview-value">${item.value}</span>
            </div>
        `).join('');
    }
}

function renderReconciliation(data) {
    const transferMatches = data.transfer_matches?.matches || [];
    const unmatchedTransfers = data.transfer_matches?.unmatched_leg_ids?.length || 0;
    const convertMatches = data.convert_matches?.matches || [];
    const duplicateGroups = data.duplicate_findings?.groups || [];

    document.getElementById('recon-matched-transfers').textContent = transferMatches.length;
    document.getElementById('recon-unmatched-transfers').textContent = unmatchedTransfers;
    document.getElementById('recon-conversions').textContent = convertMatches.length;
    document.getElementById('recon-duplicates').textContent = duplicateGroups.length;
}

function renderAccounting(acct) {
    if (!acct || !acct.summary) {
        document.getElementById('acct-events').textContent = '0';
        document.getElementById('acct-acquisitions').textContent = '0';
        document.getElementById('acct-disposals').textContent = '0';
        document.getElementById('acct-lots').textContent = '0';
        document.getElementById('accounting-body').innerHTML = '<tr><td colspan="7" class="empty-state">No accounting data available</td></tr>';
        return;
    }

    const summary = acct.summary;
    document.getElementById('acct-events').textContent = summary.total_events || 0;
    document.getElementById('acct-acquisitions').textContent = summary.acquisition_events || 0;
    document.getElementById('acct-disposals').textContent = summary.disposal_events || 0;
    document.getElementById('acct-lots').textContent = summary.total_lots_created || 0;

    const events = acct.events || [];
    document.getElementById('accounting-body').innerHTML = events.map(event => `
        <tr>
            <td>${formatDate(event.timestamp)}</td>
            <td><span class="badge badge-${getAccountingEventClass(event.event_type)}">${event.event_type}</span></td>
            <td>${event.asset}</td>
            <td>${formatNumber(event.quantity)}</td>
            <td>${event.cost_basis ? formatCurrency(event.cost_basis, event.cost_currency) : '<span class="unresolved">UNRESOLVED</span>'}</td>
            <td>${event.proceeds ? formatCurrency(event.proceeds, event.proceeds_currency) : '<span class="unresolved">UNRESOLVED</span>'}</td>
            <td class="${event.realized_pnl ? (parseFloat(event.realized_pnl) >= 0 ? 'text-positive' : 'text-negative') : ''}">${event.realized_pnl ? formatCurrency(event.realized_pnl, event.pnl_currency) : '<span class="unresolved">UNRESOLVED</span>'}</td>
        </tr>
    `).join('');
}

function renderTaxReadySummary(summary, acctSummary) {
    // Tax-ready summary shows what can be honestly calculated
    const taxYear = state.selectedTaxYear;
    const taxYearLabel = taxYear === 'all' ? 'All Years' : taxYear;

    document.getElementById('tax-year-label').textContent = taxYearLabel;

    // For now, show overall totals since we don't have year-filtered data yet
    document.getElementById('tax-capital-gains').textContent = acctSummary.disposal_events || 0;
    document.getElementById('tax-income').textContent = summary.unknown_transactions || 0;
    document.getElementById('tax-fees').textContent = summary.fees || 0;
    document.getElementById('tax-transfers').textContent = summary.transfers || 0;
    document.getElementById('tax-exceptions').textContent = summary.unknown_transactions || 0;
}

function renderPnLCard(acct) {
    const pnlCard = document.getElementById('pnl-card');
    if (!acct || !acct.summary) {
        pnlCard.style.display = 'none';
        return;
    }

    pnlCard.style.display = 'block';
    const summary = acct.summary;
    const totalPnL = summary.total_realized_pnl;
    const currency = summary.pnl_currency || 'USD';

    const pnlTotalEl = document.getElementById('pnl-total');
    if (totalPnL !== null && totalPnL !== undefined && totalPnL !== '') {
        const pnlValue = parseFloat(totalPnL);
        pnlTotalEl.textContent = (pnlValue >= 0 ? '+' : '') + formatCurrency(pnlValue, currency);
        pnlTotalEl.className = 'pnl-value ' + (pnlValue >= 0 ? 'positive' : 'negative');
    } else {
        pnlTotalEl.textContent = 'UNRESOLVED';
        pnlTotalEl.className = 'pnl-value unresolved';
    }

    const breakdownEl = document.getElementById('pnl-breakdown');
    breakdownEl.innerHTML = '';

    if (acct.realized_pnl && acct.realized_pnl.length > 0) {
        acct.realized_pnl.forEach(pnl => {
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

function renderWarnings(data) {
    const warningsList = document.getElementById('warnings-list');
    const qualityList = document.getElementById('quality-list');
    const warnings = data.warnings || [];
    document.getElementById('warning-count').textContent = warnings.length;

    if (warnings.length > 0) {
        warningsList.innerHTML = warnings.map(w => `
            <div class="warning-item warning">
                <div class="warning-icon">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 1 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#F59E0B" stroke-width="2"/></svg>
                </div>
                <div class="warning-content"><div class="warning-message">${w}</div></div>
            </div>
        `).join('');
    } else {
        warningsList.innerHTML = '<p class="empty-state">No warnings</p>';
    }

    const accountingWarnings = data.accounting_result?.warnings || [];
    const qualityIssues = accountingWarnings.map(w => w.message);
    document.getElementById('quality-count').textContent = qualityIssues.length;

    if (qualityIssues.length > 0) {
        qualityList.innerHTML = qualityIssues.map(msg => `
            <div class="warning-item info">
                <div class="warning-icon">
                    <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 6V10M10 14H10.01M19 10C19 14.9706 14.9706 19 10 19C5.02944 19 1 14.9706 1 10C1 5.02944 5.02944 1 10 1C14.9706 1 19 5.02944 19 10Z" stroke="#6366F1" stroke-width="2"/></svg>
                </div>
                <div class="warning-content"><div class="warning-message">${msg}</div></div>
            </div>
        `).join('');
    } else {
        qualityList.innerHTML = '<p class="empty-state">No data quality issues</p>';
    }
}

function getAccountingEventClass(type) {
    const classes = { 'ACQUISITION': 'deposit', 'DISPOSAL': 'withdrawal', 'TRANSFER': 'transfer', 'SWAP': 'swap', 'FEE': 'fee', 'NON_ACCOUNTING': 'unknown' };
    return classes[type] || 'unknown';
}

function setupTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
            document.getElementById(`tab-${tabName}`)?.classList.add('active');
        });
    });
}

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

function toggleFaq(item) {
    const answer = item.querySelector('.faq-answer');
    const icon = item.querySelector('.faq-question svg');
    const isOpen = item.classList.contains('active');

    document.querySelectorAll('.faq-item').forEach(faq => {
        faq.classList.remove('active');
        const a = faq.querySelector('.faq-answer');
        const i = faq.querySelector('.faq-question svg');
        if (a) a.style.display = 'none';
        if (i) i.style.transform = 'rotate(0deg)';
    });

    if (!isOpen) {
        item.classList.add('active');
        if (answer) answer.style.display = 'block';
        if (icon) icon.style.transform = 'rotate(180deg)';
    }
}

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

function showToast(type, title, message) {
    const toastContainer = document.getElementById('toast-container');
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
    toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatNumber(value) {
    if (value === null || value === undefined) return '-';
    const num = parseFloat(value);
    if (isNaN(num)) return value;
    if (Math.abs(num) >= 1000000) return (num / 1000000).toFixed(2) + 'M';
    if (Math.abs(num) >= 1000) return (num / 1000).toFixed(2) + 'K';
    if (Math.abs(num) < 0.01 && num !== 0) return num.toExponential(2);
    return num.toLocaleString('en-US', { maximumFractionDigits: 6 });
}

function formatCurrency(value, currency = 'USD') {
    if (value === null || value === undefined) return '-';
    const num = parseFloat(value);
    if (isNaN(num)) return value;
    return num.toLocaleString('en-US', { style: 'currency', currency: currency, minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
