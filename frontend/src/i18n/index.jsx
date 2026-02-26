import { createContext, useContext, useEffect, useMemo, useState } from 'react';

import en from './locales/en.json';
import ptBR from './locales/pt-BR.json';
import es from './locales/es.json';
import { DEFAULT_LOCALE, SUPPORTED_LOCALES, FALLBACK_LOCALE } from './config';

const catalogs = {
  en,
  'pt-BR': ptBR,
  es,
};

const normalize = (value) => {
  if (!value) return FALLBACK_LOCALE;
  const v = value.replace('_', '-').toLowerCase();
  if (v.startsWith('pt')) return 'pt-BR';
  if (v.startsWith('es')) return 'es';
  return SUPPORTED_LOCALES.includes('en') ? 'en' : FALLBACK_LOCALE;
};

const I18nContext = createContext({
  locale: 'en',
  t: (key) => key,
  setLocale: () => {},
});

export const I18nProvider = ({ children }) => {
  const [locale, setLocale] = useState(() => normalize(DEFAULT_LOCALE));

  useEffect(() => {
    localStorage.setItem('locale', locale);
  }, [locale]);

  const t = useMemo(() => {
    const catalog = catalogs[locale] || catalogs.en;
    return (key) => catalog[key] || catalogs.en[key] || key;
  }, [locale]);

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

export const useI18n = () => useContext(I18nContext);
