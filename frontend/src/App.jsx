import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { VideoPlayerProvider } from './context/VideoPlayerContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import VideoPlayerDock from './components/VideoPlayerDock';
import WegenaSceneModal from './components/WegenaSceneModal';
import PwaInstallBanner from './components/PwaInstallBanner';
import DashboardLayout from './layouts/DashboardLayout';

// Pages (to be implemented)
import Login from './pages/Login';
import Setup from './pages/Setup';
import Overview from './pages/Overview';
import Chat from './pages/Chat';
import Capabilities from './pages/Capabilities';
import Memory from './pages/Memory';
import CognitionDiagnostics from './pages/CognitionDiagnostics';
import Settings from './pages/Settings';
import Tasks from './pages/Tasks';
import MessagingAccess from './pages/MessagingAccess';
import Security from './pages/Security';
import NotFound from './pages/NotFound';
import Nexus from './pages/Nexus';
import NexusScenePreview from './pages/NexusScenePreview';

import { Toaster } from 'react-hot-toast';

const AppRoutes = () => {
    const { initialized, loading, agentName } = useAuth();

    // Sync browser tab title with agent name from config
    useEffect(() => {
        if (agentName && agentName !== '...') {
            document.title = agentName;
        }
    }, [agentName]);

    const showLoader = loading;

    if (loading) {
        return (
            <div className="flex-center" style={{ height: '100vh', width: '100vw', background: 'var(--bg-color)', position: 'fixed', zIndex: 2147483647, inset: 0, overflow: 'hidden' }}>
                <style>{`
                    @keyframes loaderGlow {
                        from { opacity: 0; }
                        to { opacity: 1; }
                    }
                `}</style>
                <div style={{
                    position: 'absolute', inset: 0,
                    background: 'linear-gradient(180deg, #000000 0%, rgba(40, 15, 75, 0.35) 50%, #000000 100%)',
                    animation: 'loaderGlow 2s ease-in-out forwards'
                }} />
                <div className="gradient-text" style={{ fontSize: '42px', fontWeight: '900', letterSpacing: '0.15em', zIndex: 1, filter: 'drop-shadow(0 4px 8px rgba(0, 0, 0, 0.6))' }}>
                    {agentName}
                </div>
            </div>
        );
    }

    return (


            <Routes>
            <Route path="/login" element={<Login />} />
            <Route
                path="/__dev/nexus-scene"
                element={import.meta.env.DEV ? <NexusScenePreview /> : <Navigate to="/" replace />}
            />

            {/* Setup is only available if not initialized */}
            {!initialized ? (
                <Route path="/setup" element={<Setup />} />
            ) : (
                <Route path="/setup" element={<NotFound />} />
            )}

            <Route path="/" element={
                <ProtectedRoute>
                    <DashboardLayout />
                </ProtectedRoute>
            }>
                <Route index element={<Overview />} />
                <Route path="chat" element={<Chat />} />
                <Route path="nexus" element={<Nexus />} />
                <Route path="capabilities" element={<Capabilities />} />
                <Route path="memory" element={<Memory />} />
                <Route path="cognition" element={<CognitionDiagnostics />} />
                <Route path="tasks" element={<Tasks />} />
                <Route path="settings" element={<Settings />} />
                <Route path="security" element={<Security />} />
                <Route path="messaging-access" element={<MessagingAccess />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
};

function App() {
    return (
        <BrowserRouter>
            <ThemeProvider>
                <AuthProvider>
                    <VideoPlayerProvider>
                        <Toaster
                            position="top-right"
                            containerStyle={{ zIndex: 12000 }}
                            toastOptions={{ style: { background: 'transparent', boxShadow: 'none', padding: 0 } }}
                        />
                        <AppRoutes />
                        <VideoPlayerDock />
                        <WegenaSceneModal />
                        <PwaInstallBanner />
                    </VideoPlayerProvider>
                </AuthProvider>
            </ThemeProvider>
        </BrowserRouter>
    );
}

export default App;
