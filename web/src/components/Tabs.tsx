import { useId } from "react";
import type { ReactNode } from "react";

export default function Tabs({ label, items, value, onChange, children, toolbar }: {
  label: string;
  items: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
  toolbar?: ReactNode;
}) {
  const id = useId();
  const tabs = <div className="research-tabs" role="tablist" aria-label={label}>
      {items.map((item, index) => <button key={item.value} id={`${id}-${item.value}`} type="button"
        role="tab" aria-selected={item.value === value} aria-controls={`${id}-panel`}
        tabIndex={item.value === value ? 0 : -1} onClick={() => onChange(item.value)}
        onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1
            : (index + (event.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
          onChange(items[next].value);
          document.getElementById(`${id}-${items[next].value}`)?.focus();
        }}>{item.label}</button>)}
    </div>;
  return <>
    {toolbar ? <div className="research-tab-controls">{tabs}{toolbar}</div> : tabs}
    <div className="workspace-tab-panel" id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${value}`}>{children}</div>
  </>;
}
