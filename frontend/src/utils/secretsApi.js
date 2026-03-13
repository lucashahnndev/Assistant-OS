import { api } from '../hooks/api';

export async function listSecretRefs() {
    const data = await api.get('/secrets/refs');
    return Array.isArray(data?.keys) ? data.keys : [];
}

export async function listSecretEntries() {
    const data = await api.get('/secrets/entries');
    return {
        entries: Array.isArray(data?.entries) ? data.entries : [],
        vault: data?.vault || {},
    };
}

export async function auditEnvSecrets() {
    return api.get('/secrets/audit-env');
}

export async function importEnvSecrets({ overwrite = false } = {}) {
    return api.post('/secrets/import-env', { overwrite });
}

export async function createSecret({ key, value, overwrite = false }) {
    return api.post('/secrets', { key, value, overwrite });
}

export async function deleteSecret(key) {
    return api.delete(`/secrets/${encodeURIComponent(key)}`);
}
