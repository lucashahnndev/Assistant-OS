import React, { useState, useEffect } from 'react';

/**
 * PageHeader component for consistent layout across different management screens.
 * 
 * @param {string} title - The title of the page.
 * @param {string} subtitle - A short description or subtitle.
 * @param {React.ReactNode} children - Actions or supplemental UI like search bars.
 */
const PageHeader = ({ title, subtitle, children }) => {
    const [isMobile, setIsMobile] = useState(window.innerWidth <= 640);

    useEffect(() => {
        const handleResize = () => setIsMobile(window.innerWidth <= 640);
        window.addEventListener('resize', handleResize);
        return () => window.removeEventListener('resize', handleResize);
    }, []);

    return (
        <div style={{
            display: 'flex',
            flexDirection: isMobile ? 'column' : 'row',
            justifyContent: 'space-between',
            alignItems: isMobile ? 'flex-start' : 'center',
            padding: isMobile ? 'var(--space-4) var(--space-4)' : 'var(--space-6) var(--space-6)',
            borderBottom: '1px solid var(--card-border)',
            background: 'rgba(0, 0, 0, 0.02)',
            marginBottom: isMobile ? 'var(--space-3)' : 'var(--space-6)',
            gap: isMobile ? 'var(--space-3)' : 'var(--space-4)'
        }}>
            <div style={{ width: isMobile ? '100%' : 'auto' }}>
                <h2 style={{
                    fontSize: isMobile ? '1.25rem' : '1.5rem',
                    fontWeight: '800',
                    color: 'var(--text-primary)',
                    letterSpacing: '-0.02em',
                    margin: 0
                }}>
                    {title}
                </h2>
                {subtitle && (
                    <p style={{
                        fontSize: '0.875rem',
                        color: 'var(--text-muted)',
                        marginTop: 'var(--space-1)'
                    }}>
                        {subtitle}
                    </p>
                )}
            </div>
            {children && (
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: isMobile ? 'var(--space-2)' : 'var(--space-4)',
                    width: isMobile ? '100%' : 'auto',
                    flexWrap: 'wrap'
                }}>
                    {children}
                </div>
            )}
        </div>
    );
};

export default PageHeader;
