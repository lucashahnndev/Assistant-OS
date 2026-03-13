(() => {
    const vH = window.innerHeight;
    const vW = window.innerWidth;
    const vArea = vH * vW;
    
    const interactive = [];
    const markers = [];
    const walk = (node) => {
        if (node.nodeType === 1) {
            const tagName = node.tagName.toLowerCase();
            if (['script', 'style', 'noscript', 'canvas'].includes(tagName)) return;

            const rect = node.getBoundingClientRect();
            if (rect.width < 2 || rect.height < 2) {
                for (let child of node.children) walk(child);
                return;
            }

            const inViewport = (rect.bottom > 0 && rect.right > 0 && rect.top < vH && rect.left < vW);
            const inExtendedViewport = (rect.bottom > 0 && rect.right > 0 && rect.top < (vH + 600) && rect.left < vW);
        
            if (!inExtendedViewport) {
                for (let child of node.children) walk(child);
                return;
            }

            const role = node.getAttribute('role') || '';
            const style = window.getComputedStyle(node);
            
            // Filter out hidden elements
            if (node.getAttribute('aria-hidden') === 'true' || 
                style.display === 'none' || 
                style.visibility === 'hidden' || 
                style.opacity === '0') {
                return;
            }

            const isClickable = (
                ['a', 'button', 'input', 'textarea', 'select'].includes(tagName) ||
                ['link', 'button', 'checkbox', 'searchbox', 'combobox'].includes(role) ||
                node.hasAttribute('onclick') || node.hasAttribute('jsaction') ||
                node.tabIndex >= 0 || style.cursor === 'pointer'
            );

            const isHeading = ['h1', 'h2', 'h3'].includes(tagName) || role === 'heading';
            const isMetaText = (tagName === 'yt-formatted-string' || tagName === 'span') && node.textContent.length >= 12;

            let label = (node.getAttribute('aria-label') || node.getAttribute('title') || node.getAttribute('placeholder') || node.getAttribute('alt') || "").trim();

            if (!label) {
                // Heuristic: Check for nested SVG with title or aria-label
                const svg = node.querySelector('svg');
                if (svg) {
                    label = (svg.getAttribute('aria-label') || svg.querySelector('title')?.textContent || "").trim();
                }
            }

            if (!label) {
                const areaRatio = (rect.width * rect.height) / vArea;
                const isSmall = areaRatio <= 0.15 || (rect.height <= 140 && rect.width <= 900);
                if (isSmall || isHeading || isMetaText) {
                        label = node.textContent.trim().replace(/\s+/g, ' ').substring(0, 120);
                }
            }

            if (isClickable) {
                const isSmall = rect.width < 20 && rect.height < 20;
                if (!label) {
                    label = `[${tagName}${role ? ':' + role : ''}${node.id ? '#' + node.id : ''}]`;
                }
                
                // Prefix small targets to warn the agent they are secondary (menus/icons)
                if (isSmall) {
                    label = `[small] ${label}`;
                }

                interactive.push({
                    tag: tagName, label: label, role: role || (['a', 'link'].includes(tagName) ? 'link' : tagName),
                    bbox: { x: rect.left, y: rect.top, w: rect.width, h: rect.height },
                    area: rect.width * rect.height,
                    center: { x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2) }
                });
            } else if (isHeading || isMetaText) {
                if (label && label.length >= 8) {
                    markers.push({
                        kind: isHeading ? 'heading' : 'text',
                        text: label,
                        bbox: { x: rect.left, y: rect.top, w: rect.width, h: rect.height },
                        area: rect.width * rect.height
                    });
                }
            }

            for (let child of node.children) walk(child);
        }
    };

    walk(document.body || document.documentElement);

    const dedup = (list) => {
        const res = [];
        const sorted = list.sort((a, b) => a.area - b.area);
        for (const cand of sorted) {
            if (!res.some(s => {
                const overlapX = Math.max(0, Math.min(cand.bbox.x + cand.bbox.w, s.bbox.x + s.bbox.w) - Math.max(cand.bbox.x, s.bbox.x));
                const overlapY = Math.max(0, Math.min(cand.bbox.y + cand.bbox.h, s.bbox.y + s.bbox.h) - Math.max(cand.bbox.y, s.bbox.y));
                const overlapArea = overlapX * overlapY;
                return (overlapArea / cand.area > 0.85) || (overlapArea / s.area > 0.85);
            })) res.push(cand);
        }
        return res;
    };

    const finalNodes = dedup(interactive).sort((a, b) => (Math.round(a.bbox.y / 20) - Math.round(b.bbox.y / 20)) || (a.bbox.x - b.bbox.x));
    const finalMarkers = dedup(markers).slice(0, 15);

    const active = document.activeElement;
    const activeTag = active && active.tagName ? String(active.tagName).toLowerCase() : "";
    const activeRole = active && active.getAttribute ? String(active.getAttribute("role") || "") : "";
    const activeType = active && active.getAttribute ? String(active.getAttribute("type") || "") : "";
    const activeName = active && active.getAttribute ? String(active.getAttribute("name") || "") : "";
    const activeId = active && active.id ? String(active.id) : "";
    const activeRect = active && active.getBoundingClientRect ? active.getBoundingClientRect() : null;
    const isEditable = !!(active && (
        active.matches?.('input, textarea, [contenteditable="true"], [contenteditable]') ||
        active.isContentEditable
    ));

    return {
        nodes: finalNodes.map((c, i) => ({ id: `node_${i + 1}`, tag: c.tag, text: c.label, role: c.role, inViewport: true, bbox: c.bbox, hit_point: c.center })),
        markers: finalMarkers.map((m, i) => ({ id: `marker_${i + 1}`, kind: m.kind, text: m.text, bbox: m.bbox })),
        total_count: finalNodes.length,
        viewport_count: finalNodes.length,
        focus: {
            active_tag: activeTag,
            active_role: activeRole,
            active_type: activeType,
            active_name: activeName,
            active_id: activeId,
            is_editable: isEditable,
            time_origin: Number((performance && performance.timeOrigin) || 0),
            ready_state: String(document.readyState || ""),
            bbox: activeRect ? {
                x: Number(activeRect.left || 0),
                y: Number(activeRect.top || 0),
                w: Number(activeRect.width || 0),
                h: Number(activeRect.height || 0)
            } : null
        }
    };
})();
