import { createContext, useContext, useState, useEffect } from 'react';

const ThemeContext = createContext(null);

export const ThemeProvider = ({ children }) => {
    const [theme, setTheme] = useState(() => {
        const saved = localStorage.getItem('theme');
        return saved || 'dark';
    });

    useEffect(() => {
        const root = window.document.documentElement;

        const applyTheme = (themeValue) => {
            root.classList.remove('light-theme', 'dark-theme');

            let effectiveTheme = themeValue;
            if (themeValue === 'system') {
                effectiveTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            }

            if (effectiveTheme === 'light') {
                root.classList.add('light-theme');
            } else {
                root.classList.add('dark-theme');
            }
        };

        applyTheme(theme);
        localStorage.setItem('theme', theme);

        // Listen for system changes if in system mode
        if (theme === 'system') {
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            const handleChange = () => applyTheme('system');
            mediaQuery.addEventListener('change', handleChange);
            return () => mediaQuery.removeEventListener('change', handleChange);
        }
    }, [theme]);

    return (
        <ThemeContext.Provider value={{ theme, setTheme }}>
            {children}
        </ThemeContext.Provider>
    );
};

export const useTheme = () => useContext(ThemeContext);
