import katex from "katex";
import "katex/dist/katex.min.css";
import type { ReactNode } from "react";

const MATH_DELIMITER_RE = /\\\((.+?)\\\)|\\\[((?:.|\n)+?)\\\]|\$\$((?:.|\n)+?)\$\$|\$([^$\n]+?)\$/g;
const BARE_LATEX_COMMAND_RE = /\\[a-zA-Z]+(?:\{[^}]*\})?(?:[_^](?:\{[^}]*\}|[a-zA-Z0-9]+))*/g;
const BARE_EQUATION_HINT_RE = /\\(frac|hbar|Psi|psi|hat|nabla|cdot|mathbf|varepsilon|partial)\b|=/;

export function MathBlock({ latex }: { latex: string }) {
  return (
    <div
      className="overflow-x-auto rounded-md border border-softline bg-paper px-3 py-3 text-sm"
      dangerouslySetInnerHTML={{ __html: renderLatex(latex, true) }}
    />
  );
}

export function InlineMathText({ text }: { text: string }) {
  return <>{parseInlineMath(text)}</>;
}

function parseInlineMath(text: string): ReactNode[] {
  if (!text) {
    return [text];
  }

  if (!hasExplicitDelimiters(text) && looksLikeStandaloneLatex(text)) {
    return [
      <span
        className="inline-block max-w-full overflow-x-auto align-baseline"
        dangerouslySetInnerHTML={{ __html: renderLatex(text, false) }}
        key="bare-latex"
      />,
    ];
  }

  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  const matches = hasExplicitDelimiters(text)
    ? text.matchAll(MATH_DELIMITER_RE)
    : text.matchAll(BARE_LATEX_COMMAND_RE);

  for (const match of matches) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      nodes.push(text.slice(lastIndex, index));
    }

    const latex = match[1] ?? match[2] ?? match[3] ?? match[4] ?? match[0] ?? "";
    const displayMode = hasExplicitDelimiters(text) && Boolean(match[2] || match[3]);
    nodes.push(
      <span
        className={displayMode ? "my-2 block overflow-x-auto" : "inline-block align-baseline"}
        dangerouslySetInnerHTML={{ __html: renderLatex(latex, displayMode) }}
        key={`${index}-${latex}`}
      />,
    );
    lastIndex = index + match[0].length;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes.length ? nodes : [text];
}

function hasExplicitDelimiters(text: string) {
  return /\\\(|\\\[|\$\$|\$[^$\n]+?\$/.test(text);
}

function looksLikeStandaloneLatex(text: string) {
  if (!text.includes("\\")) {
    return looksLikePlainEquation(text);
  }
  if (!BARE_EQUATION_HINT_RE.test(text)) {
    return false;
  }
  const proseWordCount = text
    .replace(/\\[a-zA-Z]+/g, " ")
    .split(/\s+/)
    .filter((word) => /^[a-zA-Z]{3,}$/.test(word)).length;
  return proseWordCount <= 2;
}

function looksLikePlainEquation(text: string) {
  if (!/[=^_]/.test(text)) {
    return false;
  }
  if (!/^[a-zA-Z0-9\s+\-*/=^_{}().,]+$/.test(text)) {
    return false;
  }
  const proseWordCount = text
    .split(/\s+/)
    .filter((word) => /^[a-zA-Z]{3,}$/.test(word)).length;
  return proseWordCount <= 1;
}

function renderLatex(latex: string, displayMode: boolean) {
  return katex.renderToString(latex, {
    displayMode,
    throwOnError: false,
    strict: false,
  });
}
