/**
 * notify — Helper centralizado para toasts do sistema Atlas.
 *
 * Uso:
 *   import { notify } from '../utils/notify.jsx';
 *   notify.success('Sessão renomeada!');
 *   notify.error('Falha ao conectar', { message: 'Verifique a rede.' });
 *   notify.loading('Gerando cena Wegena...');
 *   const id = notify.loading('Processando...');
 *   notify.dismiss(id);
 */
import toast from 'react-hot-toast';
import React from 'react';
import { AtlasToast } from '../components/AtlasToast';

const DURATIONS = {
    success: 3500,
    error: 5000,
    warning: 4500,
    info: 4000,
    loading: Infinity,
};

const show = (type, titleOrOpts, opts = {}) => {
    let title, message;
    if (typeof titleOrOpts === 'string') {
        title = titleOrOpts;
        message = opts.message || null;
    } else if (typeof titleOrOpts === 'object' && titleOrOpts !== null) {
        title = titleOrOpts.title || null;
        message = titleOrOpts.message || null;
    }

    const duration = opts.duration ?? DURATIONS[type];
    const id = opts.id;

    return toast.custom(
        (t) => (
            <AtlasToast
                t={t}
                type={type}
                title={title}
                message={message}
                duration={duration === Infinity ? null : duration}
            />
        ),
        {
            duration,
            id,
            position: opts.position || 'top-right',
        }
    );
};

export const notify = {
    success: (title, opts) => show('success', title, opts),
    error:   (title, opts) => show('error',   title, opts),
    warning: (title, opts) => show('warning', title, opts),
    info:    (title, opts) => show('info',    title, opts),
    loading: (title, opts) => show('loading', title, { duration: Infinity, ...opts }),
    dismiss: (id) => toast.dismiss(id),
};

export default notify;
