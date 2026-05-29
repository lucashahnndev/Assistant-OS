import { notify } from '../../utils/notify.jsx';
import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import rehypeRaw from 'rehype-raw';


export const CodeBlock = ({ node, inline, className, children, ...props }) => {
    const [copied, setCopied] = useState(false);
    const codeRef = useRef(null);
    const match = /language-(\w+)/.exec(className || '');
    const language = match ? match[1] : '';

    // Force block rendering if the content has newlines, even if parsed as inline markdown
    const hasNewlines = String(children).includes('\n');
    const isInline = (inline || !className) && !hasNewlines;

    const handleCopy = () => {
        const text = codeRef.current?.innerText || children.toString();
        navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
        notify.success("Code copied!");
    };

    if (isInline) {
        return <code style={{ background: 'rgba(255,255,255,0.1)', padding: '2px 4px', borderRadius: '4px', fontFamily: 'monospace', fontSize: '13px' }} {...props}>{children}</code>;
    }

    return (
        <div style={{
            position: 'relative',
            margin: '16px 0',
            borderRadius: '12px',
            overflow: 'hidden',
            border: '1px solid rgba(255,255,255,0.1)',
            background: 'rgba(0,0,0,0.3)'
        }}>
            {/* Header / Toolbar */}
            <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '8px 16px',
                background: 'rgba(255,255,255,0.05)',
                borderBottom: '1px solid rgba(255,255,255,0.05)'
            }}>
                <span style={{
                    fontSize: '11px',
                    fontWeight: '800',
                    textTransform: 'uppercase',
                    opacity: 0.5,
                    letterSpacing: '0.05em'
                }}>
                    {language || 'code'}
                </span>
                <button
                    onClick={handleCopy}
                    className="btn-ghost"
                    style={{
                        padding: '4px 10px',
                        height: 'auto',
                        minWidth: '60px',
                        background: 'rgba(255,255,255,0.08)',
                        borderRadius: '6px',
                        fontSize: '10px',
                        fontWeight: '800',
                        color: copied ? 'var(--success)' : 'var(--text-main)',
                        transition: 'var(--transition)',
                        border: '1px solid rgba(255,255,255,0.1)'
                    }}
                >
                    {copied ? 'COPIED' : 'COPY'}
                </button>
            </div>
            <pre style={{
                margin: 0,
                padding: '16px',
                overflow: 'auto',
                background: 'transparent'
            }}>
                <code className={className} {...props} ref={codeRef} style={{ fontSize: '13px', lineHeight: '1.6' }}>
                    {children}
                </code>
            </pre>
        </div>
    );
};

export const TypewriterMarkdown = ({ text, isStreaming, isComplete, isUser, animateTyping }) => {
    const [displayedText, setDisplayedText] = useState(() => {
        if (isUser || !animateTyping) return text;
        return "";
    });

    useEffect(() => {
        if (isUser) {
            setDisplayedText(text);
            return;
        }

        if (isStreaming) {
            setDisplayedText(text);
            return;
        }

        if (!animateTyping) {
            setDisplayedText(text);
            return;
        }

        if (displayedText.length >= text.length) {
            if (displayedText !== text) setDisplayedText(text);
            return;
        }

        const charsToAdd = Math.max(1, Math.floor(text.length / 90) + 1);
        const timer = setTimeout(() => {
            setDisplayedText(prev => text.slice(0, prev.length + charsToAdd));
        }, 12);

        return () => clearTimeout(timer);
    }, [displayedText, text, isStreaming, animateTyping, isUser]);

    return (
        <div className="markdown-content" style={{ overflowWrap: 'anywhere', wordBreak: 'break-word' }}>
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                rehypePlugins={[rehypeRaw]}
                components={{
                    code: CodeBlock,
                    p: ({ node, children, ...props }) => <div style={{ marginBottom: '12px' }} {...props}>{children}</div>,
                    ul: ({ node, ...props }) => <ul style={{ paddingLeft: '24px', marginBottom: '16px' }} {...props} />,
                    ol: ({ node, ...props }) => <ol style={{ paddingLeft: '24px', marginBottom: '16px', listStyleType: 'decimal' }} {...props} />,
                    li: ({ node, ...props }) => <li style={{ marginBottom: '8px' }} {...props} />,
                    strong: ({ node, ...props }) => <strong style={{ color: isUser ? '#fff' : 'var(--accent-color)', fontWeight: '800' }} {...props} />,
                    a: ({ node, ...props }) => <a style={{ color: isUser ? '#fff' : 'var(--accent-color)', textDecoration: 'underline', fontWeight: 'bold' }} target="_blank" rel="noreferrer" {...props} />
                }}
            >
                {displayedText}
            </ReactMarkdown>
            {(!isUser && (isStreaming || displayedText.length < text.length)) && (
                <span style={{
                    display: 'inline-block',
                    width: '6px',
                    height: '15px',
                    background: 'var(--accent-color)',
                    marginLeft: '4px',
                    verticalAlign: 'middle',
                    borderRadius: '1px',
                    boxShadow: '0 0 8px var(--accent-color)',
                    animation: 'pulse 0.8s infinite'
                }} />
            )}
        </div>
    );
};
