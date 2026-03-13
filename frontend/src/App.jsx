import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import { VideoPlayerProvider } from './context/VideoPlayerContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import VideoPlayerDock from './components/VideoPlayerDock';
import DashboardLayout from './layouts/DashboardLayout';

// Pages (to be implemented)
import Login from './pages/Login';
import Setup from './pages/Setup';
import Dashboard from './pages/Dashboard';
import Chat from './pages/Chat';
import Capabilities from './pages/Capabilities';
import Memory from './pages/Memory';
import Settings from './pages/Settings';
import Tasks from './pages/Tasks';
import MessagingAccess from './pages/MessagingAccess';
import Security from './pages/Security';
import NotFound from './pages/NotFound';

import { Toaster } from 'react-hot-toast';

const AppRoutes = () => {
    const { initialized, loading, agentName } = useAuth();

    if (loading) {
        return (
            <div className="flex-center" style={{ height: '100vh', width: '100vw', background: 'var(--bg-color)' }}>
                <div className="gradient-text animate-pulse" style={{ fontSize: '32px', fontWeight: '900', letterSpacing: '-0.02em' }}>
                    {agentName}
                </div>
            </div>
        );
    }

    return (
        <Routes>
            <Route path="/login" element={<Login />} />

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
                <Route index element={<Dashboard />} />
                <Route path="chat" element={<Chat />} />
                <Route path="capabilities" element={<Capabilities />} />
                <Route path="memory" element={<Memory />} />
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
                        <Toaster position="top-right"
                            containerStyle={{ zIndex: 12000 }}
                            toastOptions={{
                                style: {
                                    background: 'var(--card-bg)',
                                    color: 'var(--text-main)',
                                    border: '1px solid var(--card-border)',
                                    backdropFilter: 'var(--surface-blur)',
                                    borderRadius: '12px',
                                    fontSize: '14px',
                                    fontWeight: '600',
                                    boxShadow: 'var(--shadow-lg)',
                                },
                            }}
                        />
                        <AppRoutes />
                        <VideoPlayerDock />
                    </VideoPlayerProvider>
                </AuthProvider>
            </ThemeProvider>
        </BrowserRouter>
    );
}

export default App;
