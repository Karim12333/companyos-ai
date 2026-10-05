import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Raw HTML is never rendered: agent output is untrusted
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-doc">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
        {children}
      </ReactMarkdown>
    </div>
  );
}
