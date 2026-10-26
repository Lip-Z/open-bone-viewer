import './style.css';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { HelpProvider } from './HelpContext';

createRoot(document.getElementById('root')!).render(<HelpProvider><App /></HelpProvider>);
