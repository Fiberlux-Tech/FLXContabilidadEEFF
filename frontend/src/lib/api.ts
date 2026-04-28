// src/lib/api.ts
import { API_CONFIG } from '@/config';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

/**
 * A centralized request function that handles responses and errors.
 * We use a generic <T> to type the successful response.
 * @param {string} url - The endpoint URL (e.g., '/auth/login')
 * @param {object} options - The standard 'fetch' options object
 * @returns {Promise<T>} - The JSON response data
 * @throws {Error} - Throws an error for non-successful HTTP responses
 */
async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
    const config: RequestInit = {
        ...options,
        credentials: 'include', // Always send cookies
    };

    // 2. Set default headers, but allow overrides
    const headers = new Headers(config.headers);

    // 3. Smartly set Content-Type, unless it's FormData
    if (config.body && !(config.body instanceof FormData)) {
        // Default to JSON if not specified
        if (!headers.has(API_CONFIG.HTTP.CONTENT_TYPE_HEADER)) {
            headers.set(API_CONFIG.HTTP.CONTENT_TYPE_HEADER, API_CONFIG.HTTP.CONTENT_TYPE_JSON);
        }
        // Stringify body if it's a JS object
        config.body = JSON.stringify(config.body);
    }

    config.headers = headers;

    // 5. Make the request
    const response = await fetch(`${API_BASE_URL}${url}`, config);

    // 6. GLOBAL ERROR HANDLER (for all non-ok responses)
    if (!response.ok) {
        let errorMessage = `HTTP ${response.status}: ${response.statusText}`;

        // Only try to parse JSON if content type indicates JSON
        const contentType = response.headers.get('content-type');
        if (contentType?.includes(API_CONFIG.HTTP.CONTENT_TYPE_JSON)) {
            try {
                const err = await response.json();
                errorMessage = err.message || err.error || errorMessage;
            } catch (e) {
                // If JSON parsing fails, keep the HTTP status message
            }
        }

        // This is where the 401 error will now be caught and thrown
        throw new Error(errorMessage);
    }

    // 7. SUCCESS HANDLER — unwrap standard { status, data } envelope
    const contentType = response.headers.get("content-type");
    if (contentType && contentType.includes(API_CONFIG.HTTP.CONTENT_TYPE_JSON)) {
        const json = await response.json();
        // If the backend wraps in { status: "ok", data: ... }, unwrap it
        if (json && json.status === 'ok' && 'data' in json) {
            return json.data as T;
        }
        return json as T;
    }

    // Return undefined for 204 No Content, cast as T
    return undefined as T;
}

// --- Our clean, typed API methods ---

export const api = {
    get: <T>(url: string) => request<T>(url, { method: API_CONFIG.HTTP.METHOD_GET }),

    post: <T>(url: string, data: Record<string, unknown>, options?: { signal?: AbortSignal }) =>
        request<T>(url, { method: API_CONFIG.HTTP.METHOD_POST, body: data as unknown as BodyInit, ...options }),

    postForm: <T>(url: string, formData: FormData) => request<T>(url, { method: API_CONFIG.HTTP.METHOD_POST, body: formData }),

    put: <T>(url: string, data: Record<string, unknown>) =>
        request<T>(url, { method: 'PUT', body: data as unknown as BodyInit }),

    patch: <T>(url: string, data: Record<string, unknown>) =>
        request<T>(url, { method: 'PATCH', body: data as unknown as BodyInit }),
};