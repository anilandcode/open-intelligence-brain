import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
export function Detail({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
    return () => { if (dialog.open && typeof dialog.close === "function") dialog.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} className="detail-drawer" aria-label={title} onCancel={e=>{e.preventDefault();onClose();}}><header><div><small>DETAIL</small><h2>{title}</h2></div><button type="button" className="ghost-icon" aria-label="Close details" onClick={onClose}><X size={20}/></button></header><div className="detail-body">{children}</div></dialog>;
}
