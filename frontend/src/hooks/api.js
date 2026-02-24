const apiRequest = async (path, options = {}) => {
    const url = `/api${path}`;

    const headers = { ...options.headers };

    // Do not set Content-Type if body is FormData (browser will set it with boundary)
    if (!(options.body instanceof FormData)) {
        headers['Content-Type'] = 'application/json';
    }

    const response = await fetch(url, {
        ...options,
        credentials: 'include',
        headers,
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
        throw new Error(error.detail || 'API request failed');
    }

    if (response.status === 204) return null;
    return response.json();
};

export const api = {
    get: (path) => apiRequest(path),
    post: (path, body) => apiRequest(path, {
        method: 'POST',
        body: body instanceof FormData ? body : JSON.stringify(body)
    }),
    patch: (path, body) => apiRequest(path, {
        method: 'PATCH',
        body: body instanceof FormData ? body : JSON.stringify(body)
    }),
    put: (path, body) => apiRequest(path, {
        method: 'PUT',
        body: body instanceof FormData ? body : JSON.stringify(body)
    }),
    delete: (path) => apiRequest(path, { method: 'DELETE' }),
};
