"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { VisualizationResponse } from "@/types/api";
import { formatMetricValue } from "@/lib/utils";

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
  const yKey = visualization.y_axis?.field ?? "value";

  if (!data.length) {
    return <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">No chart data available.</div>;
  }

  const commonProps = {
    data,
    margin: { top: 12, right: 12, bottom: 12, left: 12 },
  };

  switch (visualization.type) {
    case "bar":
      return (
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart {...commonProps}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value) => formatTooltipValue(value, visualization.y_axis?.format ?? "text")} />
              <Bar dataKey={yKey} radius={[8, 8, 0, 0]} fill="#2563eb" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      );
    case "line":
      return (
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart {...commonProps}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value) => formatTooltipValue(value, visualization.y_axis?.format ?? "text")} />
              <Line type="monotone" dataKey={yKey} stroke="#2563eb" strokeWidth={3} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      );
    case "area":
      return (
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart {...commonProps}>
              <defs>
                <linearGradient id="fillArea" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0.1} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey={xKey} tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(value) => formatTooltipValue(value, visualization.y_axis?.format ?? "text")} />
              <Area type="monotone" dataKey={yKey} stroke="#2563eb" fill="url(#fillArea)" strokeWidth={2} />
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
                  <Cell key={`${entry.name}-${index}`} fill={['#2563eb', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444'][index % 5]} />
                ))}
              </Pie>
              <Tooltip formatter={(value) => formatTooltipValue(value, visualization.y_axis?.format ?? "text")} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      );
    }
    default:
      return <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">Table output is shown below.</div>;
  }
}
