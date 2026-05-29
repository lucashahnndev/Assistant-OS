/**
 * WEGCompiler - Wegena Code (.weg) Compiler
 * JavaScript Port of the Python WEGCompiler (server/weg_compiler.py)
 */
class WEGCompiler {
    constructor() {
        this.reset();
    }

    reset() {
        this.generatedCode = [];
        this.indentLevel = 1;
        this.variables = {};
        this.meta = {};
        this.isAsync = false;
        this.codeBlockStack = []; // 'loop', 'if', 'none'
        this.currentNode = null; // For multi-line property support
        this.loopVariables = []; // Unique loop variable scoping
        this.inTable = false;
        this.tableHeaders = [];
        this.inJsBlock = false;
        this.jsBlockContent = [];
    }

    _add(line) {
        const indentStr = '  '.repeat(Math.max(0, this.indentLevel));
        this.generatedCode.push(indentStr + line);
    }

    _splitCsv(line) {
        const values = [];
        let current = "";
        let depthB = 0;
        let depthC = 0;
        let depthP = 0; // Parentheses
        let inQuote = false;
        for (let j = 0; j < line.length; j++) {
            const char = line[j];
            if (char === '"') inQuote = !inQuote;
            if (!inQuote) {
                if (char === '[') depthB++;
                else if (char === ']') depthB--;
                else if (char === '{') depthC++;
                else if (char === '}') depthC--;
                else if (char === '(') depthP++;
                else if (char === ')') depthP--;
                else if (char === ',' && depthB === 0 && depthC === 0 && depthP === 0) {
                    values.push(current.trim());
                    current = "";
                    continue;
                }
            }
            current += char;
        }
        values.push(current.trim());
        return values;
    }

    _isJsExpression(val) {
        if (typeof val !== 'string') return false;
        const trimmed = val.trim();
        if (trimmed.startsWith('{') || trimmed.startsWith('[') || trimmed.startsWith('(') || trimmed.startsWith('`')) return true;
        
        // Common mathematical operators
        const hasOperators = /[\+\-\*\/%]/.test(trimmed);
        // Math functions or constants
        const hasMath = /(Math\.\w+|sin|cos|tan|abs|sqrt|pow|PI)/.test(trimmed);
        // Standard loop variables or frame-time
        const hasIterationVars = /\b(i|j|k|l|t|currentIdx)\b/.test(trimmed);
        // Local defined variables
        const isKnownVar = this.variables && this.variables[trimmed];
        
        return !!(hasOperators || hasMath || hasIterationVars || isKnownVar);
    }

    _propsToJs(props) {
        if (!props || typeof props !== 'object') return JSON.stringify(props);
        const entries = Object.entries(props);
        if (entries.length === 0) return "{}";
        const parts = entries.map(([k, v]) => {
            let val = v;
            if (typeof v === 'string') {
                val = this._preprocessShorthands(v);
                
                // If it's already a JS object, array, or expression (starts with {, [ or (), don't quote.
                const trimmed = val.trim();
                const isExpression = this._isJsExpression(trimmed);
                
                if (isExpression) {
                    // Stay as is.
                } else if (!val.startsWith('"') && !val.startsWith("'") && isNaN(val)) {
                    // If it is a keyword (true, false, null) or a common identifier like "box", "pulse", "lerp",
                    // we might need to quote it IF it's not a known JS variable/expression.
                    // For safety in Wegena, we quote most unquoted strings that aren't numeric.
                    const keywords = ['true', 'false', 'null', 'undefined'];
                    const isKnownVar = this.variables && this.variables[val];
                    if (!keywords.includes(val) && !isKnownVar) {
                        val = `"${val}"`;
                    }
                } else if (isNaN(val)) {
                    // Already quoted string literal, keep it.
                }
            } else if (typeof v === 'object' && v !== null) {
                // If it's a parsed object from a nested block, convert it back to JS.
                val = this._propsToJs(v);
            }
            return `${k}: ${val}`;
        });
        return `{ ${parts.join(', ')} }`;
    }

    _prepareNodeProps(p) {
        const props = { ...p };
        const isTerrain = !!props.terrain || props.volume === 'terrain' || props.type === 'terrain' || props.kind === 'terrain';
        
        // Unboxing volume: { ... } or terrain: { ... }
        if (props.volume && typeof props.volume === 'object') {
            Object.assign(props, props.volume);
            delete props.volume;
        }
        if (props.terrain && typeof props.terrain === 'object') {
            Object.assign(props, props.terrain);
            delete props.terrain;
        }
        
        // Unbox other shapes (sphere, cube, box, cylinder, torus, cone)
        const shapes = ['sphere', 'cube', 'box', 'cylinder', 'torus', 'cone'];
        shapes.forEach(shape => {
            if (props[shape] !== undefined) {
                props.shape = shape;
                if (typeof props[shape] === 'string') {
                    const extra = this._parseParams(props[shape]);
                    Object.assign(props, extra);
                } else if (typeof props[shape] === 'object' && props[shape] !== null) {
                    Object.assign(props, props[shape]);
                }
                delete props[shape];
            }
        });
        if (props.light && typeof props.light === 'object') {
            Object.assign(props, props.light);
            // Don't delete props.light if it's just a boolean flag, 
            // but here we check if it was an OBJECT.
            // If it was @Node "L" light: { color: "#f00" }, we unbox it.
            // If it was @Node "L" light: true, props.light is boolean, not caught here.
            delete props.light;
            props.light = true; // Ensure it's still flagged as a light
        }
        
        // Parameter mapping
        if (props.pos) {
            props.center = this._normalizeVector(props.pos);
            delete props.pos;
        } else if (props.center) {
            props.center = this._normalizeVector(props.center);
        }

        if (props.size) {
            const keys = (isTerrain) ? ['x', 'z'] : ['x', 'y', 'z'];
            props.size = this._normalizeVector(props.size, keys);
        }

        if (props.direction) {
            props.direction = this._normalizeVector(props.direction);
        }

        // Cleanup kind/type
        delete props.kind;
        delete props.type;

        return props;
    }

    _normalizeBackground(p) {
        // If it was parsed as a collection of flags (e.g. "@Bg: #ff0000" -> {"#ff0000": true})
        const keys = Object.keys(p);
        
        // 1. Check for solid hex shorthand
        if (keys.length === 1 && keys[0].startsWith("#") && p[keys[0]] === true) {
            return { type: "solid", color: keys[0] };
        }

        // 2. Check for positional shorthand (e.g. "@Bg: linear #000 #fff @180")
        if (p.linear || p.radial) {
            const result = { type: p.linear ? "linear" : "radial", stops: [] };
            let angle = 180;
            const colors = [];
            
            for (const k of keys) {
                if (k.startsWith("#")) colors.push(k);
                else if (k.startsWith("@") && !isNaN(k.substring(1))) angle = parseFloat(k.substring(1));
                else if (k === "angle" && !isNaN(p[k])) angle = parseFloat(p[k]);
            }
            
            if (colors.length > 0) {
                if (colors.length === 1) {
                    result.stops = [{ color: colors[0], pos: 0 }, { color: colors[0], pos: 100 }];
                } else {
                    colors.forEach((c, i) => {
                        result.stops.push({ color: c, pos: Math.round((i / (colors.length - 1)) * 100) });
                    });
                }
                result.angle = angle;
                return result;
            }
        }

        // 3. Normalize explicit properties
        const res = { ...p };
        if (res.stops && Array.isArray(res.stops)) {
            res.stops = res.stops.map((s, i, arr) => {
                if (typeof s === 'string') {
                    return { color: s, pos: Math.round((i / (arr.length - 1)) * 100) };
                }
                return s;
            });
        }

        if (res.type === 'hdri' && !res.sky) {
            if (res.stops && res.stops.length >= 2) {
                const first = res.stops[0];
                const last = res.stops[res.stops.length - 1];
                res.sky = { 
                    top: typeof first === 'object' ? first.color : first, 
                    bottom: typeof last === 'object' ? last.color : last 
                };
            } else {
                // Default daylight sky for HDRI if no colors provided
                res.sky = { top: '#4488ff', bottom: '#e3f2fd' };
            }
        }

        return res;
    }

    _normalizeVector(val, keys = ['x', 'y', 'z']) {
        if (Array.isArray(val)) {
            const obj = {};
            keys.forEach((k, i) => {
                let v = val[i];
                if (v === undefined) {
                    v = (k === 'y' || k === 'z') ? 0 : 1;
                }
                if (typeof v === 'string') {
                    v = v.trim();
                    if (v.startsWith('(') && v.endsWith(')')) {
                        const inner = v.substring(1, v.length - 1).trim();
                        if (!isNaN(inner) && inner !== "") {
                            v = parseFloat(inner);
                        }
                    }
                }
                obj[k] = v;
            });
            return obj;
        }
        if (typeof val === 'string' && val.trim().startsWith('[')) {
            const trimmed = val.trim();
            try {
                const arr = JSON.parse(trimmed);
                if (Array.isArray(arr)) return this._normalizeVector(arr, keys);
            } catch(e) {
                // FALLBACK: Manual parsing for things like "[ (10), (20), (30) ]" or "[ x+1, y ]"
                const inner = trimmed.substring(1, trimmed.length - 1).trim();
                const parts = this._splitCsv(inner); // Reuse split logic that follows depth tracking
                return this._normalizeVector(parts, keys);
            }
        }
        // If it is a string like "(100)", strip it too ONLY if it's a number
        if (typeof val === 'string') {
            const v = val.trim();
            if (v.startsWith('(') && v.endsWith(')')) {
                const inner = v.substring(1, v.length - 1).trim();
                if (!isNaN(inner) && inner !== "") return parseFloat(inner);
            }
        }
        return val;
    }

    _autoCloseBrackets(s) {
        if (!s) return s;
        let stack = [];
        const opening = "([{";
        const closing = ")]}";
        const pairs = {")": "(", "]": "[", "}": "{"};
        const reversePairs = {"(": ")", "[": "]", "{": "}"};
        
        for (let char of s) {
            if (opening.includes(char)) {
                stack.push(char);
            } else if (closing.includes(char)) {
                if (stack.length > 0 && stack[stack.length - 1] === pairs[char]) {
                    stack.pop();
                }
            }
        }
        
        let result = s;
        while (stack.length > 0) {
            result += reversePairs[stack.pop()];
        }
        return result;
    }

    _preprocessShorthands(val) {
        if (!val) return val;
        // @Node/ @ shorthands (e.g. @Node.pos -> node.pos)
        return val.replace(/@Node\./g, 'node.').replace(/@\./g, 'node.');
    }

    _parseParams(s) {
        const res = {};
        if (!s) return res;
        let i = 0;
        const n = s.length;

        while (i < n) {
            // Skip spaces and commas
            while (i < n && (s[i] === ' ' || s[i] === ',' || s[i] === '\t' || s[i] === '\n' || s[i] === '\r')) i++;
            if (i >= n) break;

            let start = i;
            // Parse Key
            while (i < n && s[i] !== ':' && s[i] !== ' ' && s[i] !== '=' && s[i] !== '{') i++;
            let key = s.substring(start, i).trim();
            if (!key) break;
            if (key.startsWith('"') && key.endsWith('"')) key = key.substring(1, key.length - 1);

            // Check if we have a value
            if (i < n && (s[i] === ':' || s[i] === '=')) {
                i++;
                while (i < n && s[i] === ' ') i++;
                let vStart = i;
                
                if (i < n && s[i] === '"') {
                    // String literal
                    i++;
                    while (i < n && s[i] !== '"') {
                        if (s[i] === '\\') i++; // simple escape skip
                        i++;
                    }
                    i++;
                    res[key] = s.substring(vStart + 1, i - 1);
                } else if (i < n && s[i] === '[') {
                    // Array
                    let depth = 0;
                    let vStartArr = i;
                    while (i < n) {
                        if (s[i] === '[') depth++;
                        else if (s[i] === ']') depth--;
                        i++;
                        if (depth === 0) break;
                    }
                    let rawArr = s.substring(vStartArr, i);
                    if (depth > 0) {
                        // Unclosed array - try to balance it
                        rawArr = this._autoCloseBrackets(rawArr);
                    }
                    try {
                        res[key] = new Function(`return ${rawArr};`)();
                    } catch(e) {
                        // If it still fails (e.g. "[1, 2,"), try to strip the last comma and balance
                        try {
                            let fixed = rawArr.replace(/,\s*\]+$/, ']');
                            if (!fixed.endsWith(']')) fixed += ']';
                            res[key] = new Function(`return ${fixed};`)();
                        } catch(e2) {
                            res[key] = rawArr;
                        }
                    }
                } else if (i < n && s[i] === '{') {
                    // Object Block
                    let depth = 0;
                    let vStartBlock = i;
                    while (i < n) {
                        if (s[i] === '{') depth++;
                        else if (s[i] === '}') depth--;
                        i++;
                        if (depth === 0) break;
                    }
                    const inner = (vStartBlock + 1 < i - 1) ? s.substring(vStartBlock + 1, i - 1).trim() : (depth > 0 ? s.substring(vStartBlock + 1).trim() : "");
                    if (depth > 0) {
                        // Unclosed block - try to parse what we have, but ensure we don't recursive-loop if s is empty
                        res[key] = this._parseParams(inner);
                    } else {
                        res[key] = this._parseParams(inner);
                    }
                } else {
                    let pDepth = 0; // ( )
                    let bDepth = 0; // [ ]
                    let cDepth = 0; // { }
                    while (i < n) {
                        const char = s[i];
                        if (char === '(') pDepth++;
                        else if (char === ')') pDepth--;
                        else if (char === '[') bDepth++;
                        else if (char === ']') bDepth--;
                        else if (char === '{') cDepth++;
                        else if (char === '}') cDepth--;
                        
                        // Terminate only if all depths are 0 and we hit a separator
                        if (pDepth === 0 && bDepth === 0 && cDepth === 0 && (char === ' ' || char === ',' || char === '\n' || char === '\r' || char === '\t')) {
                            break;
                        }
                        i++;
                    }
                    let val = s.substring(vStart, i).trim();
                    
                    if (val === 'true') res[key] = true;
                    else if (val === 'false') res[key] = false;
                    else if (val === 'null') res[key] = null;
                    else if (!isNaN(val) && val !== "") res[key] = parseFloat(val);
                    else res[key] = this._autoCloseBrackets(val);
                }
            } else {
                // Key-only (flag)
                res[key] = true;
            }

            // Lookahead: check if next thing is a '{' block. 
            // If so, and current value is an identifier or we just parsed a key, it might be a block for it.
            let lookaheadI = i;
            while (lookaheadI < n && (s[lookaheadI] === ' ' || s[lookaheadI] === '\t')) lookaheadI++;
            if (lookaheadI < n && s[lookaheadI] === '{') {
                i = lookaheadI;
                let blockStart = i;
                let depth = 0;
                while (i < n) {
                    if (s[i] === '{') depth++;
                    else if (s[i] === '}') depth--;
                    i++;
                    if (depth === 0) break;
                }
                const blockContent = s.substring(blockStart + 1, i - 1).trim();
                const blockParams = this._parseParams(blockContent);
                
                // If the previous value was a string identifier, convert to object { type: val, ...block }
                if (typeof res[key] === 'string' && !res[key].startsWith('"')) {
                    const type = res[key];
                    res[key] = { type, ...blockParams };
                } else if (typeof res[key] === 'object' && res[key] !== null) {
                    // Merge into existing object
                    Object.assign(res[key], blockParams);
                } else if (res[key] === true) {
                    // Flag + block
                    res[key] = blockParams;
                }
            }
        }
        return res;
    }

    _emitCurrentNode() {
        if (!this.currentNode) return;
        const { name, props } = this.currentNode;
        const p = this._prepareNodeProps(props);
        
        // If it has a volume/shape/budget/count, it's a volume first.
        const hasVolume = p.volume || p.shape || p.budget !== undefined || p.count !== undefined;
        let kind = p.kind || p.type || (p.terrain ? "terrain" : ((p.light && !hasVolume) ? "light" : "volume"));
        
        if (kind === "mesh") {
            p.mesh = true;
            kind = "volume";
        } else if (p.path) {
            p.shape = "path";
            kind = "volume";
        }
        
        const method = kind === "terrain" ? "createTerrain" : (kind === "light" ? "createLight" : "createVolume");
        
        const hasInterpolation = name.includes("${") || name.includes("{");
        const nameJs = hasInterpolation ? `\`${name.replace(/(^|[^\$])\{(\w+)\}/g, '$1${$2}')}\`` : `"${name.replace(/["']/g, '')}"`;
        
        this._add(`engine.${method}({ name: ${nameJs}, ...${this._propsToJs(p)} });`);
        
        // Companion Light emission if a physical volume also has "light"
        if (kind === "volume" && p.light) {
            const lightProps = {
                color: p.color || "#ffffff",
                intensity: p.intensity !== undefined ? p.intensity : 1.0,
                pos: p.pos || p.center || [0, 0, 0]
            };
            const lightNameJs = hasInterpolation ? `\`\${${nameJs}}_light\`` : `"${name.replace(/["']/g, '')}_light"`;
            this._add(`engine.createLight({ name: ${lightNameJs}, ...${this._propsToJs(lightProps)} });`);
        }
        
        this.currentNode = null;
    }

    compile(source) {
        if (!source) return "";
        this.reset();

        // Sanity Check
        const trimmed = source.trim();
        const hasWegMarker = source.includes("@Meta") || source.includes("@Node") || source.includes("[Nodes:") || source.includes("{{");
        const isJsFunction = trimmed.startsWith("function") || source.includes("module.exports") || source.includes("engine.create");
        
        if (isJsFunction && !hasWegMarker) {
             console.warn("LEGACY_FORMAT_DETECTED: Source appears to be JavaScript. Attempting to run as-is.");
             return source; 
        }

        // Try to handle multiline block comments correctly before splitting
        source = source.replace(/\/\*[\s\S]*?\*\//g, '');
        // Force newlines before @ commands to handle single-line LLM outputs
        source = source.replace(/\s+(@(?:Node|Meta|Quality|World|Background|Bg|Loop|Var|End|Material|Shape|ForEach|If|Lines|Metaballs|FX)|\[Nodes:)/g, '\n$1');
        const lines = source.split('\n');
        this._parseLines(lines);

        // Final assembly
        this._emitCurrentNode();
        let header = "async function scene(engine) {";
        if (!source.includes("let currentIdx") && !source.includes("var currentIdx") && !source.includes("const currentIdx")) {
            header += "\n  let currentIdx = 0;";
        }

        // Auto-close any unclosed blocks
        while (this.codeBlockStack.length > 0) {
            const type = this.codeBlockStack.pop();
            this.indentLevel--;
            if (type !== 'none') {
                this._add("} // auto-closed");
                if (type === 'loop') this.loopVariables.pop();
            }
        }

        const footer = "}\n\nscene.meta = " + JSON.stringify(this.meta, null, 2) + ";\nif (typeof module !== 'undefined') module.exports = scene;";
        
        return header + "\n" + this.generatedCode.join('\n') + "\n" + footer;
    }

    _parseLines(lines) {
        for (let i = 0; i < lines.length; i++) {
            let line = lines[i].trim();
            if (!line) {
                this._emitCurrentNode();
                continue;
            }

            // JS Blocks {{ ... }}
            if (line.startsWith("{{")) {
                this.inJsBlock = true;
                let content = line.substring(2).trim();
                if (content.endsWith("}}")) {
                    this._add(content.substring(0, content.length - 2).trim());
                    this.inJsBlock = false;
                } else if (content) {
                    this.jsBlockContent.push(content);
                }
                continue;
            }

            if (this.inJsBlock) {
                if (line.endsWith("}}")) {
                    this.jsBlockContent.push(line.substring(0, line.length - 2).trim());
                    this.jsBlockContent.forEach(blk => this._add(blk));
                    this.jsBlockContent = [];
                    this.inJsBlock = false;
                } else {
                    this.jsBlockContent.push(line);
                }
                continue;
            }

            if (line.startsWith("###")) continue;

            // Meta
            if (line.startsWith("@Meta ")) {
                this._emitCurrentNode();
                Object.assign(this.meta, this._parseParams(line.substring(6)));
                continue;
            }

            // Variables
            const varMatch = line.match(/@Var\s+(\w+)\s*=\s*(.*)/);
            if (varMatch) {
                this._emitCurrentNode();
                const [_, name, val] = varMatch;
                const cleanVal = this._preprocessShorthands(val);
                this._add(`let ${name} = ${cleanVal};`);
                this.variables[name] = cleanVal;
                continue;
            }

            // Tables
            if (line.startsWith("[") && line.includes("]")) {
                this.inTable = true;
                const headerPart = line.substring(1, line.indexOf("]"));
                if (headerPart.includes(":")) {
                    this.tableHeaders = headerPart.split(":")[1].split(",").map(h => h.trim().toLowerCase());
                }
                continue;
            }

            if (this.inTable && line.includes(",") && !line.startsWith("@")) {
                const values = this._splitCsv(line);
                const p = {};
                this.tableHeaders.forEach((h, idx) => {
                    const rawVal = values[idx] !== undefined ? values[idx] : "";
                    if (rawVal === "true") p[h] = true;
                    else if (rawVal === "false") p[h] = false;
                    else if (!isNaN(rawVal) && rawVal.trim() !== "") p[h] = parseFloat(rawVal);
                    else if (rawVal.startsWith("{")) {
                        try {
                            p[h] = this._parseParams(rawVal.slice(1, -1));
                        } catch(e) { p[h] = rawVal; }
                    } else {
                        p[h] = rawVal;
                    }
                });

                const hasVolume = p.volume || p.shape || p.budget !== undefined || p.count !== undefined;
                let kind = p.kind || p.type || (p.terrain ? "terrain" : ((p.light && !hasVolume) ? "light" : "volume"));
                
                if (kind === "mesh") {
                    p.mesh = true;
                    kind = "volume";
                } else if (p.path) {
                    p.shape = "path";
                    kind = "volume";
                }
                
                const method = kind === "terrain" ? "createTerrain" : (kind === "light" ? "createLight" : "createVolume");
                
                const props = this._prepareNodeProps(p);
                const name = props.name || `row_${i}`;
                delete props.name;

                this._add(`engine.${method}({ name: "${name}", ...${this._propsToJs(props)} });`);
                continue;
            }

            // Command context switch
            if (line.startsWith("@")) {
                this._emitCurrentNode();
                this.inTable = false;
            }

            // Commands
            if (line.startsWith("@Background") || line.startsWith("@Bg")) {
                const raw = line.substring(line.indexOf(" ")).trim();
                const p = this._parseParams(raw);
                const normalized = this._normalizeBackground(p);
                this._add(`engine.setBackground(${JSON.stringify(normalized)});`);
                continue;
            }

            if (line.startsWith("@Metaballs")) {
                const p = this._parseParams(line.substring(10));
                const enabled = p.enabled !== undefined ? p.enabled : true;
                const blur = p.blur !== undefined ? p.blur : 4.0;
                const threshold = p.threshold !== undefined ? p.threshold : 0.28;
                this._add(`engine.setMetaballs(${enabled}, ${blur}, ${threshold});`);
                continue;
            }

            if (line.startsWith("@Lines")) {
                const p = this._parseParams(line.substring(6));
                const enabled = p.enabled !== undefined ? p.enabled : true;
                const maxDist = p.maxDist !== undefined ? p.maxDist : 12.0;
                this._add(`engine.setLineConnections(${enabled}, ${maxDist});`);
                continue;
            }

            if (line.startsWith("@Quality")) {
                const p = this._parseParams(line.substring(8));
                const mode = p.mode || "balanced";
                this._add(`if (engine.setQualityMode) engine.setQualityMode("${mode}");`);
                continue;
            }

            if (line.startsWith("@Shape")) {
                const shapeMatch = line.match(/@Shape\s+(?:"([^"]+)"|([^\s:]+))(?:\s+([\s\S]*))?/);
                if (shapeMatch) {
                    const [_, quotedName, varName, paramStr] = shapeMatch;
                    const name = quotedName || varName;
                    const p = this._parseParams(paramStr || "");
                    if (name) p.name = name;
                    this._add(`engine.createShape(${this._propsToJs(p)});`);
                }
                continue;
            }

            if (line.startsWith("@Material")) {
                const p = this._parseParams(line.substring(10));
                this._add(`engine.setMaterialProperties("${p.type}", ${p.roughness}, ${p.metalness}, ${p.emissive});`);
                continue;
            }

            if (line.startsWith("@World")) {
                const p = this._parseParams(line.substring(7));
                if (p.zoom) this._add(`engine.visualState.navigation.targetZoom = ${p.zoom};`);
                if (p.fov) this._add(`engine.setFOV(${p.fov});`);
                if (p.density) {
                    let d = p.density;
                    if (typeof d === 'string' && d.endsWith('k')) d = parseFloat(d.slice(0, -1)) * 1000;
                    this._add(`engine.setDensity(${d}, false);`);
                }
                if (p.size) this._add(`engine.setParticleSize(${p.size});`);
                continue;
            }

            // Control flow
            if (line.startsWith("@ForEach")) {
                this._emitCurrentNode();
                const match = line.match(/@ForEach\s+(\w+)\s+in\s+(\w+)/);
                if (match) {
                    const [_, item, list] = match;
                    this._add(`${list}.forEach(${item} => {`);
                    this.codeBlockStack.push('foreach');
                    this.indentLevel++;
                }
                continue;
            }

            if (line.startsWith("@Else")) {
                this._emitCurrentNode();
                this.indentLevel--;
                this._add("} else {");
                this.indentLevel++;
                continue;
            }

            if (line.startsWith("@Loop")) {
                this._emitCurrentNode();
                let params = line.substring(6).trim();
                if (params.endsWith("{")) params = params.slice(0, -1).trim();
                const p = this._parseParams(params);
                const count = p.count || 10;
                let v = p.var;
                if (!v) {
                    const candidates = ['i', 'j', 'k', 'l', 'm', 'n'];
                    v = candidates.find(c => !this.loopVariables.includes(c)) || `i_${this.loopVariables.length}`;
                }
                this.loopVariables.push(v);
                this._add(`for (let ${v} = 0; ${v} < ${count}; ${v}++) {`);
                this.codeBlockStack.push('loop');
                this.indentLevel++;
                continue;
            }

            if (line.startsWith("@If")) {
                this._emitCurrentNode();
                let cond = line.substring(4).trim();
                if (cond.endsWith("{")) cond = cond.slice(0, -1).trim();
                this._add(`if (${cond}) {`);
                this.codeBlockStack.push('if');
                this.indentLevel++;
                continue;
            }

            if (line.startsWith("@End")) {
                this._emitCurrentNode();
                if (this.codeBlockStack.length > 0) {
                    this.indentLevel--;
                    this._add("}");
                    const type = this.codeBlockStack.pop();
                    if (type === 'loop') this.loopVariables.pop();
                } else {
                    console.warn(`Unexpected @End at line ${i+1}`);
                }
                continue;
            }

            // Node creation
            if (line.startsWith("@Node")) {
                const nodeMatch = line.match(/@Node\s+(?:"([^"]+)"|([^\s:]+))(?:\s+([\s\S]*))?/);
                if (nodeMatch) {
                    const [_, quotedName, varName, paramStr] = nodeMatch;
                    const name = quotedName || varName;
                    const hasBlock = paramStr?.trim()?.endsWith("{");
                    const cleanParams = hasBlock ? paramStr.trim().slice(0, -1).trim() : (paramStr?.trim() || "");
                    const p = this._parseParams(cleanParams);

                    const hasInterpolation = name.includes("${") || name.includes("{");
                    const nameJs = hasInterpolation ? `\`${name.replace(/\{(\w+)\}/g, '${$1}')}\`` : `"${name.replace(/["']/g, '')}"`;

                    this.currentNode = { name, props: p };
                    
                    if (hasBlock) {
                        this._emitCurrentNode(); 
                        this.currentNode = null; 
                        const kind = p.kind || p.type || (p.terrain ? "terrain" : "volume");
                        const method = kind === "terrain" ? "createTerrain" : "createVolume";
                        const props = this._prepareNodeProps(p);
                        this._add(`engine.${method}({ name: ${nameJs}, ...${this._propsToJs(props)} });`);
                        
                        this.codeBlockStack.push('none');
                        this.indentLevel++;
                    }
                }
                continue;
            }

            if (line.startsWith("@FX")) {
                const p = this._parseParams(line.substring(4));
                let kind = p.kind || p.type || "burst";
                if (typeof kind === 'string') kind = kind.replace(/["']/g, '').toLowerCase();

                let method = "spawnBurst";
                if (kind === "smoke") method = "spawnSmokeColumn";
                else if (kind === "fire") method = "spawnFireJet";
                else if (kind === "exhaust") method = "spawnEngineExhaust";
                else if (kind === "water") method = "spawnWaterFlow";
                else if (kind === "debris") method = "spawnDebris";

                const props = { ...p };
                if (props.pos) props.center = this._normalizeVector(props.pos);
                else if (props.center) props.center = this._normalizeVector(props.center);
                
                delete props.kind;
                delete props.type;
                delete props.pos;

                this._add(`engine.${method}(${this._propsToJs(props)});`);
                continue;
            }

            // Block termination
            if (line === "}") {
                this._emitCurrentNode();
                if (this.codeBlockStack.length > 0) {
                    this.indentLevel--;
                    const type = this.codeBlockStack.pop();
                    if (type !== 'none') {
                        this._add("}");
                        if (type === 'loop') this.loopVariables.pop();
                    }
                } else {
                    // It might be a rogue brace or a literal brace in a comment/JS that wasn't caught
                    // But we don't want to add a matching brace if the stack is empty
                    console.warn(`Unexpected '}' at line ${i+1}`);
                }
                continue;
            }

            // Fallback for multi-line properties
            if (this.currentNode && line.includes(":")) {
                Object.assign(this.currentNode.props, this._parseParams(line));
                continue;
            }
        }
    }
}

// Export for browser and node
if (typeof module !== 'undefined' && module.exports) {
    module.exports = WEGCompiler;
} else {
    window.WEGCompiler = WEGCompiler;
}
