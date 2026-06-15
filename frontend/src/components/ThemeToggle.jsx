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
        <div style={{
            display: 'flex',
            gap: '2px',
            padding: '2px',
            borderRadius: 'var(--radius-md)',
            background: 'var(--card-bg)',
            border: '1px solid var(--card-border)',
        }}>
            {themes.map((t) => {
                const Icon = t.icon;
                const isActive = theme === t.id;
                return (
                    <button
                        key={t.id}
                        onClick={() => setTheme(t.id)}
                        title={t.label}
                        className={isActive ? "btn-primary" : "btn-ghost"}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: '28px',
                            height: '28px',
                            padding: '4px',
                            borderRadius: 'var(--radius-sm)',
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
