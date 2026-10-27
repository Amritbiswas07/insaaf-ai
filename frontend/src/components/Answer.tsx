import { Children, cloneElement, isValidElement, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router-dom";
import remarkGfm from "remark-gfm";

const CITE = /\[doc:(\d+)\]/g;
const SECTION_LABELS = ["Short answer", "Analysis", "Relevant provisions", "Key cases", "Conclusion"];
const DISCLAIMER = /^[_*\s]*(this is (legal )?research assistance,? not legal advice\.?)[_*\s]*$/im;

export function citationOrder(text: string): string[] {
  return [...new Set([...text.matchAll(CITE)].map((m) => m[1]))];
}

/**
 * Tidy model output before rendering: section labels become headings (small
 * models often emit "Short answer" as plain text), and the disclaimer is
 * pulled out so it can be styled separately.
 */
export function normalizeAnswer(text: string): { body: string; disclaimer: string | null } {
  let body = text.replace(/\r\n/g, "\n");
  for (const label of SECTION_LABELS) {
    // "**Short answer**" / "## Analysis" / "1. Relevant provisions:" alone on a line
    const own = new RegExp(`^[ \\t]*(?:#{1,6}[ \\t]*)?(?:\\d+\\.[ \\t]*)?\\**${label}\\**[ \\t]*:?[ \\t]*\\**[ \\t]*$`, "im");
    // "**Short answer:** text…" or "Short answer: text…" on one line
    const inline = new RegExp(`^[ \\t]*(?:\\d+\\.[ \\t]*)?(?:\\*\\*${label}:?\\*\\*:?|${label}:)[ \\t]*(\\S.*)$`, "im");
    body = body.replace(own, `\n### ${label}\n`).replace(inline, `\n### ${label}\n\n$1`);
  }
  let disclaimer: string | null = null;
  const m = body.match(DISCLAIMER);
  if (m) {
    disclaimer = m[1].charAt(0).toUpperCase() + m[1].slice(1);
    body = body.replace(DISCLAIMER, "");
  }
  return { body: body.trim(), disclaimer };
}

function withCitations(node: ReactNode, numbering: Map<string, number>, unverified: Set<string>): ReactNode {
  return Children.map(node, (child) => {
    if (typeof child === "string") {
      const parts: ReactNode[] = [];
      let last = 0;
      for (const m of child.matchAll(CITE)) {
        const id = m[1];
        if (m.index! > last) parts.push(child.slice(last, m.index));
        if (!numbering.has(id)) numbering.set(id, numbering.size + 1);
        const bad = unverified.has(id);
        parts.push(
          <Link
            key={`${id}-${m.index}`}
            to={`/cases/${id}`}
            className={`cite ${bad ? "cite--bad" : ""}`}
            title={bad ? "Not among the retrieved sources — verify independently" : "Open this judgment"}
          >
            {numbering.get(id)}
          </Link>,
        );
        last = m.index! + m[0].length;
      }
      if (last === 0) return child;
      if (last < child.length) parts.push(child.slice(last));
      return parts;
    }
    if (isValidElement<{ children?: ReactNode }>(child) && child.props.children) {
      return cloneElement(child, undefined, withCitations(child.props.children, numbering, unverified));
    }
    return child;
  });
}

export default function Answer({
  text,
  unverified = [],
  streaming,
}: {
  text: string;
  unverified?: string[];
  streaming?: boolean;
}) {
  const { body, disclaimer } = normalizeAnswer(text);
  const numbering = new Map<string, number>(citationOrder(text).map((id, i) => [id, i + 1]));
  const bad = new Set(unverified);
  const wrap = (children: ReactNode) => withCitations(children, numbering, bad);

  return (
    <div className={`md ${streaming ? "caret" : ""}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p>{wrap(children)}</p>,
          li: ({ children }) => <li>{wrap(children)}</li>,
          td: ({ children }) => <td>{wrap(children)}</td>,
          strong: ({ children }) => <strong>{wrap(children)}</strong>,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {body}
      </ReactMarkdown>
      {disclaimer && !streaming && <p className="disclaimer">{disclaimer}</p>}
    </div>
  );
}
