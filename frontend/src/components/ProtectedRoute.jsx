import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export const ProtectedRoute = ({ children }) => {
    const { user, loading, initialized } = useAuth();
    const location = useLocation();

    if (loading) {
        return (
            <div className="flex-center" style={{ height: '100vh', width: '100vw' }}>
                <div className="gradient-text" style={{ fontSize: '24px', fontWeight: 'bold' }}>Atlas OS</div>
            </div>
        );
    }

    if (!initialized) {
        return <Navigate to="/setup" replace />;
    }

    if (!user) {
        return <Navigate to="/login" state={{ from: location }} replace />;
    }

    return children;
};
