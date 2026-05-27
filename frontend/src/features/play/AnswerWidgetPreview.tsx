import { CheckSquare, LocateFixed, MousePointer2, Rows3, Shuffle, TextCursorInput } from "lucide-react";

import type { AnswerWidget } from "../../api/types";
import { InlineMathText } from "./MathText";

const widgetLabels: Record<AnswerWidget["type"], string> = {
  text_input: "Text answer",
  list_input: "List race input",
  multiple_choice: "Multiple choice",
  ordering: "Ordering",
  matching: "Matching",
  image_choice: "Image choice",
  hotspot: "Hotspot",
};

export function AnswerWidgetPreview({ widget }: { widget: AnswerWidget }) {
  const Icon = iconFor(widget.type);
  return (
    <div className="rounded-md border border-softline bg-white p-3">
      <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase text-midnight/60">
        <Icon className="h-4 w-4" />
        {widgetLabels[widget.type]}
      </div>
      <WidgetBody widget={widget} />
    </div>
  );
}

function iconFor(type: AnswerWidget["type"]) {
  switch (type) {
    case "text_input":
      return TextCursorInput;
    case "list_input":
      return Rows3;
    case "multiple_choice":
      return CheckSquare;
    case "ordering":
      return Shuffle;
    case "matching":
      return Shuffle;
    case "image_choice":
      return MousePointer2;
    case "hotspot":
      return LocateFixed;
  }
}

function WidgetBody({ widget }: { widget: AnswerWidget }) {
  switch (widget.type) {
    case "text_input":
      return (
        <div className="min-h-10 w-full rounded-md border border-softline bg-paper px-3 py-2 text-sm leading-5 text-midnight/55">
          {widget.placeholder ?? "Type answer"}
        </div>
      );
    case "list_input":
      return (
        <div className="min-h-10 w-full rounded-md border border-softline bg-paper px-3 py-2 text-sm leading-5 text-midnight/55">
          {widget.placeholder ?? "Type an item and press Enter"}
        </div>
      );
    case "multiple_choice":
      {
        const choices = multipleChoiceLabels(widget);
        return (
          <div className="grid gap-2 sm:grid-cols-2">
            {choices.map((choice) => (
              <button
                className="rounded-md border border-softline bg-paper px-3 py-2 text-left text-sm leading-5"
                key={choice}
                type="button"
              >
                <InlineMathText text={choice} />
              </button>
            ))}
          </div>
        );
      }
    case "ordering":
      {
        const items = "items" in widget && Array.isArray(widget.items)
          ? widget.items
          : multipleChoiceLabels({ type: "multiple_choice", choices: "choices" in widget && Array.isArray(widget.choices) ? widget.choices : [] });
        return (
          <ol className="space-y-2">
            {items.map((item, index) => (
              <li className="rounded-md border border-softline bg-paper px-3 py-2 text-sm" key={`${item}-${index}`}>
                {index + 1}. <InlineMathText text={item} />
              </li>
            ))}
          </ol>
        );
      }
    case "matching":
      {
        const left = Array.isArray(widget.left) ? widget.left : [];
        const right = Array.isArray(widget.right) ? widget.right : [];
        const fallback = "choices" in widget && Array.isArray(widget.choices) ? widget.choices : [];
        const midpoint = Math.ceil(fallback.length / 2);
        const leftItems = left.length ? left : fallback.slice(0, midpoint);
        const rightItems = right.length ? right : fallback.slice(midpoint);
        return (
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-2">
              {leftItems.map((item, index) => (
                <div className="rounded-md border border-softline bg-paper px-3 py-2 text-sm" key={`${item}-${index}`}>
                  <InlineMathText text={item} />
                </div>
              ))}
            </div>
            <div className="space-y-2">
              {rightItems.map((item, index) => (
                <div className="rounded-md border border-softline bg-paper px-3 py-2 text-sm" key={`${item}-${index}`}>
                  <InlineMathText text={item} />
                </div>
              ))}
            </div>
          </div>
        );
      }
    case "image_choice":
      return (
        <div className="grid gap-2 sm:grid-cols-3">
          {widget.images.map((image, index) => (
            <div className="aspect-video rounded-md border border-softline bg-paper p-2 text-xs" key={index}>
              <InlineMathText text={image.label ?? image.alt ?? "Image option"} />
            </div>
          ))}
        </div>
      );
    case "hotspot":
      return (
        <div className="aspect-video rounded-md border border-dashed border-softline bg-paper p-3 text-sm text-midnight/60">
          Click target preview
        </div>
      );
  }
}

function multipleChoiceLabels(
  widget: Extract<AnswerWidget, { type: "multiple_choice" }>,
): string[] {
  if (widget.choices?.length) {
    return widget.choices;
  }

  return (widget.options ?? []).map((option) => {
    if (typeof option === "string") {
      return option;
    }
    return option.text ?? option.label ?? option.id ?? "Option";
  });
}
