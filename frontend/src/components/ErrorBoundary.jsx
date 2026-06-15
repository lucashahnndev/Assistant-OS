import React from 'react';
import { AlertCircle } from 'lucide-react';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          color: '#f87171',
          fontSize: '12px',
          padding: '12px',
          background: 'rgba(239,68,68,0.08)',
          borderRadius: '6px',
          border: '1px solid rgba(239,68,68,0.18)'
        }}>
          <AlertCircle size={16} />
          <div>
            <strong style={{ display: 'block', marginBottom: '2px' }}>Erro de Renderização</strong>
            <span>O conteúdo deste artefato possui formatação não suportada ou quebra de segurança e não pôde ser exibido.</span>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
