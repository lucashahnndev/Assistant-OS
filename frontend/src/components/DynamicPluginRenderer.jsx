import React, { Suspense } from 'react';
import { Loader2 } from 'lucide-react';
import pluginRegistry from '../plugins_ui/registry';

// Generic fallback renderer for capabilities that don't provide custom UIs
const GenericDataCard = ({ title, payload }) => {
    // Attempt to stringify the payload nicely
    const displayData = typeof payload === 'object' 
        ? JSON.stringify(payload, null, 2) 
        : String(payload);

    return (
        <div className="relative p-4 rounded-xl border border-[var(--glass-border)] bg-[var(--glass-bg)] backdrop-blur-md overflow-hidden">
            <h4 className="text-sm font-semibold text-white/90 mb-2 capitalize">{title || 'Data Payload'}</h4>
            <pre className="text-xs text-white/70 overflow-auto max-h-32 p-2 rounded bg-black/20">
                {displayData}
            </pre>
        </div>
    );
};

const DynamicPluginRenderer = ({ capabilityId, actionId, payload, title }) => {
    // Check if the capability has a custom registered UI
    const PluginComponent = pluginRegistry[capabilityId];

    if (PluginComponent) {
        return (
            <Suspense fallback={
                <div className="flex items-center justify-center p-4 rounded-xl border border-[var(--glass-border)] bg-[var(--glass-bg)] backdrop-blur-md">
                    <Loader2 className="w-5 h-5 text-[var(--primary-color)] animate-spin" />
                </div>
            }>
                <PluginComponent payload={payload} actionId={actionId} title={title} />
            </Suspense>
        );
    }

    // Fallback to generic JSON renderer
    return <GenericDataCard title={title || capabilityId} payload={payload} />;
};

export default DynamicPluginRenderer;
