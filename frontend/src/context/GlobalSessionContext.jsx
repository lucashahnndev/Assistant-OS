import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { api } from '../hooks/api';

const GlobalSessionContext = createContext(null);

export const GlobalSessionProvider = ({ children }) => {
    const [activeSessionId, setActiveSessionId] = useState(null);
    const [connectionStatus, setConnectionStatus] = useState('offline'); // 'offline' | 'connecting' | 'online' | 'error'
    const [lastEventAt, setLastEventAt] = useState(null);
    
    const [messages, setMessages] = useState([]);
    const [thoughts, setThoughts] = useState([]);
    const [workers, setWorkers] = useState([]);
    const [mediaCards, setMediaCards] = useState([]);

    const wsRef = useRef(null);
    const listenersRef = useRef(new Set());

    const pushGlobalThought = useCallback((thoughtText) => {
        if (!thoughtText) return;
        setThoughts(prev => {
            if (prev[prev.length - 1]?.text === thoughtText) return prev;
            return [...prev, { text: thoughtText, ts: Date.now() }].slice(-50);
        });
    }, []);

    const setGlobalWorkers = useCallback((newWorkers) => {
        setWorkers(newWorkers.slice(-50));
    }, []);

    const clearGlobalPanel = useCallback(() => {
        setThoughts([]);
        setWorkers([]);
    }, []);

    const fetchActiveSession = useCallback(async () => {
        try {
            const data = await api.get('/sessions/active?interface=web');
            if (data && data.session_id) {
                setActiveSessionId(data.session_id);
            }
        } catch (error) {
            console.error('GlobalSessionProvider: Failed to fetch active session', error);
        }
    }, []);

    useEffect(() => {
        // Initial fetch of active session
        fetchActiveSession();
    }, [fetchActiveSession]);

    const addWebSocketListener = useCallback((callback) => {
        listenersRef.current.add(callback);
    }, []);

    const removeWebSocketListener = useCallback((callback) => {
        listenersRef.current.delete(callback);
    }, []);

    const sendWebSocketMessage = useCallback((payload) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(payload));
            return true;
        }
        return false;
    }, []);

    useEffect(() => {
        if (!activeSessionId) return;

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${activeSessionId}`;
        
        if (wsRef.current) {
            if (wsRef.current.url === wsUrl && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
                return;
            } else {
                wsRef.current.close();
                wsRef.current = null;
            }
        }

        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            setConnectionStatus('online');
        };

        ws.onclose = () => {
            setConnectionStatus('offline');
            wsRef.current = null;
        };

        ws.onerror = () => {
            setConnectionStatus('error');
        };

        ws.onmessage = (event) => {
            setLastEventAt(Date.now());
            try {
                const data = JSON.parse(event.data);

                // --- P2A: Internal state management ---
                if (data.type === 'worker_state') {
                    setWorkers(prev => {
                        const next = [...prev];
                        const idx = next.findIndex(w => w.work_id === data.data?.work_id);
                        if (idx >= 0) next[idx] = { ...next[idx], ...data.data };
                        else if (data.data) next.push(data.data);
                        return next.slice(-50);
                    });
                } else if (data.type === 'system_metrics' || data.type === 'system_health') {
                    if (data.data?.active_workers) {
                        setWorkers(data.data.active_workers.slice(-50));
                    }
                }
                // --------------------------------------

                // Dispatch to all subscribers
                listenersRef.current.forEach(listener => {
                    try {
                        listener(data, event);
                    } catch (err) {
                        console.error('Error in websocket listener:', err);
                    }
                });
            } catch (err) {
                console.error('Failed to parse websocket message', err);
            }
        };

        return () => {
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, [activeSessionId]);

    const value = {
        activeSessionId,
        setActiveSessionId,
        connectionStatus,
        lastEventAt,
        messages,
        thoughts,
        workers,
        mediaCards,
        refreshActiveSession: fetchActiveSession,
        pushGlobalThought,
        setGlobalWorkers,
        clearGlobalPanel,
        addWebSocketListener,
        removeWebSocketListener,
        sendWebSocketMessage
    };

    return (
        <GlobalSessionContext.Provider value={value}>
            {children}
        </GlobalSessionContext.Provider>
    );
};

export const useGlobalSession = () => {
    const context = useContext(GlobalSessionContext);
    if (!context) {
        throw new Error('useGlobalSession must be used within a GlobalSessionProvider');
    }
    return context;
};
