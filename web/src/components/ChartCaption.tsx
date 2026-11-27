export default function ChartCaption({
  title,
  meta,
  disclaimer = "",
}: {
  title: string;
  meta: string;
  disclaimer?: string;
}) {
  return (
    <div className="chart-caption">
      <span>
        <strong>{title}</strong>
        {meta ? <span> · {meta}</span> : null}
      </span>
      {disclaimer ? <span className="chart-disclaimer">{disclaimer}</span> : null}
    </div>
  );
}
