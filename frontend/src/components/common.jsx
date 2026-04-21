import {
  useState,
  useRef,
  useLayoutEffect,
  useCallback,
  Children,
  cloneElement,
  isValidElement,
} from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function Spinner() {
  return (
    <svg className="spinner" width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeDasharray="31.4 31.4" opacity="0.9" />
    </svg>
  );
}

export function ThemeToggle({ theme, setTheme, layout = "inline", id }) {
  const inner = (
    <div id={id} className="theme-toggle" role="group" aria-label="Color theme">
      <FloatingTooltip text="Light Theme">
        <button
          type="button"
          className={theme === "light" ? "active" : ""}
          onClick={() => setTheme("light")}
          aria-pressed={theme === "light"}
          aria-label="Light Theme"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
          </svg>
        </button>
      </FloatingTooltip>
      <FloatingTooltip text="Dark Theme">
        <button
          type="button"
          className={theme === "dark" ? "active" : ""}
          onClick={() => setTheme("dark")}
          aria-pressed={theme === "dark"}
          aria-label="Dark Theme"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
          </svg>
        </button>
      </FloatingTooltip>
    </div>
  );
  return layout === "auth" ? <div className="auth-page-toolbar">{inner}</div> : inner;
}

export function AuthPageShell({ theme, setTheme, children }) {
  return (
    <div className="auth-page">
      <ThemeToggle theme={theme} setTheme={setTheme} layout="auth" />
      <div className="auth-page-inner">{children}</div>
    </div>
  );
}

export function AuthBrandIcon() {
  return (
    <div className="auth-brand-mark" aria-hidden>
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
        <path d="M9 12l2 2 4-4" />
      </svg>
    </div>
  );
}

export function PasteRequirementsPreview({ text }) {
  const t = (text || "").trim();
  if (!t) return null;
  return (
    <div className="paste-md-preview" role="region" aria-label="Formatted preview of pasted requirements">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: (props) => <a {...props} target="_blank" rel="noopener noreferrer" />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

export function FloatingTooltip({ text, children, wrapClassName = "" }) {
  const wrapRef = useRef(null);
  const tooltipRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [float, setFloat] = useState({
    top: 0,
    left: 0,
    arrowLeft: 0,
    below: false,
    visible: false,
  });

  const reposition = useCallback(() => {
    const wrap = wrapRef.current;
    const tip = tooltipRef.current;
    if (!wrap || !tip) return;
    const ar = wrap.getBoundingClientRect();
    const tr = tip.getBoundingClientRect();
    if (tr.width === 0 && tr.height === 0) return;
    const pad = 8;
    const gap = 8;
    const cx = ar.left + ar.width / 2;
    let left = cx - tr.width / 2;
    left = Math.max(pad, Math.min(left, window.innerWidth - pad - tr.width));
    let top = ar.top - gap - tr.height;
    let below = false;
    if (top < pad) {
      below = true;
      top = ar.bottom + gap;
      const maxTop = window.innerHeight - pad - tr.height;
      if (top > maxTop) top = Math.max(pad, maxTop);
    }
    const arrowLeft = cx - left;
    setFloat({ top, left, arrowLeft, below, visible: true });
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    const run = () => {
      requestAnimationFrame(() => reposition());
    };
    run();
    window.addEventListener("resize", run);
    window.addEventListener("scroll", run, true);
    return () => {
      window.removeEventListener("resize", run);
      window.removeEventListener("scroll", run, true);
    };
  }, [open, text, reposition]);

  const beginOpen = () => {
    setOpen((wasOpen) => {
      if (!wasOpen) {
        setFloat({ top: 0, left: 0, arrowLeft: 0, below: false, visible: false });
      }
      return true;
    });
  };
  const handleMouseEnter = () => {
    if (!String(text || "").trim()) return;
    beginOpen();
  };
  const handleMouseLeave = () => {
    if (!wrapRef.current?.matches(":focus-within")) setOpen(false);
  };

  let child;
  try {
    child = Children.only(children);
  } catch {
    return children;
  }
  if (!isValidElement(child)) return children;

  const merged = cloneElement(child, {
    onFocus: (e) => {
      if (String(text || "").trim()) beginOpen();
      child.props.onFocus?.(e);
    },
    onBlur: (e) => {
      setOpen(false);
      child.props.onBlur?.(e);
    },
  });

  const tooltip =
    typeof document !== "undefined" && open && String(text || "").trim() ? (
      createPortal(
        <span
          ref={tooltipRef}
          className={`field-info-tooltip field-info-tooltip--floating${float.below ? " field-info-tooltip--below" : ""}`}
          style={{
            top: float.top,
            left: float.left,
            visibility: float.visible ? "visible" : "hidden",
            "--field-info-arrow-left": `${float.arrowLeft}px`,
          }}
          aria-hidden="true"
        >
          {text}
        </span>,
        document.body
      )
    ) : null;

  const wrapCls = ["field-info-wrap", wrapClassName].filter(Boolean).join(" ");

  return (
    <span ref={wrapRef} className={wrapCls} onMouseEnter={handleMouseEnter} onMouseLeave={handleMouseLeave}>
      {merged}
      {tooltip}
    </span>
  );
}

export function FieldInfo({ text }) {
  return (
    <FloatingTooltip text={text}>
      <button type="button" className="field-info" aria-label={text}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4M12 8h.01" />
        </svg>
      </button>
    </FloatingTooltip>
  );
}

export function Copy({ text, label = "Copy", onAnnounce, disabled = false, omitTitle = false }) {
  const [ok, setOk] = useState(false);
  const title = omitTitle && !ok ? undefined : ok ? "Copied" : label;
  return (
    <button
      type="button"
      className="copy-icon"
      disabled={disabled || !text}
      title={title}
      aria-label={ok ? "Copied" : label}
      onClick={async () => {
        if (!text) return;
        await navigator.clipboard.writeText(text);
        setOk(true);
        onAnnounce?.("Copied to clipboard");
        setTimeout(() => setOk(false), 1500);
      }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
        {ok ? (
          <polyline points="20 6 9 17 4 12" strokeWidth="2.5" />
        ) : (
          <>
            <rect x="8" y="8" width="14" height="14" rx="2" />
            <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
          </>
        )}
      </svg>
    </button>
  );
}
