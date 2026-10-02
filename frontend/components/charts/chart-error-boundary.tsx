"use client";

import { Component, type ReactNode } from "react";

interface ChartErrorBoundaryProps {
  children: ReactNode;
}

interface ChartErrorBoundaryState {
  hasError: boolean;
}

export class ChartErrorBoundary extends Component<ChartErrorBoundaryProps, ChartErrorBoundaryState> {
  state: ChartErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ChartErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div role="status" className="flex h-48 items-center justify-center rounded-md bg-slate-50 text-sm text-slate-600">
          Chart unavailable. The result table is still available below.
        </div>
      );
    }
    return this.props.children;
  }
}
