const WEGCompiler = require('./weg_compiler.js');

/**
 * WEG-P Compiler (Procedural Edition)
 * Extends the base compiler with shorthand and procedural primitives.
 */
class WEGPCompiler extends WEGCompiler {
    constructor() {
        super();
        this.shorthandMap = {
            '!': '@Meta:',
            '^': '@World:',
            '$': '@Data',
            '>': '@Node',
            '*': '@ForEach',
            '?': '@If',
            '/': '}',
            '.': '@JS',
            '&': '@Distribute',
            '~': '@Animate',
            '+': '@Transform'
        };
    }

    _preprocessShorthand(lines) {
        return lines.map(line => {
            const trimmed = line.trim();
            if (!trimmed) return line;
            const prefix = trimmed[0];
            if (this.shorthandMap[prefix]) {
                const indent = line.substring(0, line.indexOf(prefix));
                let command = this.shorthandMap[prefix];
                let content = trimmed.substring(1).trim();
                
                // Specific handling for nodes: add colon if missing
                if (prefix === '>') {
                    if (!content.includes(':')) {
                        const parts = content.split(/\s+/);
                        if (parts.length >= 2) {
                            // "name" kind -> "name" kind:
                            const name = parts[0];
                            const kind = parts[1];
                            const rest = parts.slice(2).join(' ');
                            content = `${name} ${kind}: ${rest}`;
                        }
                    }
                }

                return `${indent}${command} ${content}`;
            }
            return line;
        });
    }

    compile(source) {
        const expandedSource = this._preprocessShorthand(source.split('\n')).join('\n');
        return super.compile(expandedSource);
    }

    // Override _parseLines to add WDS-P specific block handling
    _parseLines(lines) {
        let i = 0;
        this.wdsPBlocks = []; // Tracks if the current block is a WDS-P loop
        
        while (i < lines.length) {
            let line = lines[i].trim();
            if (!line || line.startsWith('#') || line.startsWith('//')) { i++; continue; }

            // Block Exit Override
            if (line === '}' || line === '/') {
                const currentPBlock = this.wdsPBlocks[this.wdsPBlocks.length - 1];
                if (currentPBlock === 'dist') {
                    this._add('currentIdx++;');
                    this.indentLevel--;
                    this._add('}');
                    this.indentLevel--;
                    this._add('}');
                    this.codeBlockStack.pop(); 
                    this.wdsPBlocks.pop();
                    i++; continue;
                } else if (currentPBlock === 'animate') {
                    this.wdsPBlocks.pop();
                    // Let super handle the closing '});' for the 'arrow' block
                    super._parseLines(['}']);
                    i++; continue;
                }
            }

            if (line.startsWith('@Distribute')) {
                const match = line.match(/@Distribute\s+(\w+)\s+(.*)\{/);
                if (match) {
                    const [_, type, paramStr] = match;
                    const p = this._parseParams(paramStr);
                    const count = p.n || p.count || 1000;
                    
                    this._add(`// Procedural Distribution: ${type}`);
                    this._add(`{`);
                    this.indentLevel++;
                    this._add(`const dStart = currentIdx;`);
                    this._add(`const dCount = ${count};`);
                    this._add(`for (let j = 0; j < dCount; j++) {`);
                    this.indentLevel++;
                    this._add(`const i3 = currentIdx * 3;`);
                    
                    if (type === 'spiral') {
                        const rings = p.rings || 10;
                        const radius = p.r || 10;
                        this._add(`const r = ${radius} * (j / dCount) * ${rings};`);
                        this._add(`const theta = j * 0.1;`);
                        this._add(`engine.basePositions[i3] = r * Math.cos(theta);`);
                        this._add(`engine.basePositions[i3+1] = 0;`);
                        this._add(`engine.basePositions[i3+2] = r * Math.sin(theta);`);
                    }

                    this.codeBlockStack.push('none'); 
                    this.wdsPBlocks.push('dist');
                }
            } else if (line.startsWith('@Animate')) {
                const match = line.match(/@Animate\s+(\w+)\s*\{/);
                if (match) {
                    const [_, timeVar] = match;
                    this._add(`engine.visualState.updaters.push((${timeVar}) => {`);
                    this.codeBlockStack.push('arrow');
                    this.indentLevel++;
                    this.wdsPBlocks.push('animate');
                }
            } else {
                // If it's a raw JS line inside a procedural block, just add it
                const currentPBlock = this.wdsPBlocks[this.wdsPBlocks.length - 1];
                if (currentPBlock === 'animate') {
                    this._add(line);
                } else {
                    super._parseLines([line]);
                }
            }
            i++;
        }
    }
}

if (typeof module !== 'undefined') module.exports = WEGPCompiler;
