import { useState, useEffect } from 'react';
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import ThemeToggle from '../components/ThemeToggle';
import { useI18n } from '../i18n';
import {
    LayoutDashboard,
    MessageSquare,
    Settings,
    Cpu,
    Database,
    LogOut,
    User as UserIcon,
    ClipboardCheck,
    Shield,
    ChevronLeft,
    ChevronRight,
    ChevronUp,
    ChevronDown,
    PanelLeftOpen,
    PanelLeftClose,
    Menu,
    X as CloseIcon
} from 'lucide-react';

const DashboardLayout = () => {
    const { user, logout, agentName } = useAuth();
    const navigate = useNavigate();
    const { t } = useI18n();
    const location = useLocation();
    const isChat = location.pathname === '/chat' || location.pathname === '/chat/';
    const [isCollapsed, setIsCollapsed] = useState(() => {
        return localStorage.getItem('sidebar-collapsed') === 'true';
    });
    const [isDrawerOpen, setIsDrawerOpen] = useState(false);
    const [isHeaderCollapsed, setIsHeaderCollapsed] = useState(() => {
        return localStorage.getItem('header-collapsed') === 'true';
    });
    // Breakpoint: Mobile and Tablet (<= 1024px) use the drawer sidebar
    const [isBelowDesktop, setIsBelowDesktop] = useState(window.innerWidth <= 1024);

    useEffect(() => {
        localStorage.setItem('sidebar-collapsed', isCollapsed);
    }, [isCollapsed]);

    useEffect(() => {
        localStorage.setItem('header-collapsed', isHeaderCollapsed);
    }, [isHeaderCollapsed]);

    useEffect(() => {
        const handleResize = () => {
            const isBelow = window.innerWidth <= 1024;
            setIsBelowDesktop(isBelow);
            if (!isBelow) setIsDrawerOpen(false);
        };
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);


    useEffect(() => {
        // Close drawer on route change
        setIsDrawerOpen(false);
    }, [location.pathname]);

    const handleLogout = async () => {
        await logout();
        navigate('/login');
    };

    const navItems = [
        { to: '/', icon: LayoutDashboard, label: t('nav.dashboard') },
        { to: '/chat', icon: MessageSquare, label: t('nav.console') },
        { to: '/tasks', icon: ClipboardCheck, label: t('nav.tasks') },
        { to: '/skills', icon: Cpu, label: t('nav.skills') },
        { to: '/memory', icon: Database, label: t('nav.memory') },
        { to: '/messaging-access', icon: Shield, label: t('nav.security') },
        { to: '/settings', icon: Settings, label: t('nav.settings') },
    ];

    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            width: '100%',
            height: '100%',
            background: 'transparent',
            color: 'var(--text-primary)',
            transition: 'background 0.3s ease',
            overflow: 'hidden'
        }}>
            {/* Global Header */}
            {!isHeaderCollapsed && (
                <header className="glass" style={{
                    height: 'var(--header-height)',
                    minHeight: 'var(--header-height)',
                    width: 'calc(100% - 1rem)',
                    margin: '0.5rem 0.5rem 0',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0 1.25rem',
                    borderRadius: 'var(--radius-md)',
                    borderBottom: '1px solid var(--card-border)',
                    zIndex: 1000,
                    flexShrink: 0
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
                        <button
                            className="btn-ghost"
                            onClick={() => {
                                if (isBelowDesktop) {
                                    setIsDrawerOpen(true);
                                } else {
                                    setIsCollapsed(!isCollapsed);
                                }
                            }}
                            style={{ padding: '0.5rem', marginRight: '-0.5rem', color: 'var(--text-primary)' }}
                            title={isBelowDesktop ? t('header.menu') : t('header.toggle_sidebar')}
                        >
                            <Menu size={20} />
                        </button>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
                            <div style={{
                                width: '32px',
                                height: '32px',
                                background: 'var(--accent-color)',
                                borderRadius: 'var(--radius-sm)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                color: 'white',
                                fontWeight: '900',
                                fontSize: '1.2rem'
                            }}>
                                {agentName.charAt(0).toUpperCase()}
                            </div>
                            {!isBelowDesktop && (
                                <span style={{ fontWeight: '800', fontSize: '1.1rem', letterSpacing: '-0.02em', textTransform: 'uppercase' }}>{agentName}</span>
                            )}
                        </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                        <ThemeToggle />
                        <button
                            className="btn-ghost"
                            onClick={() => {
                                setIsDrawerOpen(false);
                                setIsHeaderCollapsed(true);
                            }}
                            style={{ padding: '0.45rem', color: 'var(--text-muted)' }}
                            title={t('header.collapse')}
                        >
                            <ChevronUp size={18} />
                        </button>
                    </div>
                </header>
            )}

            {isHeaderCollapsed && (
                <button
                    className="glass btn-ghost"
                    onClick={() => setIsHeaderCollapsed(false)}
                    title="Expandir cabeçalho"
                    style={{
                        position: 'fixed',
                        top: isBelowDesktop ? '8px' : '10px',
                        right: isBelowDesktop ? '8px' : '14px',
                        zIndex: 2102,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        padding: isBelowDesktop ? '8px' : '8px 12px',
                        borderRadius: '999px',
                        background: 'var(--card-bg)',
                        border: '1px solid var(--card-border)',
                        color: 'var(--text-primary)',
                        boxShadow: 'var(--shadow-md)'
                    }}
                >
                    <ChevronDown size={16} />
                    {!isBelowDesktop && <span style={{ fontSize: '12px', fontWeight: 700 }}>Header</span>}
                </button>
            )}

            <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
                {/* Sidebar */}
                <aside className={`glass ${isBelowDesktop ? 'sidebar-drawer' : ''} ${isDrawerOpen ? 'open' : ''}`} style={{
                    width: isCollapsed && !isBelowDesktop ? '0px' : 'var(--sidebar-width)',
                    margin: isBelowDesktop ? '0' : (isCollapsed ? '0.5rem 0 0.5rem 0' : '0.5rem 0 0.5rem 0.5rem'),
                    display: 'flex',
                    flexDirection: 'column',
                    padding: (isCollapsed && !isBelowDesktop) ? '0' : '1rem 0.625rem',
                    opacity: (isCollapsed && !isBelowDesktop) ? 0 : 1,
                    transition: 'var(--transition-base)',
                    position: isBelowDesktop ? 'fixed' : 'relative',
                    overflow: 'hidden',
                    borderRadius: isBelowDesktop ? '0 var(--radius-md) var(--radius-md) 0' : 'var(--radius-md)',
                    zIndex: isBelowDesktop ? 2001 : 1
                }}>
                    {isBelowDesktop && (
                        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '1rem' }}>
                            <button className="btn-ghost" onClick={() => setIsDrawerOpen(false)} style={{ padding: '0.5rem' }}>
                                <CloseIcon size={20} />
                            </button>
                        </div>
                    )}
                    <nav className="custom-scrollbar" style={{
                        flex: 1,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '0.25rem',
                        overflowY: 'auto',
                        marginRight: '-0.25rem',
                        paddingRight: '0.25rem'
                    }}>
                        {navItems.map((item) => (
                            <NavLink
                                key={item.to}
                                to={item.to}
                                title={isCollapsed && !isBelowDesktop ? item.label : ''}
                                className={({ isActive }) => `btn-ghost ${isActive ? 'active' : ''}`}
                                style={({ isActive }) => ({
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.75rem',
                                    color: isActive ? 'var(--accent-color)' : 'var(--text-secondary)',
                                    background: isActive ? 'var(--accent-glow)' : 'transparent',
                                    justifyContent: isCollapsed && !isBelowDesktop ? 'center' : 'flex-start',
                                    padding: '0.75rem 1rem',
                                    fontSize: '0.9375rem',
                                    borderRadius: 'var(--radius-sm)',
                                    transition: 'var(--transition-fast)',
                                    flexShrink: 0
                                })}
                            >
                                <item.icon size={20} />
                                {(!isCollapsed || isBelowDesktop) && <span style={{ fontWeight: '600' }}>{item.label}</span>}
                            </NavLink>
                        ))}
                    </nav>

                    {/* Footer Controls */}
                    <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                        <div className="glass" style={{
                            padding: (isCollapsed && !isBelowDesktop) ? '0.5rem' : '0.625rem 0.75rem',
                            background: 'rgba(255, 255, 255, 0.02)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: (isCollapsed && !isBelowDesktop) ? 'center' : 'flex-start',
                            gap: '0.75rem',
                            borderRadius: 'var(--radius-sm)',
                            border: '1px solid var(--card-border)',
                            boxShadow: 'none'
                        }}>
                            <div className="flex-center" style={{
                                width: '2rem',
                                height: '2rem',
                                borderRadius: 'var(--radius-xs)',
                                background: 'var(--accent-glow)',
                                color: 'var(--accent-color)',
                                flexShrink: 0
                            }}>
                                <UserIcon size={16} />
                            </div>
                            {(!isCollapsed || isBelowDesktop) && (
                                <>
                                    <div style={{ flex: 1, overflow: 'hidden' }}>
                                        <p style={{ fontSize: '0.8125rem', fontWeight: '700', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                            {user?.display_name || user?.username}
                                        </p>
                                        <p style={{ fontSize: '0.625rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: '800' }}>{user?.role}</p>
                                    </div>
                                    <button onClick={handleLogout} className="btn-ghost" style={{ padding: '0.25rem', color: 'var(--error)' }}>
                                        <LogOut size={16} />
                                    </button>
                                </>
                            )}
                        </div>
                    </div>
                </aside>

                {/* Main Content */}
                <main style={{
                    flex: 1,
                    padding: isBelowDesktop ? '0.5rem' : '0.5rem 1rem 1rem 1rem',
                    minHeight: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    overflow: 'hidden'
                }}>
                    <div className={(isChat || location.pathname === '/skills' || location.pathname === '/memory') ? "" : "custom-scrollbar"} style={{
                        flex: 1,
                        position: 'relative',
                        minHeight: 0,
                        overflowY: (isChat || location.pathname === '/skills' || location.pathname === '/memory') ? 'hidden' : 'auto',
                        borderRadius: 'var(--radius-md)',
                        padding: (isChat || isBelowDesktop) ? '0' : '0 var(--space-2)',
                        display: 'flex',
                        flexDirection: 'column',
                        background: 'rgba(255, 255, 255, 0.01)',
                        border: '1px solid var(--card-border)'
                    }}>
                        <Outlet />
                    </div>
                </main>

                {isBelowDesktop && (
                    <div
                        className={`sidebar-overlay ${isDrawerOpen ? 'open' : ''}`}
                        onClick={() => setIsDrawerOpen(false)}
                    />
                )}
            </div>
        </div>
    );
};

export default DashboardLayout;
