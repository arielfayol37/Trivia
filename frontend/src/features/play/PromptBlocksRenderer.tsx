import { ImageIcon, Table2 } from "lucide-react";
import { useState } from "react";

import type { PromptBlock } from "../../api/types";
import { InlineMathText, MathBlock } from "./MathText";

export function PromptBlocksRenderer({
  blocks,
  variant = "preview",
}: {
  blocks: PromptBlock[];
  variant?: "preview" | "play";
}) {
  return (
    <div className={variant === "play" ? "space-y-5" : "space-y-3"}>
      {blocks.map((block, index) => (
        <PromptBlockView block={block} key={`${block.type}-${index}`} variant={variant} />
      ))}
    </div>
  );
}

function PromptBlockView({
  block,
  variant,
}: {
  block: PromptBlock;
  variant: "preview" | "play";
}) {
  const isPlay = variant === "play";

  switch (block.type) {
    case "text":
      return (
        <p className={isPlay ? "text-xl leading-8 text-midnight sm:text-2xl sm:leading-10" : "text-sm leading-6 text-midnight"}>
          <InlineMathText text={block.text} />
        </p>
      );
    case "math":
      return <MathBlock latex={block.latex} />;
    case "source_excerpt":
      return (
        <blockquote
          className={
            isPlay
              ? "border-l-4 border-stagegold bg-paper px-5 py-4 text-lg leading-8"
              : "border-l-4 border-stagegold bg-paper px-4 py-3 text-sm leading-6"
          }
        >
          <InlineMathText text={block.text} />
          {block.citation ? <cite className="mt-2 block text-xs text-midnight/60">{block.citation}</cite> : null}
        </blockquote>
      );
    case "image":
      return <ImagePromptBlock block={block} isPlay={isPlay} />;
    case "table":
      return (
        <div className="overflow-hidden rounded-md border border-softline bg-white">
          <div className="flex items-center gap-2 border-b border-softline bg-paper px-3 py-2 text-xs font-medium uppercase text-midnight/60">
            <Table2 className="h-4 w-4" />
            Table
          </div>
          <table className="w-full text-left text-sm">
            <thead className="bg-paper">
              <tr>
                {block.columns.map((column) => (
                  <th
                    className={`border-b border-softline px-3 py-2 font-medium ${isPlay ? "text-base" : ""}`}
                    key={column}
                  >
                    <InlineMathText text={column} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td className={`border-b border-softline px-3 py-2 ${isPlay ? "text-base" : ""}`} key={cellIndex}>
                      <InlineMathText text={String(cell)} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "diagram_spec":
      return (
        <div className="rounded-md border border-softline bg-paper p-4">
          <div className="text-xs font-medium uppercase text-midnight/60">Diagram</div>
          <div className="mt-2 text-sm font-medium">{block.title ?? "Structured diagram"}</div>
          <pre className="mt-3 max-h-40 overflow-auto rounded bg-white p-3 text-xs">
            {JSON.stringify(block.spec ?? {}, null, 2)}
          </pre>
        </div>
      );
  }
}

function ImagePromptBlock({
  block,
  isPlay,
}: {
  block: Extract<PromptBlock, { type: "image" }>;
  isPlay: boolean;
}) {
  const [failed, setFailed] = useState(false);

  if (!block.url || failed) {
    return (
      <div className="flex items-center gap-2 rounded-md border border-dashed border-softline bg-paper p-4 text-sm text-midnight/60">
        <ImageIcon className="h-4 w-4" />
        {failed ? "Image URL could not be loaded" : "Image block pending asset"}
      </div>
    );
  }

  return (
    <figure className="overflow-hidden rounded-md border border-softline bg-white">
      <img
        alt={block.alt ?? ""}
        className={`${isPlay ? "max-h-[56vh]" : "max-h-80"} w-full object-contain`}
        onError={() => setFailed(true)}
        src={block.url}
      />
      {block.caption ? (
        <figcaption className="px-3 py-2 text-xs text-midnight/60">{block.caption}</figcaption>
      ) : null}
    </figure>
  );
}
