"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { colorAt, formatAxisLabel, resolveSeries, sortByField } from "@/lib/chart-utils";
import type { VisualizationResponse } from "@/types/api";
import { formatLabel, formatMetricValue } from "@/lib/utils";

function formatTooltipValue(value: unknown, format: string) {
  return formatMetricValue(typeof value === "number" || typeof value === "string" ? value : null, format);
}

interface ChartRendererProps {
  data: Record<string, unknown>[];
  visualization: VisualizationResponse;
}

function getNumericValue(row: Record<string, unknown>, key: string) {
  const value = row[key];
  return typeof value === "number" ? value : Number(value ?? 0);
}

export function ChartRenderer({ data, visualization }: ChartRendererProps) {
  const xKey = visualization.x_axis?.field ?? "label";
  const series = resolveSeries(visualization);
  const yKey = series[0].field;
  const valueFormat = series[0].format ?? "text";
  const showLegend = series.length > 1;

  if (!data.length) {
    return <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">No chart data available.</div>;
  }

  const commonProps = {
    data,
    margin: { top: 12, right: 12, bottom: 12, left: 12 },
  };
  const tooltip = (
    <Tooltip
      formatter={(value, name) => [formatTooltipValue(value, valueFormat), formatLabel(String(name))]}
    />
  );
  const legend = showLegend ? <Legend formatter={(name) => formatLabel(String(name))} /> : null;

  switch (visualization.type) {
    case "bar":
      return (
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart {...commonProps}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              {tooltip}
              {legend}
              {series.map((axis, index) => (
                <Bar key={axis.field} dataKey={axis.field} radius={[8, 8, 0, 0]} fill={colorAt(index)} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      );
    case "line":
      return (
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart {...commonProps} data={sortByField(data, xKey)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} tickFormatter={formatAxisLabel} />
              <YAxis tick={{ fontSize: 12 }} />
              {tooltip}
              {legend}
              {series.map((axis, index) => (
                <Line
                  key={axis.field}
                  type="monotone"
                  dataKey={axis.field}
                  stroke={colorAt(index)}
                  strokeWidth={3}
                  dot={{ r: 3 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      );
    case "area":
      return (
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart {...commonProps} data={sortByField(data, xKey)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} tickFormatter={formatAxisLabel} />
              <YAxis tick={{ fontSize: 12 }} />
              {tooltip}
              {legend}
              {series.map((axis, index) => (
                <Area
                  key={axis.field}
                  type="monotone"
                  dataKey={axis.field}
                  stroke={colorAt(index)}
                  fill={colorAt(index)}
                  fillOpacity={0.2}
                  strokeWidth={2}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </div>
      );
    case "pie": {
      const pieData = data.map((entry) => ({
        name: String(entry[xKey] ?? "Unknown"),
        value: getNumericValue(entry as Record<string, unknown>, yKey),
      }));
      return (
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" outerRadius={110} innerRadius={40} paddingAngle={2}>
                {pieData.map((entry, index) => (
                  <Cell key={`${entry.name}-${index}`} fill={colorAt(index)} />
                ))}
              </Pie>
              <Tooltip formatter={(value) => formatTooltipValue(value, valueFormat)} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      );
    }
    default:
      return <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">Table output is shown below.</div>;
  }
}
