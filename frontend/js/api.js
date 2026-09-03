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
        const isSingleFile = files.length === 1;
        const endpoint = accounting
            ? (isSingleFile ? '/api/v1/account' : '/api/v1/process-multi')
            : (isSingleFile ? '/api/v1/process' : '/api/v1/process-multi');

        const formData = new FormData();
        const fieldName = isSingleFile ? 'file' : 'files';
        for (const file of files) {
            formData.append(fieldName, file);
        }

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
                    error: safeString(data.detail || data || 'An error occurred while processing your files.'),
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
