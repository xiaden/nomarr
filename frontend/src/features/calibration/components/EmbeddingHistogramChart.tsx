import { BarChart } from "@mui/x-charts/BarChart";

interface EmbeddingHistogramChartProps {
  xLabels: string[];
  counts: number[];
}

export function EmbeddingHistogramChart({ xLabels, counts }: EmbeddingHistogramChartProps) {
  return (
    <BarChart
      xAxis={[
        {
          data: xLabels,
          barGapRatio: 0.1,
          tickPlacement: 'middle', 
        },
      ]}
      series={[{ data: counts }]}
      height={350}
      skipAnimation={true}
      renderer={'svg-batch'}
      sx={{
        minWidth: 200,
        width: '100%'
      }}
    />
  );
}
