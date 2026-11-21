import { QuietButton } from "./ui";
import { TIME_CHOICES } from "../testPlan";

export type PlanMode = "time" | "count";

export function PlanModeSwitch({
  mode,
  onChange,
  timeBody = "Choose 15 minutes, 30 minutes, 45 minutes, 1 hour, 2 hours, or 3 hours. The number of each question that fits is shown for that period.",
  countTitle = "Go by number of questions",
  countBody = "Set how many of each question you want. The time for that paper is calculated from those numbers.",
}: {
  mode: PlanMode;
  onChange: (mode: PlanMode) => void;
  timeBody?: string;
  countTitle?: string;
  countBody?: string;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2" role="group" aria-label="How to choose the test">
      <ChoiceCard pressed={mode === "time"} title="Go by time" body={timeBody} onClick={() => onChange("time")} />
      <ChoiceCard pressed={mode === "count"} title={countTitle} body={countBody} onClick={() => onChange("count")} />
    </div>
  );
}

function ChoiceCard({ pressed, title, body, onClick }: { pressed: boolean; title: string; body: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className={`rounded-2xl border p-4 text-left ${pressed ? "border-accent ring-2 ring-accent" : "border-line"}`}
    >
      <span className="block font-semibold">{title}</span>
      <span className="mt-1 block text-sm font-normal text-muted">{body}</span>
    </button>
  );
}

export function TimeChoices({ minutes, onChange, label }: { minutes: number; onChange: (minutes: number) => void; label: string }) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label={label}>
      {TIME_CHOICES.map((choice) => (
        <QuietButton key={choice.minutes} pressed={choice.minutes === minutes} onClick={() => onChange(choice.minutes)}>
          {choice.label}
        </QuietButton>
      ))}
    </div>
  );
}
