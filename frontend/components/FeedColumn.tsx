"use client";

import type { ReactNode } from "react";

export type Filter<T> = { id: string; label: string; test: (item: T) => boolean };

export default function FeedColumn<T>({
  icon,
  title,
  subtitle,
  meta,
  filters,
  activeFilter,
  onFilter,
  error,
  loading,
  emptyText,
  children,
  count,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  meta?: ReactNode;
  filters: Filter<T>[];
  activeFilter: string;
  onFilter: (id: string) => void;
  error?: string | null;
  loading?: boolean;
  emptyText: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section className="column">
      <header className="column-head">
        <div className="column-title-row">
          <span className="column-icon">{icon}</span>
          <h2>{title}</h2>
          <span className="column-meta">{meta}</span>
        </div>
        <p className="column-sub">{subtitle}</p>
        <div className="chips">
          {filters.map((f) => (
            <button
              key={f.id}
              className={`chip chip-filter ${activeFilter === f.id ? "active" : ""}`}
              onClick={() => onFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </header>
      <div className="column-body">
        {error && <div className="notice notice-error">{error}</div>}
        {!error && loading && count === 0 && <div className="notice">Loading…</div>}
        {!error && !loading && count === 0 && <div className="notice">{emptyText}</div>}
        {children}
      </div>
    </section>
  );
}
