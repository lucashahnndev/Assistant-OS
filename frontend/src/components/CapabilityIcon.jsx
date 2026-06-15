import { useState } from 'react';
import { Puzzle } from 'lucide-react';

const CapabilityIcon = ({
    capabilityId = '',
    assets = null,
    variant = 'inline',
    size,
}) => {
    const [imgError, setImgError] = useState(false);
    const iconSize = Number(size || (variant === 'display' ? 26 : (variant === 'hub' ? 24 : 12)));
    const shellSize = Number(size || (variant === 'display' ? 40 : (variant === 'hub' ? 40 : 18)));

    let iconUrl = null;
    if (assets && !imgError) {
        // Resolve best available asset
        if (iconSize <= 16 && assets.icon_16) {
            iconUrl = `/api/capabilities/${capabilityId}/icon/16x16`;
        } else if (iconSize <= 32 && assets.icon_32) {
            iconUrl = `/api/capabilities/${capabilityId}/icon/32x32`;
        } else if (iconSize <= 64 && assets.icon_64) {
            iconUrl = `/api/capabilities/${capabilityId}/icon/64x64`;
        } else if (assets.icon_svg) {
            iconUrl = `/api/capabilities/${capabilityId}/icon/svg`;
        }
    }

    return (
        <span
            className={variant === 'hub' ? 'capability-icon-box' : undefined}
            style={variant === 'hub' ? {} : {
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
            {iconUrl ? (
                <img
                    src={iconUrl}
                    alt=""
                    width={iconSize}
                    height={iconSize}
                    style={{ 
                        borderRadius: variant === 'display' ? '8px' : '4px', 
                        objectFit: 'contain',
                        width: `${iconSize}px`,
                        height: `${iconSize}px`
                    }}
                    onError={() => setImgError(true)}
                />
            ) : (
                <Puzzle size={iconSize} color={variant === 'hub' ? 'currentColor' : '#a78bfa'} />
            )}
        </span>
    );
};

export default CapabilityIcon;
