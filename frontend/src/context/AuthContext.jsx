import { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialized, setInitialized] = useState(true);
    const [agentName, setAgentName] = useState('...');

    const checkStatus = async () => {
        try {
            // Fetch agent name from public status endpoint (works before login)
            try {
                let statusData = null;
                const statusRes = await fetch('/api/system/status');
                if (statusRes.ok) {
                    statusData = await statusRes.json();
                } else {
                    const legacyStatusRes = await fetch('/api/status');
                    if (legacyStatusRes.ok) {
                        statusData = await legacyStatusRes.json();
                    }
                }
                if (statusData?.agent_name) {
                    setAgentName(statusData.agent_name);
                }
            } catch (err) {
                console.error("Failed to fetch public system status", err);
            }

            // First check if initialized
            const bootRes = await fetch('/api/auth/initialized');
            if (bootRes.ok) {
                const bootData = await bootRes.json();
                setInitialized(bootData.initialized);
            }

            const res = await fetch('/api/auth/me');
            if (res.ok) {
                const data = await res.json();
                setUser(data);
                setInitialized(true);
            } else {
                setUser(null);
            }
        } catch (error) {
            console.error("Auth check failed", error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        checkStatus();
    }, []);

    const login = async (username, password) => {
        const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        if (res.ok) {
            await checkStatus();
            return { success: true };
        }
        const data = await res.json();
        return { success: false, error: data.detail || 'Login failed' };
    };

    const logout = async () => {
        await fetch('/api/auth/logout', { method: 'POST' });
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, loading, initialized, agentName, login, logout, checkStatus }}>
            {children}
        </AuthContext.Provider>
    );
};

export const useAuth = () => useContext(AuthContext);
