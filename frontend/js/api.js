/**
 * KryptLedg API Client
 * Handles all communication with the backend API
 */

const API_BASE_URL = 'https://cryptoclean-api.onrender.com';

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
    async exportResults(data, format = 'csv', taxYear = '') {
        try {
            let url, method, body;
            if (format === 'pdf') {
                url = new URL(`${API_BASE_URL}/api/v1/report/pdf`);
                method = 'POST';
                body = JSON.stringify({ data: data, tax_year: taxYear || undefined });
            } else {
                url = new URL(`${API_BASE_URL}/api/v1/export`);
                method = 'POST';
                body = JSON.stringify({ data: data, tax_year: taxYear || undefined, format: 'csv' });
            }

            const response = await fetch(url.toString(), {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: body
            });

            if (response.ok) {
                const blob = await response.blob();
                const downloadUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = downloadUrl;
                a.download = `kryptledg-report-${new Date().toISOString().split('T')[0]}.${format === 'pdf' ? 'pdf' : 'csv'}`;
                a.click();
                URL.revokeObjectURL(downloadUrl);
                return { success: true };
            } else {
                const errData = await response.json().catch(() => ({}));
                return { success: false, error: errData.detail || 'Export failed.' };
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
