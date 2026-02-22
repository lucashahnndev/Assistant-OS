import { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialized, setInitialized] = useState(true);
    const [agentName, setAgentName] = useState('...');

    const checkStatus = async () => {
        try {
            // First check if initialized
            const bootRes = await fetch('/api/auth/initialized');
            if (bootRes.ok) {
                const bootData = await bootRes.json();
                setInitialized(bootData.initialized);
            }

            // Fetch agent name from config
            try {
                const configRes = await fetch('/api/system/config');
                if (configRes.ok) {
                    const configData = await configRes.json();
                    if (configData.agent?.agent_name) {
                        setAgentName(configData.agent.agent_name);
                    }
                }
            } catch (err) {
                console.error("Failed to fetch agent config", err);
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
