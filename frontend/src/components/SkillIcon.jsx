import { useMemo, useState } from 'react';
import { getSkillVisual } from '../utils/skillVisuals';

const SkillIcon = ({
    skillId = '',
    skillName = '',
    actionId = '',
    iconKey = '',
    iconUrl = '',
    variant = 'inline',
    size,
}) => {
    const visual = useMemo(
        () => getSkillVisual({ skillId, skillName, actionId, iconKey, iconUrl }),
        [skillId, skillName, actionId, iconKey, iconUrl],
    );
    const [logoError, setLogoError] = useState(false);

    const iconSize = Number(size || (variant === 'display' ? 26 : 12));
    const shellSize = Number(size || (variant === 'display' ? 40 : 18));
    const Icon = visual.Icon;
    const shouldUseLogo = Boolean(visual.logoUrl) && !logoError;
    const logoSrc = shouldUseLogo ? `/api/favicon?url=${encodeURIComponent(visual.logoUrl)}` : '';

    return (
        <span
            title={visual.label}
            aria-label={visual.label}
            style={{
                width: `${shellSize}px`,
                height: `${shellSize}px`,
                borderRadius: variant === 'display' ? '12px' : '6px',
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                background: variant === 'display' ? 'rgba(255,255,255,0.04)' : 'rgba(255,255,255,0.03)',
                border: '1px solid var(--card-border)',
                overflow: 'hidden',
            }}
        >
            {shouldUseLogo ? (
                <img
                    src={logoSrc}
                    alt={visual.label}
                    width={iconSize}
                    height={iconSize}
                    style={{ borderRadius: variant === 'display' ? '8px' : '4px', objectFit: 'contain' }}
                    onError={() => setLogoError(true)}
                />
            ) : (
                <Icon size={iconSize} color={visual.color} />
            )}
        </span>
    );
};

export default SkillIcon;
