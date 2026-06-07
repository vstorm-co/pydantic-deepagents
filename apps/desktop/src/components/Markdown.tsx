import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

// Safe markdown (react-markdown never uses dangerouslySetInnerHTML). Fenced
// ```mermaid blocks render as diagrams; other code blocks get a copy button.
export function Markdown({ text }: { text: string }): JSX.Element {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={{
          pre: ({ children }) => <>{children}</>,
          a: (props) => <a {...props} target="_blank" rel="noreferrer" />,
          code: ({ className, children }) => {
            const lang = /language-(\w+)/.exec(className ?? "")?.[1];
            if (lang === "mermaid") {
              return <MermaidBlock code={String(children).replace(/\n$/, "")} />;
            }
            if (!lang) return <code className={className}>{children}</code>;
            return <CodeBlock className={className}>{children}</CodeBlock>;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

function CodeBlock({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}): JSX.Element {
  const copy = (e: React.MouseEvent<HTMLButtonElement>): void => {
    const pre = e.currentTarget.parentElement?.querySelector("pre");
    void navigator.clipboard.writeText(pre?.textContent ?? "");
    const btn = e.currentTarget;
    btn.textContent = "Copied";
    setTimeout(() => (btn.textContent = "Copy"), 1200);
  };
  return (
    <div className="code-wrap">
      <button className="copy-code" onClick={copy}>
        Copy
      </button>
      <pre>
        <code className={className}>{children}</code>
      </pre>
    </div>
  );
}

let mermaidReady: Promise<typeof import("mermaid").default> | null = null;
function loadMermaid(): Promise<typeof import("mermaid").default> {
  if (!mermaidReady) {
    mermaidReady = import("mermaid").then((m) => {
      m.default.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
      return m.default;
    });
  }
  return mermaidReady;
}

function MermaidBlock({ code }: { code: string }): JSX.Element {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let active = true;
    void loadMermaid().then(async (mermaid) => {
      try {
        const id = `mmd-${Math.floor(Math.random() * 1e9)}`;
        const { svg } = await mermaid.render(id, code);
        if (active && ref.current) ref.current.innerHTML = svg;
      } catch (err) {
        if (active && ref.current) ref.current.textContent = `Diagram error: ${String(err)}`;
      }
    });
    return () => {
      active = false;
    };
  }, [code]);

  return <div className="mermaid" ref={ref} />;
}
