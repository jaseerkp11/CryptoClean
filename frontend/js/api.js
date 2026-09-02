/**
 * CryptoClean API Client
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
        formData.append('timezone', timezone || '');
        formData.append('plan', plan);
        if (accounting) {
            formData.append('accounting', 'true');
        }

        const endpoint = accounting ? '/api/v1/account' : '/api/v1/process';

        try {
            const response = await fetch(`${API_BASE_URL}${endpoint}`, {
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
    }
};
