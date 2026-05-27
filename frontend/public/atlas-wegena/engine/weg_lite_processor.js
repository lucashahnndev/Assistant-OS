/**
 * WEG-Lite Pre-processor (PoC)
 * Converts shorthand WEG-X syntax to standard WEG.
 */
class WEGLiteProcessor {
    constructor() {
        this.map = {
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

    process(source) {
        return source.split('\n').map(line => {
            const trimmed = line.trim();
            if (!trimmed) return line;
            const prefix = trimmed[0];
            const content = trimmed.substring(1).trim();
            
            if (this.map[prefix]) {
                const indent = line.substring(0, line.indexOf(prefix));
                let command = this.map[prefix];
                
                // Specific handling for nodes and data to ensure spaces/equalities
                if (prefix === '>') {
                    if (!content.includes(':')) {
                        const parts = content.split(/\s+/);
                        if (parts.length >= 2) {
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
        }).join('\n');
    }
}

// Simple test
if (require.main === module) {
    const processor = new WEGLiteProcessor();
    const input = `! label="Solar" version="5.0.0"
^ fov=70 zoom=380
$ planets = []
* p in planets {
  ? p.name === "Sun" {
    > "Sun" volume: p=0,0,0 r=45 c=#ffcc33
  /
/`;
    console.log("--- Input WEG-Lite ---");
    console.log(input);
    console.log("\n--- Output standard WEG ---");
    console.log(processor.process(input));
}

module.exports = WEGLiteProcessor;
