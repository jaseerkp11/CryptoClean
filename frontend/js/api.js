/**
 * KryptLedg API Client
 * Handles all communication with the backend API
 */

const API_BASE_URL = 'https://cryptoclean-api.onrender.com';

function safeString(value) {
    if (typeof value === 'string') return value;
    if (Array.isArray(value)) return value.join(', ');
    if (value && typeof value === 'object') {
        if (value.detail) return safeString(value.detail);
        return JSON.stringify(value);
    }
    return value ? String(value) : '';
}

function mergeSummary(a, b) {
    if (!a && !b) return {};
    if (!a) return b || {};
    if (!b) return a || {};
    return {
        total_transactions: (a.total_transactions || 0) + (b.total_transactions || 0),
        duplicate_groups: (a.duplicate_groups || 0) + (b.duplicate_groups || 0),
        exact_duplicates: (a.exact_duplicates || 0) + (b.exact_duplicates || 0),
        probable_duplicates: (a.probable_duplicates || 0) + (b.probable_duplicates || 0),
        possible_duplicates: (a.possible_duplicates || 0) + (b.possible_duplicates || 0),
        internal_transfers: (a.internal_transfers || 0) + (b.internal_transfers || 0),
        unknown_transactions: (a.unknown_transactions || 0) + (b.unknown_transactions || 0),
        fees: (a.fees || 0) + (b.fees || 0),
        deposits: (a.deposits || 0) + (b.deposits || 0),
        withdrawals: (a.withdrawals || 0) + (b.withdrawals || 0),
        transfers: (a.transfers || 0) + (b.transfers || 0),
        trades: (a.trades || 0) + (b.trades || 0),
        swaps: (a.swaps || 0) + (b.swaps || 0),
        convert_events: (a.convert_events || 0) + (b.convert_events || 0),
        unresolved_convert_rows: (a.unresolved_convert_rows || 0) + (b.unresolved_convert_rows || 0),
        comments: (a.comments || 0) + (b.comments || 0),
        acquisitions: (a.acquisitions || 0) + (b.acquisitions || 0),
        disposals: (a.disposals || 0) + (b.disposals || 0),
        non_accounting: (a.non_accounting || 0) + (b.non_accounting || 0),
        unresolved: (a.unresolved || 0) + (b.unresolved || 0),
        accounting_events: (a.accounting_events || 0) + (b.accounting_events || 0),
        total_proceeds: mergeDecimalStrings(a.total_proceeds, b.total_proceeds),
        total_cost_basis: mergeDecimalStrings(a.total_cost_basis, b.total_cost_basis),
        total_fees: mergeDecimalStrings(a.total_fees, b.total_fees),
        realized_gains: mergeDecimalStrings(a.realized_gains, b.realized_gains),
        realized_losses: mergeDecimalStrings(a.realized_losses, b.realized_losses),
        net_realized_pnl: mergeDecimalStrings(a.net_realized_pnl, b.net_realized_pnl)
    };
}

function mergeDecimalStrings(a, b) {
    const aNum = a !== null && a !== undefined && a !== '' ? parseFloat(a) : 0;
    const bNum = b !== null && b !== undefined && b !== '' ? parseFloat(b) : 0;
    const sum = aNum + bNum;
    return sum !== 0 ? String(sum) : null;
}

const api = {
    /**
     * Check API health status
     */
    async checkHealth() {
        try {
            const response = await fetch(`${API_BASE_URL}/health`, {
                method: 'GET',
                headers: { 'Accept': 'application/json' }
            });
            if (response.ok) {
                return { online: true, data: await response.json() };
            }
            return { online: false, data: null };
        } catch (error) {
            return { online: false, data: null, error: error.message };
        }
    },

    /**
     * Process a CSV file
     * @param {File} file - The CSV file to process
     * @param {string} timezone - The timezone for date interpretation
     * @param {boolean} accounting - Whether to include accounting calculations
     * @param {function} onProgress - Progress callback
     */
    async processFile(file, timezone, accounting = false, plan = 'free', onProgress = null) {
        const formData = new FormData();
        formData.append('file', file);

        const endpoint = accounting ? '/api/v1/account' : '/api/v1/process';
        const url = new URL(`${API_BASE_URL}${endpoint}`);
        url.searchParams.set('plan', plan || 'free');
        if (timezone) {
            url.searchParams.set('timezone', timezone);
        }
        if (accounting) {
            url.searchParams.set('accounting', 'true');
        }

        try {
            const response = await fetch(url.toString(), {
                method: 'POST',
                body: formData,
            });

            const data = await response.json();

            if (response.ok || response.status === 207) {
                return {
                    success: true,
                    status: response.status,
                    data: data,
                    partial: response.status === 207
                };
            } else {
                return {
                    success: false,
                    status: response.status,
                    error: data.detail || 'An error occurred while processing your file.',
                    data: data
                };
            }
        } catch (error) {
            return {
                success: false,
                status: 0,
                error: 'Unable to connect to the server. Please check your connection and try again.'
            };
        }
    },

    /**
     * Process multiple CSV files
     * @param {FileList|Array<File>} files - The CSV files to process
     * @param {string} timezone - The timezone for date interpretation
     * @param {boolean} accounting - Whether to include accounting calculations
     */
    async processFiles(files, timezone, accounting = false, plan = 'free') {
        if (files.length === 1) {
            return this.processFile(files[0], timezone, accounting, plan);
        }

        const formData = new FormData();
        for (const file of files) {
            formData.append('files', file);
        }

        const endpoint = '/api/v1/process-multi';
        const url = new URL(`${API_BASE_URL}${endpoint}`);
        url.searchParams.set('plan', plan || 'free');
        if (timezone) {
            url.searchParams.set('timezone', timezone);
        }
        if (accounting) {
            url.searchParams.set('accounting', 'true');
        }

        try {
            const response = await fetch(url.toString(), {
                method: 'POST',
                body: formData,
            });

            if (!response.ok && response.status !== 207) {
                const data = await response.json().catch(() => ({}));
                console.error('Multi-file endpoint error:', response.status, data);
                return await this._processFilesIndividually(files, timezone, accounting, plan);
            }

            const data = await response.json();

            return {
                success: true,
                status: response.status,
                data: data,
                partial: response.status === 207
            };
        } catch (error) {
            console.error('Multi-file endpoint exception:', error);
            return await this._processFilesIndividually(files, timezone, accounting, plan);
        }
    },

    async _processFilesIndividually(files, timezone, accounting = false, plan = 'free') {
        const combined = {
            success: true,
            status: 200,
            data: null,
            error: null,
            partial: false
        };

        for (const file of files) {
            const result = await this.processFile(file, timezone, accounting, plan);
            if (!result.success) {
                combined.success = false;
                combined.status = result.status || 400;
                combined.error = result.error || 'One or more files failed to process.';
                combined.partial = true;
                continue;
            }

            if (!combined.data) {
                combined.data = result.data;
            } else {
                combined.data.transaction_count = (combined.data.transaction_count || 0) + (result.data.transaction_count || 0);
                combined.data.transactions = (combined.data.transactions || []).concat(result.data.transactions || []);
                combined.data.warnings = (combined.data.warnings || []).concat(result.data.warnings || []);
                combined.data.errors = (combined.data.errors || []).concat(result.data.errors || []);
                if (result.data.accounting_result) {
                    const prev = combined.data.accounting_result || {};
                    const next = result.data.accounting_result;
                    combined.data.accounting_result = {
                        events: (prev.events || []).concat(next.events || []),
                        lots: (prev.lots || []).concat(next.lots || []),
                        consumptions: (prev.consumptions || []).concat(next.consumptions || []),
                        realized_pnl: (prev.realized_pnl || []).concat(next.realized_pnl || []),
                        warnings: (prev.warnings || []).concat(next.warnings || []),
                        errors: (prev.errors || []).concat(next.errors || []),
                        summary: mergeSummary(prev.summary, next.summary)
                    };
                }
                if (result.data.summary) {
                    combined.data.summary = mergeSummary(combined.data.summary, result.data.summary);
                }
            }
        }

        return combined;
    },

    async processFile(file, timezone, accounting = false, plan = 'free') {
        const endpoint = accounting ? '/api/v1/account' : '/api/v1/process';
        const formData = new FormData();
        formData.append('file', file);

        const url = new URL(`${API_BASE_URL}${endpoint}`);
        url.searchParams.set('plan', plan || 'free');
        if (timezone) {
            url.searchParams.set('timezone', timezone);
        }
        if (accounting) {
            url.searchParams.set('accounting', 'true');
        }

        try {
            const response = await fetch(url.toString(), {
                method: 'POST',
                body: formData,
            });

            const data = await response.json();

            if (response.ok || response.status === 207) {
                return {
                    success: true,
                    status: response.status,
                    data: data,
                    partial: response.status === 207
                };
            } else {
                return {
                    success: false,
                    status: response.status,
                    error: safeString(data.detail || data || 'An error occurred while processing your file.'),
                    data: data
                };
            }
        } catch (error) {
            return {
                success: false,
                status: 0,
                error: 'Unable to connect to the server. Please check your connection and try again.'
            };
        }
    },

    /**
     * Ingest a CSV file for preview/detection
     * @param {File} file - The CSV file to ingest
     */
    async ingestFile(file) {
        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch(`${API_BASE_URL}/api/v1/ingest`, {
                method: 'POST',
                body: formData,
            });

            const data = await response.json();

            if (response.ok) {
                return { success: true, data: data };
            } else {
                return { success: false, error: data.detail || 'Failed to analyze file.' };
            }
        } catch (error) {
            return { success: false, error: 'Unable to connect to the server.' };
        }
    },

    /**
     * Export results as CSV or PDF
     * @param {string} format - 'csv' or 'pdf'
     */
    async exportResults(data, format = 'csv', taxYear = '', file = null, plan = 'free', timezone = '') {
        try {
            const endpoint = format === 'pdf' ? '/api/v1/report/pdf' : '/api/v1/export';
            const url = new URL(`${API_BASE_URL}${endpoint}`);
            url.searchParams.set('plan', plan || 'free');
            if (timezone) url.searchParams.set('timezone', timezone);
            if (format === 'pdf' && taxYear) url.searchParams.set('tax_year', taxYear);

            const formData = new FormData();
            if (file) {
                formData.append('file', file);
            } else {
                throw new Error('No file available for export. Please re-upload your report.');
            }

            const response = await fetch(url.toString(), {
                method: 'POST',
                body: formData,
            });

            if (response.ok) {
                const blob = await response.blob();
                const downloadUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                const ext = format === 'pdf' ? 'pdf' : 'zip';
                a.download = `kryptledg-report-${new Date().toISOString().split('T')[0]}.${ext}`;
                a.click();
                URL.revokeObjectURL(downloadUrl);
                return { success: true };
            } else {
                let errorMessage = 'Export failed.';
                try {
                    const errData = await response.json();
                    if (typeof errData.detail === 'string') {
                        errorMessage = errData.detail;
                    } else if (errData.detail) {
                        errorMessage = JSON.stringify(errData.detail);
                    } else {
                        errorMessage = 'Export failed.';
                    }
                } catch {
                    errorMessage = `Export failed with status ${response.status}.`;
                }
                return { success: false, error: errorMessage };
            }
        } catch (error) {
            return { success: false, error: 'Export failed: ' + error.message };
        }
    },

    /**
     * Fetch tax year data
     * @param {string} year - Tax year
     */
    async getTaxYear(year) {
        try {
            const url = new URL(`${API_BASE_URL}/api/v1/tax-year`);
            if (year) url.searchParams.set('year', year);
            const response = await fetch(url.toString(), {
                method: 'GET',
                headers: { 'Accept': 'application/json' }
            });
            if (response.ok) {
                return { success: true, data: await response.json() };
            }
            return { success: false, error: 'Failed to fetch tax year data.' };
        } catch (error) {
            return { success: false, error: error.message };
        }
    }
};
