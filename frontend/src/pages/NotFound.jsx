import { Link } from 'react-router-dom';
import { FileQuestion } from 'lucide-react';

const NotFound = () => {
    return (
        <div className="flex-center" style={{ width: '100vw', height: '100vh', background: '#05070a', color: '#fff' }}>
            <div className="glass animate-fade-in" style={{ padding: '48px', textAlign: 'center', maxWidth: '440px' }}>
                <div className="flex-center" style={{ width: '64px', height: '64px', margin: '0 auto 24px', borderRadius: '50%', background: 'rgba(239, 68, 68, 0.1)', color: 'var(--error)' }}>
                    <FileQuestion size={32} />
                </div>
                <h1 className="gradient-text" style={{ fontSize: '48px', fontWeight: '900', marginBottom: '8px' }}>404</h1>
                <h2 style={{ fontSize: '20px', fontWeight: '600', marginBottom: '16px' }}>Page Not Found</h2>
                <p style={{ color: 'var(--text-muted)', marginBottom: '32px', lineHeight: '1.6' }}>
                    The page you are looking for does not exist or has been moved.
                    If you were looking for the setup page, it is only available during initial system configuration.
                </p>
                <Link to="/" className="btn-primary" style={{ padding: '12px 24px', textDecoration: 'none', display: 'inline-block' }}>
                    Return to Dashboard
                </Link>
            </div>
        </div>
    );
};

export default NotFound;
