import { Sun, Moon, Monitor } from 'lucide-react';
import { useTheme } from '../context/ThemeContext';

const ThemeToggle = () => {
    const { theme, setTheme } = useTheme();

    const themes = [
        { id: 'light', icon: Sun, label: 'Light' },
        { id: 'dark', icon: Moon, label: 'Dark' },
        { id: 'system', icon: Monitor, label: 'System' },
    ];

    return (
        <div className="glass theme-hub" style={{
            display: 'flex',
            gap: '4px',
            padding: '4px',
            borderRadius: '100px',
            background: 'var(--card-bg)',
            border: '1px solid var(--card-border)',
            backdropFilter: 'blur(12px)',
        }}>
            {themes.map((t) => {
                const Icon = t.icon;
                const isActive = theme === t.id;
                return (
                    <button
                        key={t.id}
                        onClick={() => setTheme(t.id)}
                        title={t.label}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: '32px',
                            height: '32px',
                            borderRadius: '50%',
                            background: isActive ? 'var(--accent-color)' : 'transparent',
                            color: isActive ? '#fff' : 'var(--text-muted)',
                            transition: 'var(--transition)',
                            border: 'none',
                        }}
                    >
                        <Icon size={16} />
                    </button>
                );
            })}
        </div>
    );
};

export default ThemeToggle;
