import { useEffect, useState } from 'react';
import type { RefObject } from 'react';
import { Maximize2, Minimize2 } from 'lucide-react';

export function FullscreenButton({ target, label }: { target: RefObject<HTMLElement | null>; label: string }) {
  const [active, setActive] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const update = () => setActive(document.fullscreenElement === target.current);
    document.addEventListener('fullscreenchange', update);
    return () => document.removeEventListener('fullscreenchange', update);
  }, [target]);
  return <><button className="icon-button" aria-label={`${active ? '退出' : ''}${label}全屏`} title={`${active ? '退出' : ''}全屏查看`} onClick={async () => {
    try {
      setError('');
      if (document.fullscreenElement === target.current) await document.exitFullscreen();
      else await target.current?.requestFullscreen();
    } catch { setError('浏览器未允许全屏'); }
  }}>{active ? <Minimize2 size={15} /> : <Maximize2 size={15} />}</button>{error && <span className="fullscreen-error" role="alert">{error}</span>}</>;
}
