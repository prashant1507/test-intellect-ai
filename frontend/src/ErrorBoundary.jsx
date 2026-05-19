import { Component } from "react";

export class ErrorBoundary extends Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      const bg = "var(--card-bg, #f4f4f5)";
      const fg = "var(--text, #18181b)";
      const bd = "var(--card-border, #d4d4d8)";
      const err = "var(--err, #b91c1c)";
      return (
        <div
          role="alert"
          style={{
            minHeight: "100vh",
            boxSizing: "border-box",
            padding: "2rem",
            fontFamily: "system-ui, sans-serif",
            background: "var(--bg, #e4e4e7)",
            color: fg,
          }}
        >
          <div
            style={{
              maxWidth: 520,
              margin: "4rem auto 0",
              padding: "1.5rem",
              borderRadius: 12,
              border: `1px solid ${bd}`,
              background: bg,
              boxShadow: "0 8px 30px rgba(0,0,0,0.08)",
            }}
          >
            <h1 style={{ fontSize: "1.15rem", fontWeight: 600, margin: "0 0 0.5rem" }}>Something went wrong</h1>
            <p style={{ margin: "0 0 1rem", lineHeight: 1.5, opacity: 0.9 }}>
              The app hit an unexpected error. You can reload the page to try again. If it keeps happening, check the
              browser console for details.
            </p>
            <pre
              style={{
                fontSize: "0.75rem",
                overflow: "auto",
                padding: "0.75rem",
                borderRadius: 8,
                background: "var(--pre-bg, #fafafa)",
                border: `1px solid ${bd}`,
                color: err,
                margin: "0 0 1rem",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {String(this.state.error?.message || this.state.error || "Error")}
            </pre>
            <button
              type="button"
              style={{
                padding: "0.5rem 1rem",
                borderRadius: 8,
                border: `1px solid ${bd}`,
                background: "var(--secondary-bg, #e4e4e7)",
                color: fg,
                fontWeight: 500,
                cursor: "pointer",
              }}
              onClick={() => window.location.reload()}
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
