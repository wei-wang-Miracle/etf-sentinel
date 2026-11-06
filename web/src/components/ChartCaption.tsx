export default function ChartCaption({
  title,
  meta,
  disclaimer = "仅供研究，不构成投资建议",
}: {
  title: string;
  meta: string;
  disclaimer?: string;
}) {
  return (
    <div className="chart-caption">
      <span>
        <strong>{title}</strong>
        <span> · {meta}</span>
      </span>
      <span className="chart-disclaimer">{disclaimer}</span>
    </div>
  );
}
