import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

// react-markdown never renders raw HTML (no rehype-raw), and defaultUrlTransform drops
// javascript:/data: URLs, so model output cannot inject markup or scripts.
const safeUrl = (url: string) => {
  const cleaned = defaultUrlTransform(url);
  return /^(https?:|mailto:)/i.test(cleaned) ? cleaned : "";
};

export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={safeUrl}
        components={{
          a: ({ href, children: c }) =>
            href ? (
              <a href={href} target="_blank" rel="noopener noreferrer nofollow">
                {c}
              </a>
            ) : (
              <span>{c}</span>
            ),
          img: () => null, // answers never need remote images
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
