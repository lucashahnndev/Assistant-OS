/**
 * Plugin UI Registry
 * Maps capability IDs to lazily loaded custom React components.
 * 
 * If a capability requires a highly customized UI (e.g., a 3D map, a complex Gantt chart),
 * you add its component here. The frontend will lazy-load the component only when the capability
 * is executed by an agent.
 */
import { lazy } from 'react';

const pluginRegistry = {
    // Example:
    // 'weather_control': lazy(() => import('./weather_control/WeatherMapWidget.jsx')),
    // 'cloudflare_tunnel': lazy(() => import('./cloudflare_tunnel/TunnelMonitor.jsx')),
};

export default pluginRegistry;
