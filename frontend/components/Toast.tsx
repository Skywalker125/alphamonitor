"use client";

import { useEffect, useState } from "react";
import { TOAST_EVENT } from "@/lib/copy";

export default function Toast() {
  const [msg, setMsg] = useState<{ text: string; id: number } | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const onToast = (e: Event) => {
      clearTimeout(timer);
      setMsg({ text: (e as CustomEvent<string>).detail, id: Date.now() });
      timer = setTimeout(() => setMsg(null), 1600);
    };
    window.addEventListener(TOAST_EVENT, onToast);
    return () => {
      clearTimeout(timer);
      window.removeEventListener(TOAST_EVENT, onToast);
    };
  }, []);

  return msg ? (
    <div key={msg.id} className="toast" role="status">
      {msg.text}
    </div>
  ) : null;
}
