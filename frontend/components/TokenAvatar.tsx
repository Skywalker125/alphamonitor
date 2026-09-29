"use client";

import { useState } from "react";

const PALETTE = ["#1fd1a0", "#5b8cff", "#f5a524", "#ef4f6b", "#b06cff", "#2ec5e6"];

export default function TokenAvatar({
  src,
  symbol,
  size = 40,
}: {
  src?: string | null;
  symbol?: string | null;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  const label = (symbol ?? "?").replace(/^\$/, "").slice(0, 2).toUpperCase();
  const color = PALETTE[(label.charCodeAt(0) || 0) % PALETTE.length];

  if (src && !failed) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        className="avatar"
        src={src}
        alt={symbol ?? ""}
        width={size}
        height={size}
        loading="lazy"
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <div className="avatar avatar-fallback" style={{ width: size, height: size, color, borderColor: color }}>
      {label}
    </div>
  );
}
