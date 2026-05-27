/**
 * Wegena WEG Decompiler (Kernel Component) - High Fidelity Edition
 * Converts procedural .js scenes to semantic .weg scripts with block tracking.
 * Supports full logic preservation via {{ }} blocks.
 */
class WEGDecompiler {
    constructor() {
        this.reset();
    }

    reset() {
        this.weg = "";
        this.proceduralBuffer = [];
        this.indent = 0;
        this.jsBraceStack = 0; // Tracks nested braces within procedural logic
        this.meta = {};
    }

    decompile(jsSource) {
        this.reset();
        
        // 1. Extract Meta if exists (find the last one, which is the footer meta)
        const lastMetaIdx = jsSource.lastIndexOf('scene.meta');
        if (lastMetaIdx !== -1) {
            const metaStr = jsSource.substring(lastMetaIdx);
            const metaMatch = metaStr.match(/scene\.meta\s*=\s*({[\s\S]*?});/);
            if (metaMatch) {
                try {
                    this.meta = eval('(' + metaMatch[1] + ')');
                } catch (e) { console.warn("Failed to parse meta", e); }
            }
        }

        // 2. Strip boilerplate (Function wrapper and exports)
        let body = jsSource;
        body = body.replace(/scene\.meta\s*=\s*\{[\s\S]*?\};?/g, '');
        body = body.replace(/module\.exports\s*=\s*scene;?/g, '');
        body = body.replace(/if\s*\(typeof\s+module\s*!==\s*'undefined'\)\s*module\.exports\s*=\s*scene;?/g, '');
        
        const wrapperPatterns = [
            /(?:const|function)\s+\w+\s*=\s*(?:async\s*)?function\s*\(engine\)\s*\{([\s\S]*)\}/,
            /function\s+\w+\s*\(engine\)\s*\{([\s\S]*)\}/,
            /module\.exports\s*=\s*(?:async\s*)?function\s*\(engine\)\s*\{([\s\S]*)\}/
        ];

        for (const pattern of wrapperPatterns) {
            const match = body.match(pattern);
            if (match) {
                body = match[1].trim();
                break;
            }
        }

        // 3. Pre-process: Collapse multi-line engine calls for easier regex matching
        body = body.replace(/engine\.\w+\s*\([\s\S]*?\)\s*;/g, (match) => {
            return match.replace(/\s+/g, ' ');
        });

        const lines = body.split('\n').map(l => l.trim()).filter(l => l);

        // 4. Header Generation
        const label = this.meta.label || "Decompiled Scene";
        const version = this.meta.scriptVersion || "5.0.0";
        this.weg += `@Meta: label="${label}" version="${version}"\n\n`;

        // 5. Line Processor
        lines.forEach(line => {
            if (line.includes('module.exports =') || line.includes('scene.meta =')) return;

            // A. World/Background Settings
            if (this.jsBraceStack === 0) {
                if (line.includes('engine.setFOV(')) {
                    this.flushProcedural();
                    const fov = line.match(/setFOV\(([\d.]+)\)/)?.[1];
                    if (fov) this.weg += `@World: fov=${fov}\n`;
                    return;
                }
                if (line.includes('targetZoom =')) {
                    this.flushProcedural();
                    const zoom = line.match(/targetZoom\s*=\s*([\d.]+)/)?.[1];
                    if (zoom) this.weg += `@World: zoom=${zoom}\n`;
                    return;
                }

                // B. Node Creation
                const nodeMatch = line.match(/engine\.(createVolume|createTerrain)\(([\s\S]*)\);/);
                if (nodeMatch) {
                    this.flushProcedural();
                    const method = nodeMatch[1];
                    const objStr = nodeMatch[2];
                    
                    const getValue = (propName) => {
                        const regex = new RegExp(`${propName}:\\s*(\\[[^\\]]+\\]|\\{[^\\}]+\\}|[^,\\}]+)`);
                        const m = objStr.match(regex);
                        return m ? m[1].trim() : null;
                    };

                    let name = getValue("name") || "node";
                    if (name.startsWith('"') && name.endsWith('"')) name = name.substring(1, name.length - 1);
                    if (name.startsWith("'") && name.endsWith("'")) name = name.substring(1, name.length - 1);
                    
                    const shape = getValue("shape") || "box";
                    let kind = method === "createTerrain" ? "terrain" : shape;
                    if (kind.startsWith('"') && kind.endsWith('"')) kind = kind.substring(1, kind.length - 1);
                    if (kind.startsWith("'") && kind.endsWith("'")) kind = kind.substring(1, kind.length - 1);

                    this.weg += `${'  '.repeat(this.indent)}@Node "${name}" volume: ${kind} `;
                    
                    const centerStr = getValue("center");
                    if (centerStr) {
                        const cx = centerStr.match(/x:\s*(\([^)]+\)|[^,}]+)/)?.[1]?.trim() || "0";
                        const cy = centerStr.match(/y:\s*(\([^)]+\)|[^,}]+)/)?.[1]?.trim() || "0";
                        const cz = centerStr.match(/z:\s*(\([^)]+\)|[^,}]+)/)?.[1]?.trim() || "0";
                        this.weg += `pos: [${cx}, ${cy}, ${cz}] `;
                    }
                    
                    const sizeStr = getValue("size");
                    if (sizeStr) {
                        if (sizeStr.startsWith("[")) {
                            this.weg += `size: ${sizeStr} `;
                        } else {
                            const sx = sizeStr.match(/x:\s*(\([^)]+\)|[^,}]+)/)?.[1]?.trim() || "1";
                            const sy = sizeStr.match(/y:\s*(\([^)]+\)|[^,}]+)/)?.[1]?.trim();
                            const sz = sizeStr.match(/z:\s*(\([^)]+\)|[^,}]+)/)?.[1]?.trim() || "1";
                            if (sy) {
                                this.weg += `size: [${sx}, ${sy}, ${sz}] `;
                            } else {
                                this.weg += `size: [${sx}, ${sz}] `;
                            }
                        }
                    }
                    
                    const color = getValue("color");
                    if (color) {
                        this.weg += `color: ${color} `;
                    }
                    
                    const material = getValue("material");
                    if (material) {
                        this.weg += `material: ${material} `;
                    }
                    
                    // Support budget
                    const budget = getValue("budget");
                    if (budget) {
                        this.weg += `budget: ${budget} `;
                    }
                    
                    // Support light
                    const light = getValue("light");
                    if (light) {
                        this.weg += `light: ${light} `;
                    }

                    this.weg += `\n`;
                    return;
                }

                // C. Control Flow (Semi-declarative support)
                if (line.includes('.forEach(') && (line.includes('=> {') || line.includes('function'))) {
                    this.flushProcedural();
                    const collection = line.split('.')[0] || 'data';
                    const iterator = line.match(/\(([^, ]+)\s*(?:=>|function)/)?.[1] || 'item';
                    this.weg += `${'  '.repeat(this.indent)}@ForEach ${iterator} in ${collection} {\n`;
                    this.indent++;
                    return;
                }

                if (line.startsWith('if (') && line.endsWith('{')) {
                    this.flushProcedural();
                    const cond = line.match(/if\s*\((.*)\)\s*\{/)?.[1];
                    this.weg += `${'  '.repeat(this.indent)}@If ${cond} {\n`;
                    this.indent++;
                    return;
                }

                if (line.includes('else {')) {
                    this.flushProcedural();
                    if (this.indent > 0) {
                        this.weg += `${'  '.repeat(this.indent-1)}@Else {\n`;
                    } else {
                        this.weg += `@Else {\n`;
                    }
                    return;
                }

                if (line === '}' || line === '});' || line === '};' || line === '})') {
                    this.flushProcedural();
                    if (this.indent > 0) {
                        this.indent--;
                        this.weg += `${'  '.repeat(this.indent)}}\n`;
                    }
                    return;
                }
            }

            // D. Procedural Fallback & Brace Tracking
            if (line.includes('{')) this.jsBraceStack += (line.match(/{/g) || []).length;
            if (line.includes('}')) this.jsBraceStack -= (line.match(/}/g) || []).length;
            
            this.proceduralBuffer.push(line);
        });

        this.flushProcedural();
        return this.weg.trim() + "\n";
    }

    flushProcedural() {
        if (this.proceduralBuffer.length > 0) {
            const indentStr = '  '.repeat(this.indent);
            this.weg += `\n${indentStr}{{\n`;
            this.proceduralBuffer.forEach(line => {
                this.weg += `${indentStr}    ${line}\n`;
            });
            this.weg += `${indentStr}}}\n\n`;
            this.proceduralBuffer = [];
        }
    }
}

if (typeof module !== 'undefined') module.exports = WEGDecompiler;
else window.WEGDecompiler = WEGDecompiler;
